"""Metadata provider orchestrator."""
from __future__ import annotations

from ..config import Config
from .sanitize import trim
from .types import DiscInfo, Metadata
from . import musicbrainz, gnudb, cdtext, local, discogs, fileimport, urlimport


def fetch_candidates(
    disc_info: DiscInfo,
    cfg: Config,
    debug: bool = False,
    sources: dict | None = None,
    metadata_file: str = "",
    metadata_url: str = "",
    manual_hints: tuple[str, str, str] | None = None,
) -> list[Metadata]:
    """
    Query metadata providers and return a deduplicated list of candidates.

    Order: imported file → metadata URL → Local cache → MusicBrainz → GnuDB → CD-Text → Discogs
    sources: dict with boolean keys "file", "url", "musicbrainz", "gnudb", "cdtext", "discogs".
             Defaults to all enabled.
    """
    if sources is None:
        sources = {}
    use_file = sources.get("file", bool(metadata_file))
    use_url = sources.get("url", bool(metadata_url))
    use_mb = sources.get("musicbrainz", True)
    use_gnudb = sources.get("gnudb", True)
    use_cdtext = sources.get("cdtext", True)
    use_discogs = sources.get("discogs", True)
    hint_artist = hint_album = hint_year = ""
    if manual_hints:
        hint_artist, hint_album, hint_year = (trim(part) for part in manual_hints)
    has_manual_terms = bool(hint_artist and hint_album)

    results: list[Metadata] = []

    def _add(metas: list[Metadata]) -> None:
        for m in metas:
            if m not in results:
                results.append(m)

    # 0. Imported metadata file
    if use_file and metadata_file:
        if debug:
            print(f"[metadata-debug] Importing metadata file: {metadata_file}")
        _add(fileimport.lookup(metadata_file, debug=debug))

    # 0b. Metadata URL import
    if use_url and metadata_url:
        if debug:
            print(f"[metadata-debug] Importing metadata URL: {metadata_url}")
        try:
            _add(
                urlimport.lookup_url(
                    metadata_url,
                    disc_info=disc_info,
                    timeout=cfg.metadata_timeout,
                    debug=debug,
                )
            )
        except ValueError as exc:
            if debug:
                print(f"[metadata-debug] Metadata URL import skipped: {exc}")

    # 1. Local CDDB cache
    if cfg.use_local_cddb_cache and disc_info.freedb_disc_id:
        if debug:
            print("[metadata-debug] Checking local CDDB cache...")
        _add(local.lookup(disc_info, debug=debug))

    # 2. MusicBrainz
    if use_mb and (disc_info.mb_disc_id or disc_info.mb_toc):
        if debug:
            print("[metadata-debug] Querying MusicBrainz...")
        _add(musicbrainz.lookup(disc_info, timeout=cfg.metadata_timeout, debug=debug))
    if use_mb and has_manual_terms:
        if debug:
            print("[metadata-debug] Searching MusicBrainz by artist/album...")
        _add(
            musicbrainz.search_releases(
                hint_artist,
                hint_album,
                year=hint_year,
                disc_info=disc_info,
                timeout=cfg.metadata_timeout,
                debug=debug,
            )
        )

    # 3. GnuDB HTTP + CDDBP
    if use_gnudb and disc_info.freedb_disc_id:
        # Limit to first hello string — trying all variants multiplies requests
        hello_values = gnudb.build_hello_values(
            cfg.gnudb.hello_user, cfg.gnudb.hello_program, cfg.gnudb.hello_version
        )[:1]
        if debug:
            print("[metadata-debug] Querying GnuDB HTTP...")
        _add(
            gnudb.lookup_http(
                disc_info,
                hello_values,
                timeout=cfg.metadata_timeout,
                cache_enabled=cfg.use_local_cddb_cache,
                debug=debug,
            )
        )

        if cfg.gnudb.host:
            if debug:
                print(f"[metadata-debug] Querying GnuDB CDDBP ({cfg.gnudb.host}:{cfg.gnudb.port})...")
            _add(
                gnudb.lookup_cddbp(
                    disc_info,
                    hello_values,
                    host=cfg.gnudb.host,
                    port=cfg.gnudb.port,
                    timeout=cfg.metadata_timeout,
                    cache_enabled=cfg.use_local_cddb_cache,
                    debug=debug,
                )
            )

    # 4. CD-Text
    if use_cdtext:
        if debug:
            print("[metadata-debug] Reading CD-Text...")
        _add(
            cdtext.lookup(
                disc_info,
                driver=cfg.cdrdao_driver,
                timeout=cfg.metadata_timeout,
                debug=debug,
            )
        )

    # 5. Discogs, seeded by prior candidates or manual hints
    if use_discogs:
        if debug:
            print("[metadata-debug] Querying Discogs...")
        _add(
            discogs.lookup(
                disc_info,
                seed_candidates=results,
                artist=hint_artist,
                album=hint_album,
                year=hint_year,
                token=cfg.discogs.token,
                timeout=cfg.metadata_timeout,
                debug=debug,
            )
        )

    return results
