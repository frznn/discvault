"""Configuration loading from ~/.config/discvault/config.toml."""
from __future__ import annotations
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
class Config:
    base_dir: str = _DEFAULT_BASE_DIR
    work_dir: str = _DEFAULT_WORK_DIR
    cdrdao_driver: str = "generic-mmc-raw"
    keep_wav: bool = False
    eject_after: bool = False
    metadata_timeout: int = 8
    preferred_metadata_source: str = "musicbrainz"  # musicbrainz | gnudb | cdtext
    use_local_cddb_cache: bool = True
    gnudb: GnudbConfig = field(default_factory=GnudbConfig)

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
        cfg.base_dir = dv.get("base_dir", cfg.base_dir)
        cfg.work_dir = dv.get("work_dir", cfg.work_dir)
        cfg.cdrdao_driver = dv.get("cdrdao_driver", cfg.cdrdao_driver)
        cfg.keep_wav = bool(dv.get("keep_wav", cfg.keep_wav))
        cfg.eject_after = bool(dv.get("eject_after", cfg.eject_after))
        cfg.metadata_timeout = int(dv.get("metadata_timeout", cfg.metadata_timeout))
        preferred = dv.get("preferred_metadata_source", cfg.preferred_metadata_source)
        cfg.preferred_metadata_source = _normalize_metadata_source(preferred)
        cfg.use_local_cddb_cache = bool(
            dv.get("use_local_cddb_cache", cfg.use_local_cddb_cache)
        )

        gn = data.get("gnudb", {})
        cfg.gnudb.host = gn.get("host", cfg.gnudb.host)
        cfg.gnudb.port = int(gn.get("port", cfg.gnudb.port))
        cfg.gnudb.hello_user = gn.get("hello_user", cfg.gnudb.hello_user)
        cfg.gnudb.hello_program = gn.get("hello_program", cfg.gnudb.hello_program)
        cfg.gnudb.hello_version = gn.get("hello_version", cfg.gnudb.hello_version)

        return cfg

    def save(self) -> None:
        """Write current settings to the config file (TOML format)."""
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "[discvault]",
            f'base_dir = "{self.base_dir}"',
            f'work_dir = "{self.work_dir}"',
            f'cdrdao_driver = "{self.cdrdao_driver}"',
            f"keep_wav = {str(self.keep_wav).lower()}",
            f"eject_after = {str(self.eject_after).lower()}",
            f"metadata_timeout = {self.metadata_timeout}",
            f'preferred_metadata_source = "{self.preferred_metadata_source}"',
            f"use_local_cddb_cache = {str(self.use_local_cddb_cache).lower()}",
            "",
            "[gnudb]",
            f'host = "{self.gnudb.host}"',
            f"port = {self.gnudb.port}",
            f'hello_user = "{self.gnudb.hello_user}"',
            f'hello_program = "{self.gnudb.hello_program}"',
            f'hello_version = "{self.gnudb.hello_version}"',
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
    if value in {"musicbrainz", "gnudb", "cdtext"}:
        return value
    return "musicbrainz"
