"""FLAC and MP3 encoding with parallel per-track execution."""
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .cleanup import Cleanup
from .metadata.types import Metadata
from .library import track_filename
from .ui.console import console, log, error


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_tracks(
    wav_files: list[Path],
    dest_dir: Path,
    meta: Metadata,
    flac: bool = True,
    mp3: bool = False,
    flac_compression: int = 8,
    mp3_quality: int = 2,
    mp3_bitrate: int = 0,
    cleanup: Cleanup | None = None,
    debug: bool = False,
) -> bool:
    """
    Encode all WAV tracks to FLAC and/or MP3 in parallel.
    Returns True if all tracks encoded successfully.
    """
    if not flac and not mp3:
        return True

    dest_dir.mkdir(parents=True, exist_ok=True)
    total = len(wav_files) * (int(flac) + int(mp3))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Encoding...", total=total)
        failed = False

        with ThreadPoolExecutor() as pool:
            futures = {}
            for wav in wav_files:
                track_num = _track_num_from_wav(wav)
                track_meta = meta.track(track_num)
                track_title = track_meta.title if track_meta else ""
                track_artist = track_meta.artist if track_meta else ""

                if flac:
                    out = dest_dir / track_filename(
                        track_num, len(wav_files), track_title, "flac"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_flac,
                        wav, out, meta, track_num, len(wav_files),
                        track_title, track_artist, flac_compression, debug,
                    )
                    futures[f] = out.name

                if mp3:
                    out = dest_dir / track_filename(
                        track_num, len(wav_files), track_title, "mp3"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_mp3,
                        wav, out, meta, track_num, len(wav_files),
                        track_title, track_artist, mp3_quality, mp3_bitrate, debug,
                    )
                    futures[f] = out.name

            for future in as_completed(futures):
                name = futures[future]
                try:
                    ok = future.result()
                except Exception as exc:
                    error(f"Encoding {name} raised: {exc}")
                    ok = False
                if not ok:
                    failed = True
                    error(f"Encoding failed: {name}")
                progress.advance(task)

    return not failed


# ---------------------------------------------------------------------------
# Internal encoders
# ---------------------------------------------------------------------------

def _track_num_from_wav(wav: Path) -> int:
    """Extract track number from cdparanoia output filename (track01.cdda.wav)."""
    stem = wav.stem  # e.g. "track01.cdda"
    digits = "".join(c for c in stem.split(".")[0] if c.isdigit())
    return int(digits) if digits else 0


def _encode_flac(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    compression: int,
    debug: bool,
) -> bool:
    cmd = [
        "flac",
        f"--compression-level-{compression}",
        "--silent",
        f"--tag=ALBUMARTIST={meta.album_artist}",
        f"--tag=ARTIST={track_artist or meta.album_artist}",
        f"--tag=ALBUM={meta.album}",
        f"--tag=TITLE={track_title}",
        f"--tag=TRACKNUMBER={track_num}",
        f"--tag=TRACKTOTAL={track_total}",
    ]
    if meta.year:
        cmd.append(f"--tag=DATE={meta.year}")
    cmd += ["-o", str(out), str(wav)]

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and debug:
        console.print(f"[dim]{result.stderr}[/dim]")
    return result.returncode == 0


def _encode_mp3(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    quality: int,
    bitrate: int,
    debug: bool,
) -> bool:
    artist = track_artist or meta.album_artist
    cmd = ["lame", "--silent", "--id3v2-only"]

    if bitrate > 0:
        cmd += ["-b", str(bitrate)]
    else:
        cmd += ["-V", str(quality)]

    cmd += [
        "--ta", artist,
        "--tl", meta.album,
        "--tt", track_title,
        "--tn", f"{track_num}/{track_total}",
        "--tv", f"TPE2={meta.album_artist}",
    ]
    if meta.year:
        cmd += ["--ty", meta.year]

    cmd += [str(wav), str(out)]

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 and debug:
        console.print(f"[dim]{result.stderr}[/dim]")
    return result.returncode == 0
