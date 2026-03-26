"""CD ripping: disc image (cdrdao) and audio WAV extraction (cdparanoia)."""
from __future__ import annotations

import re
import shlex
import subprocess
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .cleanup import Cleanup
from .ui.console import console, log, error

if TYPE_CHECKING:
    from .metadata.types import DiscInfo


# cdrdao drivers to try in order
_CDRDAO_DRIVERS = ["generic-mmc-raw", "generic-mmc", "audio"]

_CDRDAO_TRACK_RE = re.compile(r"Reading track\s+(\d+)", re.IGNORECASE)
_CDRDAO_TRACK_LABEL_RE = re.compile(r"^Track\s+(\d+)\.\.\.$", re.IGNORECASE)
_CDRDAO_PERCENT_RE = re.compile(r"\b(\d+)%")
_CDRDAO_READ_MB_RE = re.compile(r"\bRead\s+(\d+)\s+of\s+(\d+)\s+MB\b", re.IGNORECASE)
_TOC_TRACK_MODE_RE = re.compile(r"^\s*TRACK\s+([A-Z0-9_]+)", re.IGNORECASE)
_RAW_SECTOR_SIZE = 2352


# ---------------------------------------------------------------------------
# Disc image (cdrdao)
# ---------------------------------------------------------------------------

def _collect_cdrdao_output(
    proc: "subprocess.Popen[str]",
    toc_path: Path,
    bin_path: Path,
    drv: str,
    tried: list[str],
    track_count: int,
    track_offsets: list[int] | None,
    leadout: int,
    progress_callback: Callable | None,
    debug: bool,
) -> tuple[bool | None, str]:
    """
    Stream output from an already-started cdrdao process, parse progress, check result.
    Returns (True, "") on success, (False, reason) on hard failure,
    (None, "") when cdrdao signals a driver incompatibility (caller may retry).
    """
    if proc.stdout is None:
        proc.kill()
        return False, "cdrdao: failed to open stdout pipe"

    output_chunks: list[str] = []
    current_track = 0
    last_track_reported = 0
    last_progress_units = -1
    last_progress_label = ""
    progress_lock = threading.Lock()
    stop_monitor = threading.Event()
    start_frame = track_offsets[0] if track_offsets else 0
    total_frames = max(leadout - start_frame, 1) if track_offsets and leadout > start_frame else 0

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

    def _emit_disc_progress(frames_done: int, label: str | None = None, *, final: bool = False) -> None:
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

    def _emit_track_progress(track_no: int, label: str | None = None, *, final: bool = False) -> None:
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
            if track_no <= last_track_reported:
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
                progress_callback(min(current_mb, total_mb), total_mb, f"Disc image: {current_mb}/{total_mb} MB")
                return
            if current_track > 0:
                m2 = _CDRDAO_PERCENT_RE.search(part)
                if m2:
                    pct = int(m2.group(1))
                    progress_callback(min(pct, 100), 100, f"Disc image: track {current_track} ({pct}%)")

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
        _emit_track_progress(track_count, f"Disc image: track {track_count}/{track_count}", final=True)

    stdout = "".join(output_chunks).strip()
    if proc.returncode == 0 and toc_path.exists() and bin_path.exists() and bin_path.stat().st_size > 0:
        log(f"cdrdao: disc image written ({bin_path.name})")
        return True, ""
    if "No driver found" in stdout or "Cannot open" in stdout:
        return None, ""  # caller may retry with another driver
    reason = f"cdrdao failed (driver={drv}, exit={proc.returncode})"
    if len(tried) > 1:
        reason = f"{reason}\nTried drivers: {', '.join(tried)}"
    if stdout:
        reason = f"{reason}\n\n{stdout}"
    error(reason)
    return False, reason


def _launch_cdrdao(cmd: list[str]) -> "tuple[subprocess.Popen[str] | None, str]":
    """Launch cdrdao subprocess. Returns (proc, "") or (None, error_reason)."""
    try:
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        ), ""
    except FileNotFoundError:
        error("cdrdao not found. Please install cdrdao.")
        return None, "cdrdao not found — please install cdrdao"


