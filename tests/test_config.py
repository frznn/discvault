from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import discvault.config as config_mod


class ConfigTests(unittest.TestCase):
    def test_invalid_numeric_values_fall_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[discvault]\n"
                'metadata_timeout = "oops"\n'
                'cdparanoia_sample_offset = "bad"\n'
                "accuraterip_enabled = true\n"
                "\n"
                "[gnudb]\n"
                'port = "bad"\n'
            )
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(cfg.metadata_timeout, config_mod.Config().metadata_timeout)
        self.assertEqual(cfg.cdparanoia_sample_offset, 0)
        self.assertEqual(cfg.gnudb.port, config_mod.GnudbConfig().port)
        self.assertTrue(cfg.accuraterip_enabled)

    def test_save_escapes_string_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config(
                    base_dir='music "special"',
                    work_dir="/tmp/discvault",
                    cdrdao_driver="generic-mmc-raw",
                )
                cfg.save()
                loaded = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(loaded.base_dir, 'music "special"')

    def test_completion_sound_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[discvault]\n"
                'completion_sound = "not-a-mode"\n'
            )
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(cfg.completion_sound, "bell")


if __name__ == "__main__":
    unittest.main()
