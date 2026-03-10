"""Configuration loading from ~/.config/discvault/config.toml."""
from __future__ import annotations
import os
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

_DEFAULT_BASE_DIR = str(Path.home() / "Music" / "CD Library")
_DEFAULT_WORK_DIR = "/tmp/discvault"
_CONFIG_PATH = Path.home() / ".config" / "discvault" / "config.toml"


@dataclass
class GnudbConfig:
    host: str = "gnudb.gnudb.org"
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
    metadata_timeout: int = 15
    gnudb: GnudbConfig = field(default_factory=GnudbConfig)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        if not _CONFIG_PATH.exists() or tomllib is None:
            return cfg
        try:
            with open(_CONFIG_PATH, "rb") as f:
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

        gn = data.get("gnudb", {})
        cfg.gnudb.host = gn.get("host", cfg.gnudb.host)
        cfg.gnudb.port = int(gn.get("port", cfg.gnudb.port))
        cfg.gnudb.hello_user = gn.get("hello_user", cfg.gnudb.hello_user)
        cfg.gnudb.hello_program = gn.get("hello_program", cfg.gnudb.hello_program)
        cfg.gnudb.hello_version = gn.get("hello_version", cfg.gnudb.hello_version)

        return cfg

    def config_path(self) -> Path:
        return _CONFIG_PATH
