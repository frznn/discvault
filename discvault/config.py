"""Configuration loading from ~/.config/discvault/config.toml."""
from __future__ import annotations
import copy
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

_DEFAULT_BASE_DIR = str(Path.home() / "Music" / "Library")
# Use ~/.cache/discvault/work instead of /tmp to avoid tmpfs size limits and
# systemd-tmpfiles cleanup, and to keep work files per-user.
_DEFAULT_WORK_DIR = str(Path.home() / ".cache" / "discvault" / "work")
CONFIG_PATH = Path.home() / ".config" / "discvault" / "config.toml"


@dataclass
class GnudbConfig:
    host: str = ""  # CDDBP disabled by default; set to "gnudb.gnudb.org" to enable
    port: int = 8880
    hello_user: str = ""
    hello_program: str = "discvault"
    hello_version: str = "1.0"


@dataclass
class DiscogsConfig:
    token: str = ""


DEFAULT_CDRDAO_COMMAND = (
    "cdrdao read-cd --device {device} --driver generic-mmc-raw -v 1 --read-raw"
    " --datafile {datafile} {toc}"
)


@dataclass
class Config:
    base_dir: str = _DEFAULT_BASE_DIR
    work_dir: str = _DEFAULT_WORK_DIR
    cdrdao_command: str = DEFAULT_CDRDAO_COMMAND
    image_ripper: str = "cdrdao"  # cdrdao | readom
    keep_wav: bool = False
    eject_after: bool = False
    metadata_timeout: int = 8
    cdparanoia_sample_offset: int = 0
    default_src_cdtext: bool = True
    default_src_musicbrainz: bool = True
    default_src_gnudb: bool = False
    default_src_discogs: bool = False
    use_local_cddb_cache: bool = True
    accuraterip_enabled: bool = False
    download_cover_art: bool = True
    completion_sound: str = "bell"  # bell | chime | both | off
    progress_style: str = "spinner"
    opus_bitrate: int = 160
    aac_bitrate: int = 256
    gnudb: GnudbConfig = field(default_factory=GnudbConfig)
    discogs: DiscogsConfig = field(default_factory=DiscogsConfig)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if not CONFIG_PATH.exists() or tomllib is None:
            return cfg
        try:
            with open(CONFIG_PATH, "rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            import warnings
            warnings.warn(f"discvault: failed to load config ({CONFIG_PATH}): {exc}")
            return cfg

        dv = data.get("discvault", {})
        cfg.base_dir = _as_str(dv.get("base_dir"), cfg.base_dir)
        cfg.work_dir = _as_str(dv.get("work_dir"), cfg.work_dir)
        # Migrate legacy cdrdao_driver + cdrdao_read_raw → cdrdao_command
        if "cdrdao_command" in dv:
            cfg.cdrdao_command = _as_str(dv["cdrdao_command"], cfg.cdrdao_command)
        elif "cdrdao_driver" in dv or "cdrdao_read_raw" in dv:
            driver = _as_str(dv.get("cdrdao_driver"), "generic-mmc-raw")
            read_raw = _as_bool(dv.get("cdrdao_read_raw"), True)
            cfg.cdrdao_command = (
                f"cdrdao read-cd --device {{device}} --driver {driver} -v 1"
                + (" --read-raw" if read_raw else "")
                + " --datafile {datafile} {toc}"
            )
        cfg.image_ripper = _normalize_image_ripper(
            _as_str(dv.get("image_ripper"), cfg.image_ripper)
        )
        cfg.keep_wav = _as_bool(dv.get("keep_wav"), cfg.keep_wav)
        cfg.eject_after = _as_bool(dv.get("eject_after"), cfg.eject_after)
        cfg.metadata_timeout = max(
            1,
            _as_int(dv.get("metadata_timeout"), cfg.metadata_timeout),
        )
        cfg.cdparanoia_sample_offset = _as_int(
            dv.get("cdparanoia_sample_offset"),
            cfg.cdparanoia_sample_offset,
        )
        # Migrate legacy preferred_metadata_source → per-source booleans if new keys absent.
        legacy_src = _normalize_metadata_source(_as_str(dv.get("preferred_metadata_source"), ""))
        def _src_default(key: str, default: bool) -> bool:
            if key in dv:
                return _as_bool(dv[key], default)
            # If only old key present, enable only that source by default.
            if legacy_src and "default_src_musicbrainz" not in dv:
                return legacy_src == key.removeprefix("default_src_")
            return default
        cfg.default_src_cdtext = _as_bool(dv.get("default_src_cdtext"), cfg.default_src_cdtext)
        cfg.default_src_musicbrainz = _src_default("default_src_musicbrainz", True)
        cfg.default_src_gnudb = _src_default("default_src_gnudb", False)
        cfg.default_src_discogs = _src_default("default_src_discogs", False)
        cfg.use_local_cddb_cache = _as_bool(
            dv.get("use_local_cddb_cache", cfg.use_local_cddb_cache),
            cfg.use_local_cddb_cache,
        )
        cfg.accuraterip_enabled = _as_bool(
            dv.get("accuraterip_enabled", cfg.accuraterip_enabled),
            cfg.accuraterip_enabled,
        )
        cfg.download_cover_art = _as_bool(
            dv.get("download_cover_art", cfg.download_cover_art),
            cfg.download_cover_art,
        )
        cfg.completion_sound = _normalize_completion_sound(
            _as_str(dv.get("completion_sound"), cfg.completion_sound)
        )
        cfg.progress_style = _normalize_progress_style(
            _as_str(dv.get("progress_style"), cfg.progress_style)
        )
        cfg.opus_bitrate = max(32, _as_int(dv.get("opus_bitrate"), cfg.opus_bitrate))
        cfg.aac_bitrate = max(96, _as_int(dv.get("aac_bitrate"), cfg.aac_bitrate))

        gn = data.get("gnudb", {})
        cfg.gnudb.host = _as_str(gn.get("host"), cfg.gnudb.host)
        cfg.gnudb.port = max(1, _as_int(gn.get("port"), cfg.gnudb.port))
        cfg.gnudb.hello_user = _as_str(gn.get("hello_user"), cfg.gnudb.hello_user)
        cfg.gnudb.hello_program = _as_str(
            gn.get("hello_program"), cfg.gnudb.hello_program
        )
        cfg.gnudb.hello_version = _as_str(
            gn.get("hello_version"), cfg.gnudb.hello_version
        )

        discogs = data.get("discogs", {})
        cfg.discogs.token = _as_str(discogs.get("token"), cfg.discogs.token)

        return cfg

    def clone(self) -> "Config":
        return copy.deepcopy(self)

    def save(self) -> None:
        """Write current settings to the config file (TOML format)."""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "[discvault]",
            f"base_dir = {_toml_string(self.base_dir)}",
            f"work_dir = {_toml_string(self.work_dir)}",
            f"cdrdao_command = {_toml_string(self.cdrdao_command)}",
            f"image_ripper = {_toml_string(self.image_ripper)}",
            f"keep_wav = {str(self.keep_wav).lower()}",
            f"eject_after = {str(self.eject_after).lower()}",
            f"metadata_timeout = {self.metadata_timeout}",
            f"cdparanoia_sample_offset = {self.cdparanoia_sample_offset}",
            f"default_src_cdtext = {str(self.default_src_cdtext).lower()}",
            f"default_src_musicbrainz = {str(self.default_src_musicbrainz).lower()}",
            f"default_src_gnudb = {str(self.default_src_gnudb).lower()}",
            f"default_src_discogs = {str(self.default_src_discogs).lower()}",
            f"use_local_cddb_cache = {str(self.use_local_cddb_cache).lower()}",
            f"accuraterip_enabled = {str(self.accuraterip_enabled).lower()}",
            f"download_cover_art = {str(self.download_cover_art).lower()}",
            f"completion_sound = {_toml_string(self.completion_sound)}",
            f"progress_style = {_toml_string(self.progress_style)}",
            f"opus_bitrate = {self.opus_bitrate}",
            f"aac_bitrate = {self.aac_bitrate}",
            "",
            "[gnudb]",
            f"host = {_toml_string(self.gnudb.host)}",
            f"port = {self.gnudb.port}",
            f"hello_user = {_toml_string(self.gnudb.hello_user)}",
            f"hello_program = {_toml_string(self.gnudb.hello_program)}",
            f"hello_version = {_toml_string(self.gnudb.hello_version)}",
            "",
            "[discogs]",
            f"token = {_toml_string(self.discogs.token)}",
            "",
        ]
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=CONFIG_PATH.parent,
                prefix=f".{CONFIG_PATH.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write("\n".join(lines))
                tmp_path = Path(handle.name)
            tmp_path.replace(CONFIG_PATH)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)


