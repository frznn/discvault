from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                    cdrdao_command=config_mod.DEFAULT_CDRDAO_COMMAND,
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

    def test_save_uses_temp_file_and_leaves_no_tmp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config(base_dir="/music")
                cfg.save()
            finally:
                config_mod.CONFIG_PATH = old

            config_exists = config_path.exists()
            tmp_files = list(Path(tmp).glob(".config.toml.*.tmp"))

        self.assertTrue(config_exists)
        self.assertEqual(tmp_files, [])

    def test_failed_replace_cleans_up_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config(base_dir="/music")
                with patch("pathlib.Path.replace", side_effect=OSError("boom")):
                    with self.assertRaises(OSError):
                        cfg.save()
            finally:
                config_mod.CONFIG_PATH = old

            tmp_files = list(Path(tmp).glob(".config.toml.*.tmp"))

        self.assertEqual(tmp_files, [])


if __name__ == "__main__":
    unittest.main()
