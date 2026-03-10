"""CD ripping: disc image (cdrdao) and audio WAV extraction (cdparanoia)."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .cleanup import Cleanup
from .ui.console import console, log, warn, error


# cdrdao drivers to try in order
_CDRDAO_DRIVERS = ["generic-mmc-raw", "generic-mmc", "audio"]


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
) -> bool:
    """
    Rip a full disc image using cdrdao. Tries multiple drivers if needed.
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
            "--read-raw",
            "--datafile", str(bin_path),
            str(toc_path),
        ]
        if debug:
            console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

        toc_path.unlink(missing_ok=True)
        bin_path.unlink(missing_ok=True)

        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            error("cdrdao not found. Please install cdrdao.")
            return False

        if result.returncode == 0 and toc_path.exists():
            log(f"cdrdao: disc image written ({bin_path.name})")
            return True

        if debug:
            console.print(f"[dim]{result.stdout}[/dim]")

        # Check if this driver explicitly failed vs. a device error
        if "No driver found" in result.stdout or "Cannot open" in result.stdout:
            continue  # try next driver
        # Other failures (device error, etc.) — don't retry
        error(f"cdrdao failed (driver={drv}, exit={result.returncode})")
        error(f"Tried drivers: {', '.join(tried)}")
        return False

    error(f"cdrdao: no working driver found (tried: {', '.join(tried)})")
    return False


# ---------------------------------------------------------------------------
# Audio extraction (cdparanoia)
# ---------------------------------------------------------------------------

_PARANOIA_TRACK_RE = re.compile(r"outputting to\s+(\S+)", re.IGNORECASE)
_PARANOIA_PROGRESS_RE = re.compile(r"\((\d+)\)")


def rip_audio(
    device: str,
    work_dir: Path,
    track_count: int,
    cleanup: Cleanup,
    debug: bool = False,
) -> list[Path] | None:
    """
    Rip audio tracks to WAV files using cdparanoia batch mode.
    Returns sorted list of WAV paths, or None on failure.
    """
    cmd = ["cdparanoia", "-d", device, "-B", "--"]
    if debug:
        console.print(f"[dim]$ {' '.join(cmd)} (cwd={work_dir})[/dim]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("Ripping audio...", total=track_count)
        current_track = 0

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

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if debug:
                console.print(f"[dim]{line}[/dim]")
            # cdparanoia prints "outputting to track01.cdda.wav"
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
