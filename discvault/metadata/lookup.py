"""Metadata provider orchestrator."""
from __future__ import annotations

from ..config import Config
from .types import DiscInfo, Metadata
from . import musicbrainz, gnudb, cdtext, local


def fetch_candidates(
    disc_info: DiscInfo,
    cfg: Config,
    debug: bool = False,
    sources: dict | None = None,
) -> list[Metadata]:
    """
    Query metadata providers and return a deduplicated list of candidates.

    Order: Local CDDB cache → MusicBrainz → GnuDB HTTP → GnuDB CDDBP → CD-Text
    sources: dict with boolean keys "musicbrainz", "gnudb", "cdtext".
             Defaults to all enabled.
    """
    if sources is None:
        sources = {}
    use_mb = sources.get("musicbrainz", True)
    use_gnudb = sources.get("gnudb", True)
    use_cdtext = sources.get("cdtext", True)

    results: list[Metadata] = []

    def _add(metas: list[Metadata]) -> None:
        for m in metas:
            if m not in results:
                results.append(m)

    # 0. Local CDDB cache
    if cfg.use_local_cddb_cache and disc_info.freedb_disc_id:
        if debug:
            print("[metadata-debug] Checking local CDDB cache...")
        _add(local.lookup(disc_info, debug=debug))

    # 1. MusicBrainz
    if use_mb and (disc_info.mb_disc_id or disc_info.mb_toc):
        if debug:
            print("[metadata-debug] Querying MusicBrainz...")
        _add(musicbrainz.lookup(disc_info, timeout=cfg.metadata_timeout, debug=debug))

    # 2. GnuDB HTTP + CDDBP
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

    # 3. CD-Text
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

    return results
