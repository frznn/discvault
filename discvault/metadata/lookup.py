"""Metadata provider orchestrator."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from ..config import Config, DEFAULT_METADATA_SOURCE_ORDER, METADATA_SOURCE_KEYS
from .sanitize import trim
from .types import DiscInfo, Metadata
from . import musicbrainz, gnudb, local, discogs, fileimport, urlimport, cdtext


@dataclass
class LookupCallbacks:
    on_start: Callable[[str], None] | None = None
    # on_success / on_error receive the provider's wall-clock duration (seconds)
    # measured around the provider call. Consumers can render or ignore it.
    on_success: Callable[[str, int, float], None] | None = None
    on_error: Callable[[str, str, float], None] | None = None
    on_skip: Callable[[str, str], None] | None = None
    on_info: Callable[[str], None] | None = None


def fetch_candidates(
    disc_info: DiscInfo,
    cfg: Config,
    debug: bool = False,
    sources: dict | None = None,
    metadata_file: str = "",
    metadata_url: str = "",
    manual_hints: tuple[str, str, str] | None = None,
    manual_query: str = "",
    *,
    manual_search: bool = False,
    manual_search_disc_info: DiscInfo | None = None,
    cdtext_driver: str = "",
    source_order: list[str] | None = None,
    callbacks: LookupCallbacks | None = None,
) -> list[Metadata]:
    """
    Query metadata providers and return a deduplicated list of candidates.

    Automatic lookup runs imports first (file → URL), then the local CDDB cache,
    then the user-priority online providers (CD-Text, MusicBrainz, GnuDB) in the
    order given by ``source_order`` (falling back to ``cfg.metadata_source_order``
    and then the default order).

    Manual search providers are separate from normal disc lookup. When
    ``manual_search`` is true, this function queries MusicBrainz text search
    (if enabled) and Discogs using the explicit search terms or manual hints.
    """
    if sources is None:
        sources = {}
    use_file = sources.get("file", bool(metadata_file))
    use_url = sources.get("url", bool(metadata_url))
    use_cdtext = sources.get("cdtext", True)
    use_mb = sources.get("musicbrainz", True)
    use_gnudb = sources.get("gnudb", True)
    ordered_sources = _resolve_source_order(source_order, cfg)
    hint_artist = hint_album = hint_year = ""
    if manual_hints:
        hint_artist, hint_album, hint_year = (trim(part) for part in manual_hints)
    manual_query = trim(manual_query)
    has_manual_terms = bool(manual_query or hint_artist or hint_album)
    search_disc_info = manual_search_disc_info or disc_info

    results: list[Metadata] = []
    dedupe_equivalent = cfg.dedupe_equivalent_candidates

    def _add(metas: list[Metadata]) -> None:
        for m in metas:
            if dedupe_equivalent:
                duplicate = any(_metadata_equivalent(m, existing) for existing in results)
            else:
                duplicate = m in results
            if not duplicate:
                results.append(m)

    def _start(label: str) -> None:
        if callbacks and callbacks.on_start:
            callbacks.on_start(label)

    def _success(label: str, count: int, duration: float = 0.0) -> None:
        if callbacks and callbacks.on_success:
            callbacks.on_success(label, count, duration)

    def _error(label: str, message: str, duration: float = 0.0) -> None:
        if callbacks and callbacks.on_error:
            callbacks.on_error(label, message, duration)

    def _skip(label: str, reason: str) -> None:
        if callbacks and callbacks.on_skip:
            callbacks.on_skip(label, reason)

    def _info(message: str) -> None:
        if callbacks and callbacks.on_info:
            callbacks.on_info(message)

    def _run(label: str, func: Callable[[], list[Metadata]]) -> None:
        _start(label)
        start = time.monotonic()
        try:
            found = func()
        except Exception as exc:
            _error(label, str(exc), time.monotonic() - start)
            return
        duration = time.monotonic() - start
        _add(found)
        _success(label, len(found), duration)

    # 0. Imported metadata file
    if use_file and metadata_file:
        label = "Imported metadata file"
        _run(label, lambda: fileimport.lookup(metadata_file, debug=debug))

    # 0b. Metadata URL import
    if use_url and metadata_url:
        label = "Imported metadata URL"
        _start(label)
        url_start = time.monotonic()
        try:
            found = urlimport.lookup_url(
                metadata_url,
                disc_info=disc_info,
                timeout=cfg.metadata_timeout,
                debug=debug,
                token=cfg.discogs.token,
            )
        except ValueError as exc:
            _error(label, str(exc), time.monotonic() - url_start)
        except Exception as exc:
            _error(label, str(exc), time.monotonic() - url_start)
        else:
            url_duration = time.monotonic() - url_start
            _add(found)
            _success(label, len(found), url_duration)

    if manual_search:
        use_discogs = sources.get("discogs", True)
        if use_mb:
            if has_manual_terms:
                _run(
                    "MusicBrainz search",
                    lambda: musicbrainz.search_releases(
                        hint_artist,
                        hint_album,
                        year=hint_year,
                        query=manual_query,
                        disc_info=search_disc_info,
                        timeout=cfg.metadata_timeout,
                        debug=debug,
                    ),
                )
            else:
                _skip("MusicBrainz search", "no search terms")
        elif not has_manual_terms:
            _skip("MusicBrainz search", "disabled and no search terms")

        if use_discogs:
            if has_manual_terms:
                if not cfg.discogs.token.strip():
                    _info("Discogs: using anonymous access; a token improves reliability and rate limits")
                _run(
                    "Discogs",
                    lambda: discogs.lookup(
                        search_disc_info,
                        seed_candidates=results,
                        artist=hint_artist,
                        album=hint_album,
                        year=hint_year,
                        query=manual_query,
                        token=cfg.discogs.token,
                        timeout=cfg.metadata_timeout,
                        debug=debug,
                    ),
                )
            else:
                _skip("Discogs", "no search terms")
        else:
            _skip("Discogs", "disabled in Manual Search")
        return results

    short_circuit = bool(getattr(cfg, "lookup_stop_at_first_match", True))

    # Local CDDB cache runs before online providers regardless of order — it
    # is a free short-circuit and not part of the user-editable priority list.
    cache_before = len(results)
    if cfg.use_local_cddb_cache and disc_info.freedb_disc_id:
        _run("Local CDDB cache", lambda: local.lookup(disc_info, debug=debug))
    elif cfg.use_local_cddb_cache:
        _skip("Local CDDB cache", "no FreeDB disc ID")
    if short_circuit and len(results) > cache_before:
        return results

    for key in ordered_sources:
        before = len(results)
        if key == "cdtext":
            if not use_cdtext:
                continue
            if disc_info.device:
                _run(
                    "CD-Text",
                    lambda: cdtext.lookup(
                        disc_info,
                        driver=cdtext_driver,
                        timeout=cfg.metadata_timeout,
                        debug=debug,
                    ),
                )
            else:
                _skip("CD-Text", "no disc device")
        elif key == "musicbrainz":
            if not use_mb:
                continue
            if disc_info.mb_disc_id or disc_info.mb_toc:
                _run(
                    "MusicBrainz",
                    lambda: musicbrainz.lookup(
                        disc_info,
                        timeout=cfg.metadata_timeout,
                        debug=debug,
                    ),
                )
            else:
                _skip("MusicBrainz", "no disc ID")
        elif key == "gnudb":
            if not use_gnudb:
                continue
            if disc_info.freedb_disc_id:
                # Limit to first hello string — trying all variants multiplies requests
                hello_values = gnudb.build_hello_values(
                    cfg.gnudb.hello_user, cfg.gnudb.hello_program, cfg.gnudb.hello_version
                )[:1]
                _run(
                    "GnuDB",
                    lambda hv=hello_values: gnudb.lookup_http(
                        disc_info,
                        hv,
                        timeout=cfg.metadata_timeout,
                        cache_enabled=cfg.use_local_cddb_cache,
                        debug=debug,
                    ),
                )
            else:
                _skip("GnuDB", "no FreeDB disc ID")

        if short_circuit and len(results) > before:
            break

    if cfg.blank_redundant_track_artist:
        for meta in results:
            _blank_redundant_track_artists(meta)

    return results


def _metadata_equivalent(a: Metadata, b: Metadata) -> bool:
    """True iff two candidates match on every field except ``source`` and ``match_quality``."""
    return (
        a.album_artist == b.album_artist
        and a.album == b.album
        and a.year == b.year
        and a.tracks == b.tracks
        and a.cover_art_url == b.cover_art_url
        and a.cover_art_ext == b.cover_art_ext
        and a.mb_release_id == b.mb_release_id
        and a.mb_release_group_id == b.mb_release_group_id
        and a.discogs_release_id == b.discogs_release_id
    )


def _blank_redundant_track_artists(meta: Metadata) -> None:
    """Blank per-track Artist on a single-artist disc.

    A track artist that is empty already counts as "matches album artist" —
    sources commonly leave it empty when the track artist is the same as the
    album artist, and one stray empty cell shouldn't defeat the rule.
    """
    if not meta.tracks or not meta.album_artist:
        return
    album_artist = meta.album_artist
    for track in meta.tracks:
        if track.artist and track.artist != album_artist:
            return
    for track in meta.tracks:
        track.artist = ""


def _resolve_source_order(
    order: list[str] | None,
    cfg: Config,
) -> list[str]:
    candidates: list[str] = []
    if order:
        candidates = list(order)
    else:
        cfg_order = getattr(cfg, "metadata_source_order", None)
        if cfg_order:
            candidates = list(cfg_order)
    seen: set[str] = set()
    result: list[str] = []
    for item in candidates:
        key = item.strip().lower() if isinstance(item, str) else ""
        if key in METADATA_SOURCE_KEYS and key not in seen:
            result.append(key)
            seen.add(key)
    for key in DEFAULT_METADATA_SOURCE_ORDER:
        if key not in seen:
            result.append(key)
    return result
