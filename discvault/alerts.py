"""Best-effort completion chime and desktop notifications."""
from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


_CHIME_PATH = Path(tempfile.gettempdir()) / "discvault-complete.wav"


def play_completion_sound(mode: str) -> bool:
    """Play the configured completion sound mode."""
    selected = (mode or "bell").strip().lower()
    if selected == "off":
        return True
    if selected == "bell":
        return play_completion_bell()
    if selected == "chime":
        return play_completion_chime()
    if selected == "both":
        bell_ok = play_completion_bell()
        chime_ok = play_completion_chime()
        return bell_ok or chime_ok
    return play_completion_bell()


def play_completion_bell() -> bool:
    """Emit the terminal bell character."""
    try:
        sys.stdout.write("\a")
        sys.stdout.flush()
    except OSError:
        return False
    return True


def play_completion_chime() -> bool:
    """Play a short completion chime if a supported backend is available."""
    chime_path = ensure_chime_file()
    for command in _audio_commands(chime_path):
        if _run_quiet(command, timeout=8):
            return True
    return False


def send_desktop_notification(title: str, message: str) -> bool:
    """Send a desktop notification if `notify-send` is available."""
    if not shutil.which("notify-send"):
        return False
    return _run_quiet(
        [
            "notify-send",
            "--app-name",
            "DiscVault",
            "--expire-time",
            "10000",
            title,
            message,
        ],
        timeout=5,
    )


def ensure_chime_file() -> Path:
    """Create a small WAV chime once and reuse it."""
    if _CHIME_PATH.exists():
        return _CHIME_PATH

    sample_rate = 22050
    envelope_len = int(sample_rate * 0.32)
    notes = [
        (880.0, envelope_len),
        (1174.66, envelope_len),
    ]
    frames = bytearray()
    for frequency, frame_count in notes:
        for index in range(frame_count):
            t = index / sample_rate
            fade = 1.0 - (index / frame_count)
            value = int(
                16000 * fade * math.sin(2.0 * math.pi * frequency * t)
            )
            frames.extend(int(value).to_bytes(2, byteorder="little", signed=True))
        pause_frames = int(sample_rate * 0.03)
        frames.extend(b"\x00\x00" * pause_frames)

    with wave.open(str(_CHIME_PATH), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(bytes(frames))

    return _CHIME_PATH


def _audio_commands(chime_path: Path) -> list[list[str]]:
    commands: list[list[str]] = []
    for player in ("pw-play", "paplay"):
        if shutil.which(player):
            commands.append([player, str(chime_path)])
    if shutil.which("aplay"):
        commands.append(["aplay", "-q", str(chime_path)])
    if shutil.which("canberra-gtk-play") and _has_display():
        commands.append(["canberra-gtk-play", "-f", str(chime_path), "-d", "DiscVault"])
    return commands


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _run_quiet(command: list[str], timeout: int) -> bool:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
