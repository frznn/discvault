"""Optional post-rip verification helpers."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .ui.console import console


def detect_accuraterip_tool() -> str | None:
    for tool in ("arver", "trackverify"):
        if shutil.which(tool):
            return tool
    return None


def verify_accuraterip(
    audio_files: list[Path],
    *,
    debug: bool = False,
    timeout: int = 300,
) -> tuple[bool | None, str]:
    """
    Run an optional AccurateRip verification with an external helper.

    Returns ``(True, detail)`` on success, ``(False, detail)`` on a failed
    verification, and ``(None, detail)`` when verification was skipped.
    """
    if not audio_files:
        return None, "AccurateRip skipped: no audio files were produced."

    tool = detect_accuraterip_tool()
    if tool is None:
        return None, "AccurateRip skipped: install `arver` or `trackverify` to enable it."

    if tool == "trackverify":
        cmd = [tool, "-R", *[str(path) for path in audio_files]]
    else:
        cmd = [tool, *[str(path) for path in audio_files]]

    if debug:
        console.print(f"[dim]$ {' '.join(cmd)}[/dim]")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"AccurateRip skipped: {tool} timed out after {timeout}s."
    except OSError as exc:
        return None, f"AccurateRip skipped: {tool} failed to start ({exc})."

    detail = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0:
        if detail:
            return True, f"AccurateRip verified via {tool}. {detail.splitlines()[-1]}"
        return True, f"AccurateRip verified via {tool}."

    if detail:
        return False, f"AccurateRip verification failed via {tool}. {detail.splitlines()[-1]}"
    return False, f"AccurateRip verification failed via {tool}."