def first_run_setup(cfg: Config) -> None:
    """
    If no config file exists and we're on an interactive terminal, ask the user
    for the library base directory and save a config file.
    Skipped silently in non-interactive or dry-run contexts.
    """
    if CONFIG_PATH.exists() or not sys.stdin.isatty():
        return

    try:
        from rich.console import Console
        con: object = Console()
        def _print(msg: str = "") -> None:
            con.print(msg)  # type: ignore[union-attr]
        def _input(prompt: str) -> str:
            return con.input(prompt)  # type: ignore[union-attr]
    except ImportError:
        def _print(msg: str = "") -> None:  # type: ignore[misc]
            print(msg)
        def _input(prompt: str) -> str:  # type: ignore[misc]
            return input(prompt)

    _print()
    _print("[bold]Welcome to discvault![/bold] No config file found.")
    _print(f"Config will be saved to: [dim]{CONFIG_PATH}[/dim]")
    _print()
    _print(f"Default library directory: [cyan]{cfg.base_dir}[/cyan]")
    try:
        answer = _input("Library directory (press Enter to keep default): ").strip()
    except (EOFError, KeyboardInterrupt):
        _print()
        return

    if answer:
        cfg.base_dir = answer

    try:
        cfg.save()
        _print(f"[green]✓[/green] Config saved to [dim]{CONFIG_PATH}[/dim]")
    except OSError as e:
        _print(f"[yellow]Warning:[/yellow] could not save config: {e}")
    _print()


def _normalize_metadata_source(value: str) -> str:
    if value == "local":
        return "gnudb"
    if value in {"musicbrainz", "gnudb", "cdtext", "discogs"}:
        return value
    return "musicbrainz"


def _normalize_image_ripper(value: str) -> str:
    if value.strip().lower() in {"cdrdao", "readom"}:
        return value.strip().lower()
    return "cdrdao"


def _normalize_progress_style(value: str) -> str:
    if value.strip().lower() in {"none", "spinner", "loading", "pulse", "color"}:
        return value.strip().lower()
    return "spinner"


def _normalize_completion_sound(value: str) -> str:
    lowered = value.strip().lower()
    if lowered in {"bell", "chime", "both", "off"}:
        return lowered
    return "bell"


def _as_str(value: object, default: str) -> str:
    return value if isinstance(value, str) else default


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, int):
        return bool(value)
    return default


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _toml_string(value: str) -> str:
    return json.dumps(value)
