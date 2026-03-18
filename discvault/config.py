"""Configuration loading from ~/.config/discvault/config.toml."""
from __future__ import annotations
import json
import sys
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
_DEFAULT_WORK_DIR = "/tmp/discvault"
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


@dataclass
class Config:
    base_dir: str = _DEFAULT_BASE_DIR
    work_dir: str = _DEFAULT_WORK_DIR
    cdrdao_driver: str = "generic-mmc-raw"
    keep_wav: bool = False
    eject_after: bool = False
    metadata_timeout: int = 8
    cdparanoia_sample_offset: int = 0
    preferred_metadata_source: str = "musicbrainz"  # musicbrainz | gnudb | cdtext
    use_local_cddb_cache: bool = True
    accuraterip_enabled: bool = False
    download_cover_art: bool = True
    completion_sound: str = "bell"  # bell | chime | both | off
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
        except Exception:
            return cfg

        dv = data.get("discvault", {})
        cfg.base_dir = _as_str(dv.get("base_dir"), cfg.base_dir)
        cfg.work_dir = _as_str(dv.get("work_dir"), cfg.work_dir)
        cfg.cdrdao_driver = _as_str(dv.get("cdrdao_driver"), cfg.cdrdao_driver)
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
        preferred = dv.get("preferred_metadata_source", cfg.preferred_metadata_source)
        cfg.preferred_metadata_source = _normalize_metadata_source(preferred)
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
        return Config(
            base_dir=self.base_dir,
            work_dir=self.work_dir,
            cdrdao_driver=self.cdrdao_driver,
            keep_wav=self.keep_wav,
            eject_after=self.eject_after,
            metadata_timeout=self.metadata_timeout,
            cdparanoia_sample_offset=self.cdparanoia_sample_offset,
            preferred_metadata_source=self.preferred_metadata_source,
            use_local_cddb_cache=self.use_local_cddb_cache,
            accuraterip_enabled=self.accuraterip_enabled,
            download_cover_art=self.download_cover_art,
            completion_sound=self.completion_sound,
            opus_bitrate=self.opus_bitrate,
            aac_bitrate=self.aac_bitrate,
            gnudb=GnudbConfig(
                host=self.gnudb.host,
                port=self.gnudb.port,
                hello_user=self.gnudb.hello_user,
                hello_program=self.gnudb.hello_program,
                hello_version=self.gnudb.hello_version,
            ),
            discogs=DiscogsConfig(token=self.discogs.token),
        )

    def save(self) -> None:
        """Write current settings to the config file (TOML format)."""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "[discvault]",
            f"base_dir = {_toml_string(self.base_dir)}",
            f"work_dir = {_toml_string(self.work_dir)}",
            f"cdrdao_driver = {_toml_string(self.cdrdao_driver)}",
            f"keep_wav = {str(self.keep_wav).lower()}",
            f"eject_after = {str(self.eject_after).lower()}",
            f"metadata_timeout = {self.metadata_timeout}",
            f"cdparanoia_sample_offset = {self.cdparanoia_sample_offset}",
            f"preferred_metadata_source = {_toml_string(self.preferred_metadata_source)}",
            f"use_local_cddb_cache = {str(self.use_local_cddb_cache).lower()}",
            f"accuraterip_enabled = {str(self.accuraterip_enabled).lower()}",
            f"download_cover_art = {str(self.download_cover_art).lower()}",
            f"completion_sound = {_toml_string(self.completion_sound)}",
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
        CONFIG_PATH.write_text("\n".join(lines))


def first_run_setup(cfg: Config) -> None:
    """
    If no config file exists and we're on an interactive terminal, ask the user
    for the library base directory and save a config file.
    Skipped silently in non-interactive or dry-run contexts.
    """
    if CONFIG_PATH.exists() or not sys.stdin.isatty():
        return

    print()
    print("Welcome to discvault! No config file found.")
    print(f"Config will be saved to: {CONFIG_PATH}")
    print()
    print(f"Default library directory: {cfg.base_dir}")
    try:
        answer = input(
            "Library directory (press Enter to keep default): "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if answer:
        cfg.base_dir = answer

    try:
        cfg.save()
        print(f"Config saved to {CONFIG_PATH}")
    except OSError as e:
        print(f"Warning: could not save config: {e}")
    print()


def _normalize_metadata_source(value: str) -> str:
    if value == "local":
        return "gnudb"
    if value in {"musicbrainz", "gnudb", "cdtext", "discogs"}:
        return value
    return "musicbrainz"


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
