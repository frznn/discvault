"""CD ripping: disc image (cdrdao) and audio WAV extraction (cdparanoia)."""
from __future__ import annotations

import re
import subprocess
import threading
from pathlib import Path
from typing import Callable

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .cleanup import Cleanup
from .ui.console import console, log, error


# cdrdao drivers to try in order
_CDRDAO_DRIVERS = ["generic-mmc-raw", "generic-mmc", "audio"]

_CDRDAO_TRACK_RE = re.compile(r"Reading track\s+(\d+)", re.IGNORECASE)
_CDRDAO_TRACK_LABEL_RE = re.compile(r"^Track\s+(\d+)\.\.\.$", re.IGNORECASE)
_CDRDAO_PERCENT_RE = re.compile(r"\b(\d+)%")
_CDRDAO_READ_MB_RE = re.compile(r"\bRead\s+(\d+)\s+of\s+(\d+)\s+MB\b", re.IGNORECASE)
_RAW_SECTOR_SIZE = 2352


# ---------------------------------------------------------------------------
# Disc image (cdrdao)
# ---------------------------------------------------------------------------

def rip_image(
    device: str,
    toc_path: Path,
    bin_path: Path,
    cleanup: Cleanup,
    driver: str = "",
    debug: bool = False,
    process_callback: Callable | None = None,
    progress_callback: Callable | None = None,
    track_count: int = 0,
    track_offsets: list[int] | None = None,
    leadout: int = 0,
) -> bool:
    """
    Rip a full disc image using cdrdao. Tries multiple drivers if needed.
    process_callback(proc) is called with the Popen object when the process starts.
    progress_callback(current, total, label) is called as progress is parsed.
    Returns True on success.
    """
    cleanup.track_file(toc_path)
    cleanup.track_file(bin_path)

    drivers_to_try: list[str] = []
    if driver:
        drivers_to_try.append(driver)
    for d in _CDRDAO_DRIVERS:
        if d not in drivers_to_try:
            drivers_to_try.append(d)

    tried: list[str] = []
    for drv in drivers_to_try:
        tried.append(drv)
        log(f"cdrdao: trying driver '{drv}'...")
        cmd = [
            "cdrdao", "read-cd",
            "--device", device,
            "--driver", drv,
            "-v", "1",
            "--read-raw",
            "--datafile", str(bin_path),
            str(toc_path),
        ]
        if debug:
            console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

        toc_path.unlink(missing_ok=True)
        bin_path.unlink(missing_ok=True)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            error("cdrdao not found. Please install cdrdao.")
            return False

        if process_callback:
            process_callback(proc)

        # Stream output for progress parsing
        output_chunks: list[str] = []
        current_track = 0
        last_track_reported = 0
        last_progress_units = -1
        last_progress_label = ""
        progress_lock = threading.Lock()
        stop_monitor = threading.Event()
        start_frame = track_offsets[0] if track_offsets else 0
        total_frames = max(leadout - start_frame, 1) if track_offsets and leadout > start_frame else 0
        assert proc.stdout is not None

        def _track_from_frames(frames_done: int) -> int:
            if track_count <= 0 or not track_offsets:
                return 0

            absolute_frame = start_frame + max(frames_done, 0)
            current = 1
            for idx, start in enumerate(track_offsets, start=1):
                if absolute_frame >= start:
                    current = idx
                else:
                    break
            return min(current, track_count)

        def _emit_disc_progress(
            frames_done: int,
            label: str | None = None,
            *,
            final: bool = False,
        ) -> None:
            nonlocal last_progress_units, last_progress_label, last_track_reported
            if progress_callback is None or total_frames <= 0:
                return

            progress_limit = total_frames if final else max(total_frames - 1, 0)
            frames_done = max(0, min(frames_done, progress_limit))
            track_no = _track_from_frames(frames_done) or max(min(track_count, 1), last_track_reported)
            total_tracks = max(track_count, track_no, 1)
            if label is None:
                label = f"Disc image: track {track_no}/{total_tracks}"

            with progress_lock:
                if frames_done < last_progress_units:
                    return
                if frames_done == last_progress_units and label == last_progress_label:
                    return
                last_progress_units = frames_done
                last_progress_label = label
                last_track_reported = max(last_track_reported, track_no)

            progress_callback(frames_done, total_frames, label)

        def _emit_track_progress(
            track_no: int,
            label: str | None = None,
            *,
            final: bool = False,
        ) -> None:
            nonlocal last_track_reported
            if progress_callback is None or track_no <= 0:
                return
            total_tracks = max(track_count, track_no, 1)
            if label is None:
                label = f"Disc image: track {track_no}/{total_tracks}"

            if total_frames > 0 and track_offsets:
                if final:
                    _emit_disc_progress(total_frames, label=label, final=True)
                else:
                    track_index = min(max(track_no - 1, 0), len(track_offsets) - 1)
                    track_start = max(track_offsets[track_index] - start_frame, 0)
                    _emit_disc_progress(track_start, label=label)
                return

            with progress_lock:
                if track_no < last_track_reported:
                    return
                if track_no == last_track_reported:
                    return
                last_track_reported = track_no
            progress_callback(track_no, total_tracks, label)

        def _monitor_image_file() -> None:
            while not stop_monitor.wait(0.5):
                if not bin_path.exists():
                    continue
                frames_done = min(bin_path.stat().st_size // _RAW_SECTOR_SIZE, total_frames)
                _emit_disc_progress(frames_done)

        monitor_thread: threading.Thread | None = None
        if progress_callback is not None and total_frames > 0:
            monitor_thread = threading.Thread(target=_monitor_image_file, daemon=True)
            monitor_thread.start()

        def _handle_output(part: str) -> None:
            nonlocal current_track
            part = part.strip()
            if not part:
                return
            if debug:
                console.print(f"[dim]{part}[/dim]")
            if progress_callback is None:
                return

            m = _CDRDAO_TRACK_RE.search(part)
            if m:
                current_track = int(m.group(1))
                _emit_track_progress(current_track)
                return

            m = _CDRDAO_TRACK_LABEL_RE.search(part)
            if m:
                current_track = int(m.group(1))
                _emit_track_progress(current_track)
                return

            if track_count <= 0:
                m = _CDRDAO_READ_MB_RE.search(part)
                if m:
                    current_mb = int(m.group(1))
                    total_mb = max(int(m.group(2)), 1)
                    progress_callback(
                        min(current_mb, total_mb),
                        total_mb,
                        f"Disc image: {current_mb}/{total_mb} MB",
                    )
                    return

                if current_track > 0:
                    m2 = _CDRDAO_PERCENT_RE.search(part)
                    if m2:
                        pct = int(m2.group(1))
                        total_units = 100
                        progress_callback(
                            min(pct, total_units),
                            total_units,
                            f"Disc image: track {current_track} ({pct}%)",
                        )

        pending = ""
        for ch in iter(lambda: proc.stdout.read(1), ""):
            output_chunks.append(ch)
            if ch in "\r\n":
                _handle_output(pending)
                pending = ""
            else:
                pending += ch
        if pending:
            _handle_output(pending)
        proc.wait()
        stop_monitor.set()
        if monitor_thread is not None:
            monitor_thread.join(timeout=1.0)

        if progress_callback is not None and track_count > 0 and proc.returncode == 0:
            _emit_track_progress(
                track_count,
                f"Disc image: track {track_count}/{track_count}",
                final=True,
            )
        stdout = "".join(output_chunks)

        if proc.returncode == 0 and toc_path.exists():
            log(f"cdrdao: disc image written ({bin_path.name})")
            return True

        if "No driver found" in (stdout or "") or "Cannot open" in (stdout or ""):
            continue
        error(f"cdrdao failed (driver={drv}, exit={proc.returncode})")
        error(f"Tried drivers: {', '.join(tried)}")
        return False

    error(f"cdrdao: no working driver found (tried: {', '.join(tried)})")
    return False


# ---------------------------------------------------------------------------
# Audio extraction (cdparanoia)
# ---------------------------------------------------------------------------

_PARANOIA_TRACK_RE = re.compile(r"outputting to\s+(\S+)", re.IGNORECASE)


def rip_audio(
    device: str,
    work_dir: Path,
    track_count: int,
    cleanup: Cleanup,
    debug: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
    process_callback: Callable | None = None,
) -> list[Path] | None:
    """
    Rip audio tracks to WAV files using cdparanoia batch mode.
    progress_callback(current, total, filename) is called as tracks are ripped.
    process_callback(proc) is called with the Popen object when started.
    Returns sorted list of WAV paths, or None on failure.
    """
    cmd = ["cdparanoia", "-d", device, "-B", "--"]
    if debug:
        console.print(f"[dim]$ {' '.join(cmd)} (cwd={work_dir})[/dim]")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(work_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        error("cdparanoia not found. Please install cdparanoia.")
        return None

    if process_callback:
        process_callback(proc)

    current_track = 0

    if progress_callback is not None:
        # TUI/callback mode: no rich Progress
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if debug:
                console.print(f"[dim]{line}[/dim]")
            m = _PARANOIA_TRACK_RE.search(line)
            if m:
                current_track += 1
                fname = Path(m.group(1)).name
                progress_callback(current_track, track_count, fname)
        proc.wait()
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
            task = progress.add_task("Ripping audio...", total=track_count)

            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip()
                if debug:
                    console.print(f"[dim]{line}[/dim]")
                m = _PARANOIA_TRACK_RE.search(line)
                if m:
                    current_track += 1
                    fname = Path(m.group(1)).name
                    progress.update(task, advance=1, description=f"Ripping {fname}...")
            proc.wait()

    if proc.returncode != 0:
        error(f"cdparanoia exited with code {proc.returncode}")
        return None

    wav_files = sorted(work_dir.glob("track*.cdda.wav"), key=lambda p: p.name)
    if not wav_files:
        error("cdparanoia produced no WAV files")
        return None

    for w in wav_files:
        cleanup.track_file(w)

    log(f"Ripped {len(wav_files)} track(s) to {work_dir}")
    return wav_files
