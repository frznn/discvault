"""Disc TOC reading and disc ID extraction."""
from __future__ import annotations
import re
import shutil
import subprocess

from .metadata.types import DiscInfo


def load_disc_info(device: str) -> DiscInfo:
    """
    Build a DiscInfo from the disc in *device*.

    Tries, in order:
      1. `discid`  (MusicBrainz disc ID + freedb disc ID)
      2. `cd-discid --musicbrainz`  (MB TOC)
      3. `cd-discid`  (freedb disc ID + offsets)
    """
    info = DiscInfo(device=device)

    if shutil.which("discid"):
        _try_discid(device, info)
    if not info.track_offsets and shutil.which("cd-discid"):
        _try_cd_discid_mb(device, info)
    if not info.track_offsets and shutil.which("cd-discid"):
        _try_cd_discid(device, info)

    return info


# ---------------------------------------------------------------------------
# discid binary (MusicBrainz discid)
# ---------------------------------------------------------------------------

def _try_discid(device: str, info: DiscInfo) -> None:
    # `discid` alone outputs the MB disc ID
    try:
        r = subprocess.run(["discid", device], capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split()
        if parts:
            info.mb_disc_id = parts[0]
    except Exception:
        pass

    # `discid -f` outputs freedb format: discid first last leadout off1 off2 ...
    try:
        r = subprocess.run(["discid", "-f", device], capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split()
        if len(parts) >= 5:
            freedb_id, first, last, leadout = parts[0], parts[1], parts[2], parts[3]
            if all(p.isdigit() for p in (first, last, leadout)):
                track_count = int(last) - int(first) + 1
                offsets = parts[4:4 + track_count]
                if len(offsets) == track_count:
                    info.freedb_disc_id = freedb_id
                    info.track_count = track_count
                    info.track_offsets = [int(o) for o in offsets]
                    info.leadout = int(leadout)
    except Exception:
        pass

    _build_mb_toc(info)


# ---------------------------------------------------------------------------
# cd-discid --musicbrainz
# ---------------------------------------------------------------------------

def _try_cd_discid_mb(device: str, info: DiscInfo) -> None:
    try:
        r = subprocess.run(
            ["cd-discid", "--musicbrainz", device],
            capture_output=True, text=True, timeout=15,
        )
        parts = r.stdout.strip().split()
        # format: ntracks off1 off2 ... leadout
        if len(parts) >= 3:
            track_count = int(parts[0])
            if track_count > 0 and len(parts) >= track_count + 2:
                offsets = [int(p) for p in parts[1:1 + track_count]]
                leadout = int(parts[track_count + 1])
                info.track_count = track_count
                info.track_offsets = offsets
                info.leadout = leadout
                _build_mb_toc(info)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# cd-discid (freedb format)
# ---------------------------------------------------------------------------

def _try_cd_discid(device: str, info: DiscInfo) -> None:
    try:
        r = subprocess.run(
            ["cd-discid", device],
            capture_output=True, text=True, timeout=15,
        )
        parts = r.stdout.strip().split()
        # format: discid ntracks off1 off2 ... total_seconds
        if len(parts) >= 4:
            freedb_id = parts[0]
            track_count = int(parts[1])
            if track_count > 0 and len(parts) >= 3 + track_count:
                offsets = [int(p) for p in parts[2:2 + track_count]]
                total_sec = int(parts[2 + track_count])
                # Reconstruct approximate leadout
                leadout = offsets[0] + total_sec * 75 if offsets else 0
                info.freedb_disc_id = freedb_id
                info.track_count = track_count
                info.track_offsets = offsets
                info.leadout = leadout
                _build_mb_toc(info)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_mb_toc(info: DiscInfo) -> None:
    """Construct MB TOC string from offsets if mb_disc_id is not available."""
    if info.mb_toc or info.mb_disc_id:
        return
    if info.track_offsets and info.leadout:
        info.mb_toc = f"1 {info.track_count} {info.leadout} " + " ".join(
            str(o) for o in info.track_offsets
        )