def rip_image(
    device: str,
    toc_path: Path,
    bin_path: Path,
    cleanup: Cleanup,
    command_template: str = "",
    driver: str = "",
    read_raw: bool = True,
    debug: bool = False,
    process_callback: Callable | None = None,
    progress_callback: Callable | None = None,
    track_count: int = 0,
    track_offsets: list[int] | None = None,
    leadout: int = 0,
) -> tuple[bool, str]:
    """
    Rip a full disc image using cdrdao.
    If command_template is set it is used directly (placeholders: {device}, {datafile}, {toc}).
    Otherwise the driver retry loop is used with the driver/read_raw flags.
    Returns (True, "") on success, (False, reason) on failure.
    """
    cleanup.track_file(toc_path)
    cleanup.track_file(bin_path)

    if command_template:
        # Use shlex.split first, then substitute placeholders to preserve paths with spaces
        try:
            cmd_parts = shlex.split(command_template)
        except ValueError as exc:
            return False, f"Invalid cdrdao command template: {exc}"
        subs = {"{device}": device, "{datafile}": str(bin_path), "{toc}": str(toc_path)}
        cmd = []
        for part in cmd_parts:
            for placeholder, value in subs.items():
                part = part.replace(placeholder, value)
            cmd.append(part)
        drv_match = re.search(r"--driver\s+(\S+)", command_template)
        drv_label = drv_match.group(1) if drv_match else "custom"
        log(f"cdrdao: running command (driver={drv_label})...")
        if debug:
            console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
        toc_path.unlink(missing_ok=True)
        bin_path.unlink(missing_ok=True)
        proc, err = _launch_cdrdao(cmd)
        if proc is None:
            return False, err
        if process_callback:
            process_callback(proc)
        ok, detail = _collect_cdrdao_output(
            proc, toc_path, bin_path, drv_label, [drv_label],
            track_count, track_offsets, leadout, progress_callback, debug,
        )
        if ok is None:
            return False, f"cdrdao command failed (device or disc not recognised, driver={drv_label})"
        return ok, detail

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
        cmd = ["cdrdao", "read-cd", "--device", device, "--driver", drv, "-v", "1"]
        if read_raw:
            cmd.append("--read-raw")
        cmd += ["--datafile", str(bin_path), str(toc_path)]
        if debug:
            console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
        toc_path.unlink(missing_ok=True)
        bin_path.unlink(missing_ok=True)
        proc, err = _launch_cdrdao(cmd)
        if proc is None:
            return False, err
        if process_callback:
            process_callback(proc)
        ok, detail = _collect_cdrdao_output(
            proc, toc_path, bin_path, drv, tried,
            track_count, track_offsets, leadout, progress_callback, debug,
        )
        if ok is True:
            return True, ""
        if ok is False:
            return False, detail
        # ok is None → try next driver

    reason = f"cdrdao: no working driver found (tried: {', '.join(tried)})"
    error(reason)
    return False, reason


def write_cue_file(
    cue_path: Path,
    bin_path: Path,
    disc_info: "DiscInfo",
    *,
    toc_path: Path | None = None,
    cleanup: Cleanup | None = None,
) -> bool:
    """Write a CUE sidecar for a raw BIN image."""
    if not disc_info.track_offsets or disc_info.track_count <= 0:
        return False

    start_frame = disc_info.track_offsets[0]
    mode_hints = _parse_toc_track_modes(toc_path)
    lines = [f'FILE "{bin_path.name}" BINARY']

    for track_no in range(1, disc_info.track_count + 1):
        mode = _cue_track_mode(track_no, disc_info, mode_hints)
        offset = max(disc_info.track_offsets[track_no - 1] - start_frame, 0)
        lines.append(f"  TRACK {track_no:02d} {mode}")
        lines.append(f"    INDEX 01 {_frames_to_msf(offset)}")

    if cleanup is not None:
        cleanup.track_file(cue_path, created=not cue_path.exists())
    cue_path.write_text("\n".join(lines) + "\n")
    return True


