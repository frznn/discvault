"""CD device detection."""
from __future__ import annotations
import subprocess
from pathlib import Path

_CANDIDATES = ["/dev/cdrom", "/dev/sr0", "/dev/sr1", "/dev/sr2", "/dev/cdrw"]


def detect() -> str | None:
    """Return the first available CD block device, or None."""
    for candidate in _CANDIDATES:
        p = Path(candidate)
        if p.is_block_device() or p.is_symlink():
            return candidate
    return None


def is_readable(device: str) -> bool:
    """Check that an audio CD is present and readable via cdparanoia."""
    try:
        result = subprocess.run(
            ["cdparanoia", "-d", device, "-Q"],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
