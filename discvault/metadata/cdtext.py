"""CD-Text metadata provider."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from .sanitize import trim
from .types import DiscInfo, Metadata, Track


def lookup(
    disc_info: DiscInfo,
    driver: str = "",
    timeout: int = 8,
    debug: bool = False,
) -> list[Metadata]:
    """Extract CD-Text from disc. Returns a list with 0 or 1 Metadata."""
    effective_timeout = max(5, min(timeout, 10))

    meta = _lookup_via_cdrdao(disc_info, driver=driver, timeout=effective_timeout, debug=debug)
    if meta:
        return [meta]

    meta = _lookup_via_cdinfo(disc_info, timeout=effective_timeout, debug=debug)
    if meta:
        return [meta]

    return []


def _lookup_via_cdrdao(
    disc_info: DiscInfo,
    driver: str,
    timeout: int,
    debug: bool,
) -> Metadata | None:
    cmd = ["cdrdao", "read-toc", "--fast-toc", "--device", disc_info.device]
    if driver:
        cmd.extend(["--driver", driver])

    with tempfile.TemporaryDirectory(prefix="discvault-cdtext-") as tmpdir:
        toc_path = Path(tmpdir) / "disc.toc"
        try:
            result = subprocess.run(
                [*cmd, str(toc_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            if toc_path.exists():
                try:
                    meta = _parse_cdrdao_toc(toc_path.read_text(errors="replace"))
                except OSError:
                    meta = None
                if meta:
                    return meta
            if debug:
                details = trim(
                    " ".join(
                        _coerce_output(part)
                        for part in (exc.stdout, exc.stderr)
                        if part
                    )
                )
                if details:
                    print(f"[metadata-debug] cdrdao timed out after {timeout}s: {details}")
                else:
                    print(f"[metadata-debug] cdrdao timed out after {timeout}s")
            return None
        except FileNotFoundError:
            if debug:
                print("[metadata-debug] cdrdao not found for CD-Text lookup")
            return None
        except Exception as exc:
            if debug:
                print(f"[metadata-debug] cdrdao CD-Text lookup failed: {exc}")
            return None

        if toc_path.exists():
            try:
                meta = _parse_cdrdao_toc(toc_path.read_text(errors="replace"))
            except OSError as exc:
                if debug:
                    print(f"[metadata-debug] Failed to read cdrdao TOC: {exc}")
                meta = None
            if meta:
                return meta

        if debug:
            details = trim(" ".join(part for part in (result.stdout, result.stderr) if part))
            if result.returncode != 0:
                if details:
                    print(f"[metadata-debug] cdrdao exited {result.returncode}: {details}")
                else:
                    print(f"[metadata-debug] cdrdao exited {result.returncode}")
            else:
                print("[metadata-debug] cdrdao TOC contained no CD-Text fields")

    return None


def _lookup_via_cdinfo(
    disc_info: DiscInfo,
    timeout: int,
    debug: bool,
) -> Metadata | None:
    cmd = [
        "cd-info",
        "--no-header",
        "--no-device-info",
        "--no-disc-mode",
        "-C",
        disc_info.device,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = _coerce_output(exc.stdout)
        meta = _parse_cdinfo_output(output)
        if meta:
            if debug:
                print(f"[metadata-debug] cd-info timed out after {timeout}s but yielded CD-Text")
            return meta
        if debug:
            print(f"[metadata-debug] cd-info timed out after {timeout}s with no CD-Text fields")
        return None
    except FileNotFoundError:
        if debug:
            print("[metadata-debug] cd-info not found")
        return None
    except Exception as exc:
        if debug:
            print(f"[metadata-debug] cd-info failed: {exc}")
        return None

    if result.returncode != 0:
        if debug:
            details = trim(result.stderr or result.stdout)
            if details:
                print(f"[metadata-debug] cd-info exited {result.returncode}: {details}")
            else:
                print(f"[metadata-debug] cd-info exited {result.returncode}")
        return None

    meta = _parse_cdinfo_output(result.stdout)
    if meta:
        return meta
    if debug:
        print("[metadata-debug] cd-info returned no CD-Text fields")
    return None


def _parse_cdrdao_toc(text: str) -> Metadata | None:
    album_artist = ""
    album = ""
    tracks: list[Track] = []

    current_track: int | None = None
    track_title: dict[int, str] = {}
    track_artist: dict[int, str] = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if stripped.startswith("TRACK "):
            current_track = 1 if current_track is None else current_track + 1
            continue

        if stripped.startswith("TITLE "):
            value = _parse_toc_value(stripped[6:])
            if current_track is None:
                album = value
            else:
                track_title[current_track] = value
            continue

        if stripped.startswith("PERFORMER "):
            value = _parse_toc_value(stripped[10:])
            if current_track is None:
                album_artist = value
            else:
                track_artist[current_track] = value

    if not album and not album_artist and not track_title:
        return None

    for num, title in sorted(track_title.items()):
        tracks.append(Track(number=num, title=title, artist=track_artist.get(num, "")))

    return Metadata(
        source="CD-Text",
        album_artist=album_artist,
        album=album,
        year="",
        tracks=tracks,
        match_quality="cdtext",
    )


def _parse_cdinfo_output(text: str) -> Metadata | None:
    album_artist = ""
    album = ""
    tracks: list[Track] = []

    current_track: int | None = None
    track_title: dict[int, str] = {}
    track_artist: dict[int, str] = {}

    for line in text.splitlines():
        line = line.rstrip()

        if line.strip().startswith("Track") and not line.strip().startswith("Tracks"):
            parts = line.strip().split()
            if len(parts) >= 2 and parts[1].isdigit():
                current_track = int(parts[1])
            continue

        stripped = line.lstrip()

        if stripped.startswith("CD-TEXT for Disc:") or stripped.startswith("CD-TEXT:"):
            current_track = None
            continue

        if "TITLE:" in stripped:
            value = trim(stripped.split("TITLE:", 1)[1])
            if current_track is None:
                album = value
            else:
                track_title[current_track] = value
        elif "PERFORMER:" in stripped:
            value = trim(stripped.split("PERFORMER:", 1)[1])
            if current_track is None:
                album_artist = value
            else:
                track_artist[current_track] = value

    if not album and not album_artist and not track_title:
        return None

    for num, title in sorted(track_title.items()):
        tracks.append(Track(number=num, title=title, artist=track_artist.get(num, "")))

    return Metadata(
        source="CD-Text",
        album_artist=album_artist,
        album=album,
        year="",
        tracks=tracks,
        match_quality="cdtext",
    )


def _parse_toc_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
        value = value.replace(r"\\", "\\").replace(r"\"", '"')
    return trim(value)


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
