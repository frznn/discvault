"""CD device detection."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix platforms
    fcntl = None

_CANDIDATES = ["/dev/cdrom", "/dev/sr0", "/dev/sr1", "/dev/sr2", "/dev/cdrw"]

_CDROM_MEDIA_CHANGED = 0x5325
_CDROM_DRIVE_STATUS = 0x5326
_CDSL_CURRENT = 2**31 - 1

_CDS_NO_INFO = 0
_CDS_NO_DISC = 1
_CDS_TRAY_OPEN = 2
_CDS_DRIVE_NOT_READY = 3
_CDS_DISC_OK = 4

_OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


def detect() -> str | None:
    """Return the first available CD block device, or None."""
    for candidate in _CANDIDATES:
        p = Path(candidate)
        if p.is_block_device() or p.is_symlink():
            return candidate
    return None


def list_available() -> list[str]:
    """Return every currently-present CD block device from the standard candidates."""
    found: list[str] = []
    for candidate in _CANDIDATES:
        p = Path(candidate)
        if p.is_block_device() or p.is_symlink():
            found.append(candidate)
    return found


def drive_status(device: str) -> str:
    """Return tray/media status without forcing a full disc read when supported."""
    if fcntl is None:
        return "unknown"
    fd: int | None = None
    try:
        fd = os.open(device, _OPEN_FLAGS)
        code = fcntl.ioctl(fd, _CDROM_DRIVE_STATUS, _CDSL_CURRENT)
    except OSError:
        return "unknown"
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    return {
        _CDS_NO_DISC: "no_disc",
        _CDS_TRAY_OPEN: "tray_open",
        _CDS_DRIVE_NOT_READY: "not_ready",
        _CDS_DISC_OK: "disc_ok",
        _CDS_NO_INFO: "unknown",
    }.get(code, "unknown")


def media_changed(device: str) -> bool | None:
    """Return True when the kernel reports media changed since the last check."""
    if fcntl is None:
        return None
    fd: int | None = None
    try:
        fd = os.open(device, _OPEN_FLAGS)
        changed = fcntl.ioctl(fd, _CDROM_MEDIA_CHANGED, _CDSL_CURRENT)
    except OSError:
        return None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
    return bool(changed)


def is_readable(device: str) -> bool:
    """Check that a disc is present and readable."""
    status = drive_status(device)
    if status == "disc_ok":
        return True
    if status in {"no_disc", "tray_open", "not_ready"}:
        return False
    try:
        result = subprocess.run(
            ["cdparanoia", "-d", device, "-Q"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
