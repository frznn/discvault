"""FLAC and MP3 encoding with parallel per-track execution."""
from __future__ import annotations

import os
import shutil
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
    meta: Metadata,
    flac_dir: Path | None = None,
    mp3_dir: Path | None = None,
    ogg_dir: Path | None = None,
    opus_dir: Path | None = None,
    alac_dir: Path | None = None,
    aac_dir: Path | None = None,
    wav_dir: Path | None = None,
    flac_compression: int = 8,
    flac_verify: bool = True,
    mp3_quality: int = 2,
    mp3_bitrate: int = 320,
    ogg_quality: int = 6,
    opus_bitrate: int = 160,
    aac_bitrate: int = 256,
    cleanup: Cleanup | None = None,
    debug: bool = False,
    progress_callback=None,  # Callable[[int, int], None] | None
    track_total_hint: int | None = None,
) -> bool:
    """
    Encode or copy all WAV tracks to the requested output formats. Pass None to skip a format.
    Returns True if all tracks encoded successfully.
    """
    output_dirs = [
        flac_dir,
        mp3_dir,
        ogg_dir,
        opus_dir,
        alac_dir,
        aac_dir,
        wav_dir,
    ]
    if all(path is None for path in output_dirs):
        return True

    for out_dir in output_dirs:
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)

    total = len(wav_files) * sum(int(path is not None) for path in output_dirs)
    failed = False
    completed = 0
    max_track_num = max((_track_num_from_wav(wav) for wav in wav_files), default=0)
    resolved_track_total = max(track_total_hint or 0, max_track_num, len(wav_files))

    def _run_futures(on_complete):
        nonlocal failed, completed
        with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
            futures = {}
            for wav in wav_files:
                track_num = _track_num_from_wav(wav)
                track_total = resolved_track_total
                track_meta = meta.track(track_num)
                track_title = track_meta.title if track_meta else ""
                track_artist = track_meta.artist if track_meta else ""

                if flac_dir is not None:
                    out = flac_dir / track_filename(
                        track_num, track_total, track_title, "flac"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_flac,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, flac_compression, flac_verify, debug,
                    )
                    futures[f] = out.name

                if mp3_dir is not None:
                    out = mp3_dir / track_filename(
                        track_num, track_total, track_title, "mp3"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_mp3,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, mp3_quality, mp3_bitrate, debug,
                    )
                    futures[f] = out.name

                if ogg_dir is not None:
                    out = ogg_dir / track_filename(
                        track_num, track_total, track_title, "ogg"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_ogg,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, ogg_quality, debug,
                    )
                    futures[f] = out.name

                if opus_dir is not None:
                    out = opus_dir / track_filename(
                        track_num, track_total, track_title, "opus"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_opus,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, opus_bitrate, debug,
                    )
                    futures[f] = out.name

                if alac_dir is not None:
                    out = alac_dir / track_filename(
                        track_num, track_total, track_title, "m4a"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_alac,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, debug,
                    )
                    futures[f] = out.name

                if aac_dir is not None:
                    out = aac_dir / track_filename(
                        track_num, track_total, track_title, "m4a"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(
                        _encode_aac,
                        wav, out, meta, track_num, track_total,
                        track_title, track_artist, aac_bitrate, debug,
                    )
                    futures[f] = out.name

                if wav_dir is not None:
                    out = wav_dir / track_filename(
                        track_num, track_total, track_title, "wav"
                    )
                    if cleanup:
                        cleanup.track_file(out)
                    f = pool.submit(_copy_wav, wav, out)
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
                completed += 1
                on_complete(completed, total)

    if progress_callback is not None:
        # TUI/callback mode: no rich Progress
        _run_futures(progress_callback)
    else:
        # CLI mode: rich Progress
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Encoding...", total=total)
            _run_futures(lambda done, tot: progress.advance(task))

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
    verify: bool,
    debug: bool,
) -> bool:
    cmd = [
        "flac",
        f"--compression-level-{compression}",
        "--silent",
        *(["--verify"] if verify else []),
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

    return _run_encoder_command(cmd, out, debug)


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

    return _run_encoder_command(cmd, out, debug)


def _encode_ogg(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    quality: int,
    debug: bool,
) -> bool:
    artist = track_artist or meta.album_artist
    cmd = [
        "oggenc", "--quiet",
        "-q", str(quality),
        "--artist", artist,
        "--album", meta.album,
        "--title", track_title,
        "--tracknum", f"{track_num}/{track_total}",
        "--comment", f"ALBUMARTIST={meta.album_artist}",
    ]
    if meta.year:
        cmd += ["--date", meta.year]
    cmd += ["-o", str(out), str(wav)]

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    return _run_encoder_command(cmd, out, debug)


def _encode_opus(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    bitrate: int,
    debug: bool,
) -> bool:
    artist = track_artist or meta.album_artist
    cmd = [
        "opusenc",
        "--quiet",
        "--bitrate",
        str(bitrate),
        "--title",
        track_title,
        "--artist",
        artist,
        "--album",
        meta.album,
        "--tracknumber",
        str(track_num),
        "--comment",
        f"TRACKTOTAL={track_total}",
        "--comment",
        f"ALBUMARTIST={meta.album_artist}",
    ]
    if meta.year:
        cmd += ["--date", meta.year]
    cmd += [str(wav), str(out)]

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    return _run_encoder_command(cmd, out, debug)


def _encode_alac(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    debug: bool,
) -> bool:
    return _encode_ffmpeg(
        wav,
        out,
        meta,
        track_num,
        track_total,
        track_title,
        track_artist,
        codec="alac",
        bitrate=0,
        debug=debug,
    )


def _encode_aac(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    bitrate: int,
    debug: bool,
) -> bool:
    return _encode_ffmpeg(
        wav,
        out,
        meta,
        track_num,
        track_total,
        track_title,
        track_artist,
        codec="aac",
        bitrate=bitrate,
        debug=debug,
    )


def _encode_ffmpeg(
    wav: Path,
    out: Path,
    meta: Metadata,
    track_num: int,
    track_total: int,
    track_title: str,
    track_artist: str,
    *,
    codec: str,
    bitrate: int,
    debug: bool,
) -> bool:
    artist = track_artist or meta.album_artist
    cmd = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(wav),
        "-vn",
        "-c:a",
        codec,
        "-metadata",
        f"album_artist={meta.album_artist}",
        "-metadata",
        f"artist={artist}",
        "-metadata",
        f"album={meta.album}",
        "-metadata",
        f"title={track_title}",
        "-metadata",
        f"track={track_num}/{track_total}",
    ]
    if bitrate > 0:
        cmd += ["-b:a", f"{bitrate}k"]
    if meta.year:
        cmd += ["-metadata", f"date={meta.year}"]
    cmd.append(str(out))

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    return _run_encoder_command(cmd, out, debug)


def _copy_wav(wav: Path, out: Path) -> bool:
    try:
        shutil.copy2(wav, out)
        return _is_nonempty_file(out)
    except OSError:
        return False


def _run_encoder_command(cmd: list[str], out: Path, debug: bool) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        if debug:
            console.print(f"[dim]{exc}[/dim]")
        return False

    if result.returncode != 0:
        if debug and result.stderr:
            console.print(f"[dim]{result.stderr}[/dim]")
        return False

    if not _is_nonempty_file(out):
        if debug:
            console.print(f"[dim]Encoder reported success but no output was written: {out}[/dim]")
        return False

    return True


def _is_nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False
