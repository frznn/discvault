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
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(loaded.base_dir, 'music "special"')
        self.assertNotIn("default_src_discogs", saved_text)

    def test_legacy_discogs_preferred_source_keeps_auto_lookup_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[discvault]\n"
                'preferred_metadata_source = "discogs"\n'
            )
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(cfg.default_src_cdtext)
        self.assertTrue(cfg.default_src_musicbrainz)
        self.assertFalse(cfg.default_src_gnudb)

    def test_metadata_source_order_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.metadata_source_order = ["gnudb", "cdtext", "musicbrainz"]
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(loaded.metadata_source_order, ["gnudb", "cdtext", "musicbrainz"])
        self.assertIn('metadata_source_order = ["gnudb", "cdtext", "musicbrainz"]', saved_text)

    def test_metadata_source_order_defaults_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(cfg.metadata_source_order, ["musicbrainz", "gnudb", "cdtext"])

    def test_log_to_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.log_to_file = True
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(loaded.log_to_file)
        self.assertIn("log_to_file = true", saved_text)

    def test_log_to_file_defaults_to_false_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(cfg.log_to_file)

    def test_blank_redundant_track_artist_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.blank_redundant_track_artist = False
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(loaded.blank_redundant_track_artist)
        self.assertIn("blank_redundant_track_artist = false", saved_text)

    def test_blank_redundant_track_artist_defaults_to_true_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(cfg.blank_redundant_track_artist)

    def test_dedupe_equivalent_candidates_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.dedupe_equivalent_candidates = False
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(loaded.dedupe_equivalent_candidates)
        self.assertIn("dedupe_equivalent_candidates = false", saved_text)

    def test_dedupe_equivalent_candidates_defaults_to_true_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(cfg.dedupe_equivalent_candidates)

    def test_lookup_log_timings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.lookup_log_timings = True
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(loaded.lookup_log_timings)
        self.assertIn("lookup_log_timings = true", saved_text)

    def test_lookup_log_timings_defaults_to_false_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(cfg.lookup_log_timings)

    def test_manual_search_source_toggles_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.manual_src_musicbrainz = False
                cfg.manual_src_discogs = False
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(loaded.manual_src_musicbrainz)
        self.assertFalse(loaded.manual_src_discogs)
        self.assertIn("manual_src_musicbrainz = false", saved_text)
        self.assertIn("manual_src_discogs = false", saved_text)

    def test_manual_search_source_toggles_default_to_true_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(cfg.manual_src_musicbrainz)
        self.assertTrue(cfg.manual_src_discogs)

    def test_lookup_stop_at_first_match_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config()
                cfg.lookup_stop_at_first_match = False
                cfg.save()
                loaded = config_mod.Config.load()
                saved_text = config_path.read_text()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertFalse(loaded.lookup_stop_at_first_match)
        self.assertIn("lookup_stop_at_first_match = false", saved_text)

    def test_lookup_stop_at_first_match_defaults_to_true_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text("[discvault]\n")
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertTrue(cfg.lookup_stop_at_first_match)

    def test_metadata_source_order_drops_unknown_and_fills_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.toml"
            config_path.write_text(
                "[discvault]\n"
                'metadata_source_order = ["discogs", "gnudb", "musicbrainz"]\n'
            )
            old = config_mod.CONFIG_PATH
            config_mod.CONFIG_PATH = config_path
            try:
                cfg = config_mod.Config.load()
            finally:
                config_mod.CONFIG_PATH = old

        self.assertEqual(cfg.metadata_source_order, ["gnudb", "musicbrainz", "cdtext"])

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