def rip_image_readom(
    device: str,
    bin_path: Path,
    disc_info: "DiscInfo",
    cleanup: Cleanup,
    debug: bool = False,
    process_callback: Callable | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[bool, str]:
    """
    Rip a disc image using readom. Produces a .bin file only (no .toc).
    Returns (True, "") on success, (False, reason) on failure.
    """
    cleanup.track_file(bin_path)

    cmd = ["readom", f"dev={device}", f"f={bin_path}"]
    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    log("readom: starting disc image rip...")
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
        error("readom not found. Please install wodim/cdrtools.")
        return False, "readom not found — please install wodim or cdrtools"

    if process_callback:
        process_callback(proc)

    track_offsets = disc_info.track_offsets or []
    leadout = disc_info.leadout or 0
    start_frame = track_offsets[0] if track_offsets else 0
    total_frames = max(leadout - start_frame, 1) if leadout > start_frame else 0
    total_bytes = total_frames * _RAW_SECTOR_SIZE

    stop_monitor = threading.Event()

    def _monitor() -> None:
        while not stop_monitor.wait(0.5):
            if not bin_path.exists() or total_bytes <= 0 or progress_callback is None:
                continue
            done = min(bin_path.stat().st_size, total_bytes)
            track_count = disc_info.track_count or 1
            track_no = max(1, min(int(done / total_bytes * track_count) + 1, track_count))
            progress_callback(done, total_bytes, f"Disc image: {done // (1024*1024)}/{total_bytes // (1024*1024)} MB")

    monitor_thread: threading.Thread | None = None
    if progress_callback is not None and total_bytes > 0:
        monitor_thread = threading.Thread(target=_monitor, daemon=True)
        monitor_thread.start()

    output_lines: list[str] = []
    if proc.stdout:
        for line in proc.stdout:
            line = line.rstrip()
            if debug:
                console.print(f"[dim]{line}[/dim]")
            output_lines.append(line)
    proc.wait()
    stop_monitor.set()
    if monitor_thread is not None:
        monitor_thread.join(timeout=1.0)

    if process_callback:
        process_callback(None)

    if proc.returncode == 0 and bin_path.exists() and bin_path.stat().st_size > 0:
        log(f"readom: disc image written ({bin_path.name})")
        return True, ""

    stdout = "\n".join(output_lines).strip()
    reason = f"readom failed (exit={proc.returncode})"
    if "Permission denied" in stdout:
        reason = f"readom failed: permission denied on {device}"
    elif "No such file" in stdout:
        reason = f"readom failed: device {device} not found"
    if stdout:
        reason = f"{reason}\n\n{stdout}"
    error(reason)
    return False, reason


def export_iso_from_bin(
    iso_path: Path,
    bin_path: Path,
    disc_info: "DiscInfo",
    *,
    toc_path: Path | None = None,
    cleanup: Cleanup | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[Path | None, str]:
    """Export a mountable ISO from a single Mode 1 data track in the raw BIN."""
    data_tracks = disc_info.data_track_numbers
    if not data_tracks:
        return None, "ISO export skipped: disc has no data track."
    if len(data_tracks) != 1:
        return None, "ISO export skipped: supports discs with exactly one data track."
    if not disc_info.track_offsets or disc_info.track_count <= 0:
        return None, "ISO export skipped: disc layout is incomplete."

    track_no = data_tracks[0]
    mode_hints = _parse_toc_track_modes(toc_path)
    raw_mode = mode_hints.get(track_no, "").upper()
    if raw_mode and not raw_mode.startswith("MODE1"):
        return None, f"ISO export skipped: unsupported data track mode {raw_mode}."

    first_frame = disc_info.track_offsets[0]
    track_start = disc_info.track_offsets[track_no - 1]
    track_end = (
        disc_info.track_offsets[track_no]
        if track_no < len(disc_info.track_offsets)
        else disc_info.leadout
    )
    frame_count = max(track_end - track_start, 0)
    if frame_count <= 0:
        return None, "ISO export skipped: data track is empty."

    start_offset = max(track_start - first_frame, 0) * _RAW_SECTOR_SIZE
    if cleanup is not None:
        cleanup.track_file(iso_path, created=not iso_path.exists())

    label = f"Exporting ISO from data track {track_no}"
    try:
        with bin_path.open("rb") as src, iso_path.open("wb") as dst:
            src.seek(start_offset)
            for current_frame in range(1, frame_count + 1):
                sector = src.read(_RAW_SECTOR_SIZE)
                if len(sector) != _RAW_SECTOR_SIZE:
                    iso_path.unlink(missing_ok=True)
                    return None, "ISO export failed: unexpected end of BIN image."
                dst.write(sector[16:16 + 2048])
                if progress_callback and (
                    current_frame == frame_count
                    or current_frame == 1
                    or current_frame % 128 == 0
                ):
                    progress_callback(current_frame, frame_count, label)
    except OSError as exc:
        iso_path.unlink(missing_ok=True)
        return None, f"ISO export failed: {exc}"

    return iso_path, ""


def _parse_toc_track_modes(toc_path: Path | None) -> dict[int, str]:
    if toc_path is None or not toc_path.exists():
        return {}

    modes: dict[int, str] = {}
    current_track = 0
    try:
        toc_text = toc_path.read_text(errors="replace")
    except OSError:
        return {}

    for line in toc_text.splitlines():
        match = _TOC_TRACK_MODE_RE.match(line)
        if not match:
            continue
        current_track += 1
        modes[current_track] = match.group(1).upper()
    return modes


def _cue_track_mode(track_no: int, disc_info: "DiscInfo", mode_hints: dict[int, str]) -> str:
    if disc_info.is_audio_track(track_no):
        return "AUDIO"

    raw_mode = mode_hints.get(track_no, "").upper()
    if raw_mode.startswith("MODE2"):
        return "MODE2/2352"
    return "MODE1/2352"


def _frames_to_msf(frames: int) -> str:
    minutes, remainder = divmod(max(frames, 0), 75 * 60)
    seconds, frame = divmod(remainder, 75)
    return f"{minutes:02d}:{seconds:02d}:{frame:02d}"


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
    selected_tracks: list[int] | None = None,
    sample_offset: int = 0,
) -> tuple[list[Path] | None, str]:
    """
    Rip audio tracks to WAV files using cdparanoia batch mode.
    progress_callback(current, total, filename) is called as tracks are ripped.
    process_callback(proc) is called with the Popen object when started.
    Returns (list of WAV paths, "") on success, (None, reason) on failure.
    """
    selected_tracks = _normalize_selected_tracks(selected_tracks, track_count)
    if not selected_tracks:
        error("No audio tracks selected for ripping")
        return None, "No audio tracks selected for ripping"

    full_disc_tracks = list(range(1, track_count + 1))
    common_args = ["cdparanoia", "-d", device]
    if sample_offset:
        common_args.extend(["-O", str(sample_offset)])

    batch_mode = selected_tracks == full_disc_tracks

    if batch_mode:
        cmd = [*common_args, "-B", "--"]
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
            return None, "cdparanoia not found — please install cdparanoia"

        if process_callback:
            process_callback(proc)

        current_track = 0
        total_selected = len(selected_tracks)

        if progress_callback is not None:
            # TUI/callback mode: no rich Progress
            if proc.stdout is None:
                error("cdparanoia: failed to open stdout pipe.")
                proc.kill()
                return None, "cdparanoia: failed to open stdout pipe"
            for line in proc.stdout:
                line = line.rstrip()
                if debug:
                    console.print(f"[dim]{line}[/dim]")
                m = _PARANOIA_TRACK_RE.search(line)
                if m:
                    current_track += 1
                    fname = Path(m.group(1)).name
                    progress_callback(current_track, total_selected, fname)
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
                task = progress.add_task("Ripping audio...", total=total_selected)

                if proc.stdout is None:
                    error("cdparanoia: failed to open stdout pipe.")
                    proc.kill()
                    return None, "cdparanoia: failed to open stdout pipe"
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
            reason = f"cdparanoia exited with code {proc.returncode}"
            error(reason)
            return None, reason

        wav_files = sorted(
            (work_dir / _wav_name_for_track(track_num, track_count) for track_num in selected_tracks),
            key=lambda p: p.name,
        )
    else:
        total_selected = len(selected_tracks)
        wav_files = []

        if progress_callback is None:
            progress_cm = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
                transient=True,
            )
        else:
            progress_cm = None

        if progress_cm is not None:
            progress_cm.__enter__()
            task = progress_cm.add_task("Ripping audio...", total=total_selected)
        else:
            task = None

        try:
            for index, track_num in enumerate(selected_tracks, start=1):
                out_name = _wav_name_for_track(track_num, track_count)
                cmd = [*common_args, str(track_num), out_name]
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
                    return None, "cdparanoia not found — please install cdparanoia"

                if process_callback:
                    process_callback(proc)

                started = False
                if proc.stdout is None:
                    error("cdparanoia: failed to open stdout pipe.")
                    proc.kill()
                    return None, "cdparanoia: failed to open stdout pipe"
                for line in proc.stdout:
                    line = line.rstrip()
                    if debug:
                        console.print(f"[dim]{line}[/dim]")
                    m = _PARANOIA_TRACK_RE.search(line)
                    if m and not started:
                        started = True
                        fname = Path(m.group(1)).name
                        if progress_callback is not None:
                            progress_callback(index, total_selected, fname)
                        elif progress_cm is not None and task is not None:
                            progress_cm.update(
                                task,
                                completed=index - 1,
                                description=f"Ripping {fname}...",
                            )
                proc.wait()

                if proc.returncode != 0:
                    reason = f"cdparanoia exited with code {proc.returncode} on track {track_num}"
                    error(reason)
                    return None, reason

                if not started:
                    if progress_callback is not None:
                        progress_callback(index, total_selected, out_name)
                    elif progress_cm is not None and task is not None:
                        progress_cm.update(
                            task,
                            completed=index - 1,
                            description=f"Ripping {out_name}...",
                        )
                wav_files.append(work_dir / out_name)
                if progress_callback is None and progress_cm is not None and task is not None:
                    progress_cm.update(task, completed=index, description=f"Ripped {out_name}")
        finally:
            if progress_cm is not None:
                progress_cm.__exit__(None, None, None)

    if not wav_files:
        error("cdparanoia produced no WAV files")
        return None, "cdparanoia produced no WAV files"

    for w in wav_files:
        cleanup.track_file(w, created=True)

    log(f"Ripped {len(wav_files)} track(s) to {work_dir}")
    return wav_files, ""


def _normalize_selected_tracks(selected_tracks: list[int] | None, track_count: int) -> list[int]:
    if selected_tracks is None:
        return list(range(1, track_count + 1))
    normalized = sorted({track for track in selected_tracks if 1 <= track <= track_count})
    return normalized


def _wav_name_for_track(track_num: int, track_total: int) -> str:
    width = max(2, len(str(max(track_num, track_total))))
    return f"track{track_num:0{width}d}.cdda.wav"
