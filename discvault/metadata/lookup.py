"""Metadata provider orchestrator."""
from __future__ import annotations

from ..config import Config
from .types import DiscInfo, Metadata
from . import musicbrainz, gnudb, cdtext, local


def fetch_candidates(
    disc_info: DiscInfo,
    cfg: Config,
    debug: bool = False,
) -> list[Metadata]:
    """
    Query all metadata providers and return a deduplicated list of candidates.

    Order: MusicBrainz → GnuDB HTTP → GnuDB CDDBP → Local CDDB → CD-Text
    """
    results: list[Metadata] = []

    def _add(metas: list[Metadata]) -> None:
        for m in metas:
            if m not in results:
                results.append(m)

    # 1. MusicBrainz
    if disc_info.mb_disc_id or disc_info.mb_toc:
        if debug:
            print("[metadata-debug] Querying MusicBrainz...")
        _add(musicbrainz.lookup(disc_info, timeout=cfg.metadata_timeout, debug=debug))

    # 2. GnuDB HTTP
    if disc_info.freedb_disc_id:
        hello_values = gnudb.build_hello_values(
            cfg.gnudb.hello_user, cfg.gnudb.hello_program, cfg.gnudb.hello_version
        )
        if debug:
            print("[metadata-debug] Querying GnuDB HTTP...")
        _add(gnudb.lookup_http(disc_info, hello_values, timeout=cfg.metadata_timeout, debug=debug))

        # 3. GnuDB CDDBP
        if cfg.gnudb.host:
            if debug:
                print(f"[metadata-debug] Querying GnuDB CDDBP ({cfg.gnudb.host}:{cfg.gnudb.port})...")
            _add(gnudb.lookup_cddbp(
                disc_info, hello_values,
                host=cfg.gnudb.host,
                port=cfg.gnudb.port,
                timeout=cfg.metadata_timeout,
                debug=debug,
            ))

    # 4. Local CDDB cache
    if disc_info.freedb_disc_id:
        if debug:
            print("[metadata-debug] Checking local CDDB cache...")
        _add(local.lookup(disc_info, debug=debug))

    # 5. CD-Text
    if debug:
        print("[metadata-debug] Reading CD-Text...")
    _add(cdtext.lookup(disc_info, debug=debug))

    return results
