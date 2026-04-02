"""Dependency checks and distro-aware install hints."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import os
import platform
import shutil

from . import __version__
from .config import CONFIG_PATH, Config


@dataclass(frozen=True)
class DependencySpec:
    key: str
    label: str
    commands: tuple[str, ...]
    mode: str = "all"  # all | any
    package_hints: dict[str, tuple[str, ...]] | None = None


@dataclass(frozen=True)
class DependencyStatus:
    spec: DependencySpec
    required: bool
    available: bool
    found_commands: tuple[str, ...]
    install_hint: str | None


@dataclass(frozen=True)
class RuntimeStatus:
    label: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class EnvironmentNote:
    label: str
    detail: str


@dataclass(frozen=True)
class DependencyProfile:
    device: str | None
    image: bool
    flac: bool
    mp3: bool
    ogg: bool
    opus: bool
    alac: bool
    aac: bool
    wav: bool
    accuraterip: bool
    cover_art: bool
    image_ripper: str
    cli_only: bool


@dataclass(frozen=True)
class DependencyReport:
    runtime: tuple[RuntimeStatus, ...]
    required: tuple[DependencyStatus, ...]
    optional: tuple[DependencyStatus, ...]
    notes: tuple[EnvironmentNote, ...]


_PACKAGE_MANAGER_LABELS = {
    "apt": "apt",
    "pacman": "pacman",
    "dnf": "dnf",
}

_DISTRO_TO_MANAGER = {
    "debian": "apt",
    "ubuntu": "apt",
    "linuxmint": "apt",
    "pop": "apt",
    "neon": "apt",
    "elementary": "apt",
    "zorin": "apt",
    "arch": "pacman",
    "manjaro": "pacman",
    "endeavouros": "pacman",
    "garuda": "pacman",
    "fedora": "dnf",
    "rhel": "dnf",
    "centos": "dnf",
    "rocky": "dnf",
    "almalinux": "dnf",
}

_DEPENDENCY_SPECS = {
    "discid_core": DependencySpec(
        key="discid_core",
        label="Disc geometry / metadata core",
        commands=("discid", "cd-discid"),
        mode="any",
        package_hints={
            "apt": ("discid", "cd-discid"),
            "pacman": ("libdiscid",),
            "dnf": ("libdiscid", "cd-discid"),
        },
    ),
    "cdparanoia": DependencySpec(
        key="cdparanoia",
        label="Audio ripping",
        commands=("cdparanoia",),
        package_hints={
            "apt": ("cdparanoia",),
            "pacman": ("cdparanoia",),
            "dnf": ("cdparanoia",),
        },
    ),
    "cdrdao": DependencySpec(
        key="cdrdao",
        label="Disc image ripping (cdrdao)",
        commands=("cdrdao",),
        package_hints={
            "apt": ("cdrdao",),
            "pacman": ("cdrdao",),
            "dnf": ("cdrdao",),
        },
    ),
    "readom": DependencySpec(
        key="readom",
        label="Disc image ripping (readom)",
        commands=("readom",),
        package_hints={
            "apt": ("wodim",),
            "pacman": ("cdrtools",),
            "dnf": ("cdrtools",),
        },
    ),
    "flac": DependencySpec(
        key="flac",
        label="FLAC encoding",
        commands=("flac",),
        package_hints={
            "apt": ("flac",),
            "pacman": ("flac",),
            "dnf": ("flac",),
        },
    ),
    "lame": DependencySpec(
        key="lame",
        label="MP3 encoding",
        commands=("lame",),
        package_hints={
            "apt": ("lame",),
            "pacman": ("lame",),
            "dnf": ("lame",),
        },
    ),
    "oggenc": DependencySpec(
        key="oggenc",
        label="OGG Vorbis encoding",
        commands=("oggenc",),
        package_hints={
            "apt": ("vorbis-tools",),
            "pacman": ("vorbis-tools",),
            "dnf": ("vorbis-tools",),
        },
    ),
    "opusenc": DependencySpec(
        key="opusenc",
        label="Opus encoding",
        commands=("opusenc",),
        package_hints={
            "apt": ("opus-tools",),
            "pacman": ("opus-tools",),
            "dnf": ("opus-tools",),
        },
    ),
    "ffmpeg": DependencySpec(
        key="ffmpeg",
        label="ALAC / AAC encoding",
        commands=("ffmpeg",),
        package_hints={
            "apt": ("ffmpeg",),
            "pacman": ("ffmpeg",),
            "dnf": ("ffmpeg",),
        },
    ),
    "cd-info": DependencySpec(
        key="cd-info",
        label="Track-mode probing / CD-Text helper",
        commands=("cd-info",),
        package_hints={
            "apt": ("libcdio-utils",),
            "pacman": ("libcdio",),
            "dnf": ("libcdio",),
        },
    ),
    "notify-send": DependencySpec(
        key="notify-send",
        label="Desktop notifications",
        commands=("notify-send",),
        package_hints={
            "apt": ("libnotify-bin",),
            "pacman": ("libnotify",),
            "dnf": ("libnotify",),
        },
    ),
    "completion-sound": DependencySpec(
        key="completion-sound",
        label="Completion sound backend",
        commands=("pw-play", "paplay", "aplay", "canberra-gtk-play"),
        mode="any",
        package_hints={
            "apt": ("pipewire-bin", "pulseaudio-utils", "alsa-utils", "gnome-session-canberra"),
            "pacman": ("pipewire", "pulseaudio", "alsa-utils", "libcanberra"),
            "dnf": ("pipewire-utils", "pulseaudio-utils", "alsa-utils", "libcanberra"),
        },
    ),
    "eject": DependencySpec(
        key="eject",
        label="Automatic disc eject",
        commands=("eject",),
        package_hints={
            "apt": ("eject",),
            "pacman": ("eject",),
            "dnf": ("eject",),
        },
    ),
    "accuraterip": DependencySpec(
        key="accuraterip",
        label="AccurateRip verification helper",
        commands=("arver", "trackverify"),
        mode="any",
        package_hints=None,
    ),
}


def profile_from_args(args, cfg: Config) -> DependencyProfile:
    return DependencyProfile(
        device=args.device,
        image=not args.no_image,
        flac=not args.no_flac,
        mp3=not args.no_mp3,
        ogg=args.ogg,
        opus=args.opus,
        alac=args.alac,
        aac=args.aac,
        wav=args.wav,
        accuraterip=(args.accuraterip or cfg.accuraterip_enabled) and not args.no_accuraterip,
        cover_art=cfg.download_cover_art and not args.no_cover_art,
        image_ripper=cfg.image_ripper,
        cli_only=args.cli,
    )


def build_dependency_report(
    args,
    cfg: Config,
    *,
    which=shutil.which,
    os_release_text: str | None = None,
    textual_available: bool | None = None,
) -> DependencyReport:
    profile = profile_from_args(args, cfg)
    package_manager = detect_package_manager(os_release_text)
    distro_name = detect_distro_name(os_release_text)

    runtime = (
        RuntimeStatus("DiscVault version", True, __version__),
        RuntimeStatus("Python", True, platform.python_version()),
        RuntimeStatus(
            "Textual",
            textual_available if textual_available is not None else _textual_available(),
            "available" if (textual_available if textual_available is not None else _textual_available()) else "not importable",
        ),
        RuntimeStatus(
            "Linux distro",
            True,
            distro_name if package_manager is None else f"{distro_name} ({package_manager})",
        ),
        RuntimeStatus(
            "Config path",
            True,
            str(CONFIG_PATH),
        ),
    )

    required_specs = ["discid_core"]
    if profile.image:
        required_specs.append("readom" if profile.image_ripper == "readom" else "cdrdao")
    if any((profile.flac, profile.mp3, profile.ogg, profile.opus, profile.alac, profile.aac, profile.wav)):
        required_specs.append("cdparanoia")
    if profile.flac:
        required_specs.append("flac")
    if profile.mp3:
        required_specs.append("lame")
    if profile.ogg:
        required_specs.append("oggenc")
    if profile.opus:
        required_specs.append("opusenc")
    if profile.alac or profile.aac:
        required_specs.append("ffmpeg")
    if profile.accuraterip:
        required_specs.append("accuraterip")

    optional_specs = ["cd-info", "notify-send", "completion-sound", "eject"]
    if not profile.accuraterip:
        optional_specs.append("accuraterip")

    required = tuple(
        _check_dependency(_DEPENDENCY_SPECS[key], True, which, package_manager)
        for key in required_specs
    )
    optional = tuple(
        _check_dependency(_DEPENDENCY_SPECS[key], False, which, package_manager)
        for key in optional_specs
    )
    notes = tuple(_environment_notes(profile.device, which))
    return DependencyReport(
        runtime=runtime,
        required=required,
        optional=optional,
        notes=notes,
    )


def dependency_exit_code(report: DependencyReport) -> int:
    return 1 if any(not item.available for item in report.required) else 0


def format_dependency_report(report: DependencyReport) -> list[str]:
    lines = ["Dependency check for the current DiscVault selection", ""]

    lines.extend(_format_runtime_section(report.runtime))
    lines.append("")
    lines.extend(_format_dependency_section("Required for current selection", report.required))
    lines.append("")
    lines.extend(_format_dependency_section("Optional enhancements", report.optional))
    lines.append("")
    lines.extend(_format_notes_section(report.notes))
    return lines


def detect_package_manager(os_release_text: str | None = None) -> str | None:
    fields = _parse_os_release(os_release_text)
    candidates = [fields.get("ID", "")]
    like = fields.get("ID_LIKE", "")
    if like:
        candidates.extend(part.strip() for part in like.split())
    for candidate in candidates:
        manager = _DISTRO_TO_MANAGER.get(candidate)
        if manager:
            return manager
    return None


def detect_distro_name(os_release_text: str | None = None) -> str:
    fields = _parse_os_release(os_release_text)
    return fields.get("ID", "unknown-linux")


def package_manager_commands() -> dict[str, str]:
    return {
        "apt": "sudo apt install",
        "pacman": "sudo pacman -S",
        "dnf": "sudo dnf install",
    }


def recommended_install_packages(manager: str, spec_keys: tuple[str, ...]) -> tuple[str, ...]:
    packages: list[str] = []
    for key in spec_keys:
        spec = _DEPENDENCY_SPECS[key]
        if not spec.package_hints:
            continue
        for package in spec.package_hints.get(manager, ()):
            if package not in packages:
                packages.append(package)
    return tuple(packages)


def _check_dependency(
    spec: DependencySpec,
    required: bool,
    which,
    package_manager: str | None,
) -> DependencyStatus:
    found = tuple(command for command in spec.commands if which(command))
    available = bool(found) if spec.mode == "any" else len(found) == len(spec.commands)
    return DependencyStatus(
        spec=spec,
        required=required,
        available=available,
        found_commands=found,
        install_hint=_install_hint(spec, package_manager),
    )


def _install_hint(spec: DependencySpec, package_manager: str | None) -> str | None:
    if package_manager and spec.package_hints:
        packages = spec.package_hints.get(package_manager, ())
        if packages:
            cmd = package_manager_commands()[package_manager]
            return f"{cmd} {' '.join(packages)}"
    if spec.mode == "any":
        return f"Install one of: {', '.join(spec.commands)}"
    return f"Install: {', '.join(spec.commands)}"


def _format_runtime_section(items: tuple[RuntimeStatus, ...]) -> list[str]:
    lines = ["Python/runtime"]
    for item in items:
        prefix = "  ✓" if item.ok else "  !"
        lines.append(f"{prefix} {item.label}: {item.detail}")
    return lines


def _format_dependency_section(title: str, items: tuple[DependencyStatus, ...]) -> list[str]:
    lines = [title]
    for item in items:
        if item.available:
            detail = ", ".join(item.found_commands)
            lines.append(f"  ✓ {item.spec.label}: {detail}")
        else:
            lines.append(f"  {'✗' if item.required else '!'} {item.spec.label}: missing")
            if item.install_hint:
                lines.append(f"    Install hint: {item.install_hint}")
    return lines


def _format_notes_section(items: tuple[EnvironmentNote, ...]) -> list[str]:
    lines = ["Environment notes"]
    for item in items:
        lines.append(f"  > {item.label}: {item.detail}")
    return lines


def _environment_notes(device: str | None, which=shutil.which) -> list[EnvironmentNote]:
    notes = [
        EnvironmentNote("Cover art downloads", "network access is required at runtime"),
    ]
    if which("cd-discid") and not which("discid"):
        notes.append(
            EnvironmentNote(
                "MusicBrainz accuracy",
                "automatic MusicBrainz matching is using TOC fallback only; install discid for exact disc IDs",
            )
        )
    if not device:
        notes.append(EnvironmentNote("Device path", "not checked (use --device to inspect a specific path)"))
        return notes

    path = Path(device)
    if not path.exists():
        notes.append(EnvironmentNote("Device path", f"{device} does not exist"))
    elif os.access(path, os.R_OK):
        notes.append(EnvironmentNote("Device path", f"{device} exists and is readable"))
    else:
        notes.append(EnvironmentNote("Device path", f"{device} exists but is not readable by the current user"))
    return notes


def _parse_os_release(text: str | None) -> dict[str, str]:
    if text is None:
        path = Path("/etc/os-release")
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    fields: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        fields[key] = value.strip().strip('"')
    return fields


def _textual_available() -> bool:
    return importlib.util.find_spec("textual") is not None
