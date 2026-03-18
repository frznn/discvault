from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from argparse import Namespace

from discvault.config import Config
from discvault.ui.tui import _folder_open_command
from discvault.ui.tui import _output_stage_label
from discvault.ui.tui import DiscvaultApp


class TuiHelpersTests(unittest.TestCase):
    def test_folder_open_command_prefers_xdg_open(self) -> None:
        with patch("discvault.ui.tui.shutil.which") as which:
            which.side_effect = lambda name: {
                "xdg-open": "/usr/bin/xdg-open",
                "gio": "/usr/bin/gio",
                "open": "/usr/bin/open",
            }.get(name)
            self.assertEqual(
                _folder_open_command(Path("/tmp/example")),
                ["xdg-open", "/tmp/example"],
            )

    def test_folder_open_command_falls_back_to_gio(self) -> None:
        with patch("discvault.ui.tui.shutil.which") as which:
            which.side_effect = lambda name: {
                "gio": "/usr/bin/gio",
            }.get(name)
            self.assertEqual(
                _folder_open_command(Path("/tmp/example")),
                ["gio", "open", "/tmp/example"],
            )

    def test_folder_open_command_returns_none_without_backend(self) -> None:
        with patch("discvault.ui.tui.shutil.which", return_value=None):
            self.assertIsNone(_folder_open_command(Path("/tmp/example")))

    def test_discogs_label_is_plain(self) -> None:
        cfg = Config()
        cfg.discogs.token = ""
        args = Namespace(
            tracks=None,
            metadata_file=None,
            metadata_url=None,
            mp3_bitrate=320,
            mp3_quality=2,
            flac_compression=8,
            no_image=False,
            no_flac=False,
            no_mp3=False,
            ogg=False,
            opus=False,
            alac=False,
            aac=False,
            wav=False,
            iso=False,
            artist=None,
            album=None,
            year=None,
        )
        app = DiscvaultApp(args, cfg)
        self.assertEqual(app._discogs_source_label(), "Discogs")

    def test_output_stage_label_uses_copy_wording_for_wav(self) -> None:
        self.assertEqual(_output_stage_label("wav", "WAV"), "Saving tracks to WAV format")
        self.assertEqual(_output_stage_label("flac", "FLAC"), "Encoding tracks to FLAC format")


if __name__ == "__main__":
    unittest.main()
