"""Disc TOC reading and disc ID extraction."""
from __future__ import annotations
import importlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .metadata.types import DiscInfo


def load_disc_info(device: str, debug: bool = False) -> DiscInfo:
    """
    Build a DiscInfo from the disc in *device*.

    Tries, in order:
      1. `discid`  (MusicBrainz disc ID + freedb disc ID)
      2. `cd-discid --musicbrainz`  (MB TOC)
      3. `cd-discid`  (freedb disc ID + offsets)
    """
    info = DiscInfo(device=device)

    if shutil.which("discid"):
        _try_discid(device, info, debug=debug)
    elif _libdiscid_available():
        _try_libdiscid(device, info, debug=debug)
    if not info.track_offsets and shutil.which("cd-discid"):
        _try_cd_discid_mb(device, info, debug=debug)
    if not info.track_offsets and shutil.which("cd-discid"):
        _try_cd_discid(device, info, debug=debug)
    # Ensure freedb_disc_id is populated even when track_offsets came from
    # cd-discid --musicbrainz (which doesn't set the freedb ID).
    if not info.freedb_disc_id and shutil.which("cd-discid"):
        _try_cd_discid(device, info, debug=debug)
    if shutil.which("cd-info"):
        _try_cdinfo_track_modes(device, info, debug=debug)
    elif shutil.which("cdrdao"):
        _try_cdrdao_track_modes(device, info, debug=debug)

    if debug and not info.track_offsets:
        print("[disc-debug] Could not determine disc geometry from discid/cd-discid.")

    return info


def musicbrainz_lookup_notice(info: DiscInfo) -> str:
    """Return a note when MusicBrainz is limited to TOC fallback matching."""
    if info.mb_disc_id or not info.mb_toc:
        return ""
    if _exact_discid_support_available():
        return (
            "MusicBrainz automatic matching is using TOC fallback only for this disc, "
            "so results may be less accurate."
        )
    return (
        "MusicBrainz automatic matching is using TOC fallback only. "
        "Install discid for more accurate automatic matches."
    )


# ---------------------------------------------------------------------------
# discid binary (MusicBrainz discid)
# ---------------------------------------------------------------------------


def _exact_discid_support_available() -> bool:
    return bool(shutil.which("discid") or _libdiscid_available())


def _load_libdiscid():
    for module_name in ("discid", "libdiscid.compat.discid"):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            continue
    return None


def _libdiscid_available() -> bool:
    return _load_libdiscid() is not None

def _try_discid(device: str, info: DiscInfo, *, debug: bool = False) -> None:
    # `discid` alone outputs the MB disc ID
    try:
        r = subprocess.run(["discid", device], capture_output=True, text=True, timeout=15)
        parts = r.stdout.strip().split()
        if parts:
            info.mb_disc_id = parts[0]
    except Exception as exc:
        _debug(debug, f"discid disc ID lookup failed: {exc}")

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
    except Exception as exc:
        _debug(debug, f"discid freedb lookup failed: {exc}")

    _build_mb_toc(info)


def _try_libdiscid(device: str, info: DiscInfo, *, debug: bool = False) -> None:
    module = _load_libdiscid()
    if module is None:
        return

    try:
        disc = module.read(device)
    except Exception as exc:
        _debug(debug, f"python libdiscid lookup failed: {exc}")
        return

    info.mb_disc_id = str(getattr(disc, "id", "") or "").strip()
    info.freedb_disc_id = str(getattr(disc, "freedb_id", "") or "").strip()

    track_offsets = list(getattr(disc, "track_offsets", []) or [])
    leadout = int(getattr(disc, "sectors", 0) or 0)
    first_track = int(getattr(disc, "first_track_num", 1) or 1)
    last_track = int(getattr(disc, "last_track_num", 0) or 0)

    if track_offsets and leadout and last_track >= first_track:
        info.track_count = last_track - first_track + 1
        info.track_offsets = [int(offset) for offset in track_offsets[:info.track_count]]
        info.leadout = leadout

    toc_string = str(getattr(disc, "toc_string", "") or "").strip()
    if toc_string:
        info.mb_toc = toc_string
    else:
        _build_mb_toc(info)


# ---------------------------------------------------------------------------
# cd-discid --musicbrainz
# ---------------------------------------------------------------------------

def _try_cd_discid_mb(device: str, info: DiscInfo, *, debug: bool = False) -> None:
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
    except Exception as exc:
        _debug(debug, f"cd-discid --musicbrainz failed: {exc}")


# ---------------------------------------------------------------------------
# cd-discid (freedb format)
# ---------------------------------------------------------------------------

def _try_cd_discid(device: str, info: DiscInfo, *, debug: bool = False) -> None:
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
                info.freedb_disc_id = freedb_id
                # Only set geometry if not already populated (may come from a
                # more precise source like cd-discid --musicbrainz).
                if not info.track_offsets:
                    leadout = offsets[0] + total_sec * 75 if offsets else 0
                    info.track_count = track_count
                    info.track_offsets = offsets
                    info.leadout = leadout
                    _build_mb_toc(info)
    except Exception as exc:
        _debug(debug, f"cd-discid freedb lookup failed: {exc}")


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


_CDINFO_TRACK_MODE_RE = re.compile(r"^\s*track\s+(\d+):\s+(.+)$", re.IGNORECASE)


def _try_cdinfo_track_modes(device: str, info: DiscInfo, *, debug: bool = False) -> None:
    try:
        result = subprocess.run(
            [
                "cd-info",
                "--no-header",
                "--no-device-info",
                "--no-disc-mode",
                "-C",
                device,
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        _debug(debug, f"cd-info track-mode probe failed: {exc}")
        return

    if result.returncode != 0:
        _debug(debug, f"cd-info track-mode probe exited {result.returncode}")
        return

    modes: dict[int, str] = {}
    for line in result.stdout.splitlines():
        match = _CDINFO_TRACK_MODE_RE.match(line)
        if not match:
            continue
        track_num = int(match.group(1))
        description = match.group(2).strip().lower()
        if "audio" in description:
            modes[track_num] = "audio"
        elif "mode" in description or "data" in description:
            modes[track_num] = "data"

    if modes:
        info.track_modes.update(modes)


_CDRDAO_TRACK_MODE_RE = re.compile(r"^\s*TRACK\s+([A-Z0-9_/]+)", re.IGNORECASE)


def _try_cdrdao_track_modes(device: str, info: DiscInfo, *, debug: bool = False) -> None:
    with tempfile.TemporaryDirectory(prefix="discvault-track-modes-") as tmpdir:
        toc_path = Path(tmpdir) / "disc.toc"
        try:
            result = subprocess.run(
                [
                    "cdrdao",
                    "read-toc",
                    "--fast-toc",
                    "--device",
                    device,
                    str(toc_path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception as exc:
            _debug(debug, f"cdrdao track-mode probe failed: {exc}")
            return

        if result.returncode != 0 or not toc_path.exists():
            if result.returncode != 0:
                _debug(debug, f"cdrdao track-mode probe exited {result.returncode}")
            return

        current_track = 0
        modes: dict[int, str] = {}
        try:
            toc_text = toc_path.read_text(errors="replace")
        except OSError:
            return

        for line in toc_text.splitlines():
            match = _CDRDAO_TRACK_MODE_RE.match(line)
            if not match:
                continue
            current_track += 1
            mode = match.group(1).upper()
            modes[current_track] = "audio" if mode == "AUDIO" else "data"

        if modes:
            info.track_modes.update(modes)


def _debug(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[disc-debug] {message}")
