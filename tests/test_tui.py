from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from argparse import Namespace

from discvault.config import Config
from discvault.ui.tui import _folder_open_command
from discvault.ui.tui import _needs_overwrite_confirmation
from discvault.ui.tui import _output_stage_label
from discvault.ui.tui import _target_button_destination
from discvault.ui.tui import _target_label_text
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

    def test_sources_dict_uses_cached_state(self) -> None:
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
        app._src_mb = False
        app._src_gnudb = True
        app._src_cdtext = False
        app._src_discogs = True
        self.assertEqual(
            app._sources_dict(),
            {
                "musicbrainz": False,
                "gnudb": True,
                "cdtext": False,
                "discogs": True,
            },
        )

    def test_outputs_dict_uses_cached_state(self) -> None:
        cfg = Config()
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
        app._out_image = True
        app._out_iso = False
        app._out_flac = True
        app._out_mp3 = False
        app._out_ogg = True
        app._out_opus = False
        app._out_alac = True
        app._out_aac = False
        app._out_wav = True
        self.assertEqual(
            app._outputs_dict(),
            {
                "image": True,
                "iso": False,
                "flac": True,
                "mp3": False,
                "ogg": True,
                "opus": False,
                "alac": True,
                "aac": False,
                "wav": True,
            },
        )

    def test_output_stage_label_uses_copy_wording_for_wav(self) -> None:
        self.assertEqual(_output_stage_label("wav", "WAV"), "Saving tracks to WAV format")
        self.assertEqual(_output_stage_label("flac", "FLAC"), "Encoding tracks to FLAC format")

    def test_target_button_destination_uses_library_when_target_missing(self) -> None:
        with TemporaryDirectory() as tmpdir:
            library_root = Path(tmpdir)
            path, label, exact = _target_button_destination(None, str(library_root))
            self.assertEqual(path, library_root)
            self.assertEqual(label, "Open Library")
            self.assertFalse(exact)

    def test_target_button_destination_uses_target_when_it_exists(self) -> None:
        with TemporaryDirectory() as tmpdir:
            library_root = Path(tmpdir)
            target = library_root / "Artist" / "Album"
            target.mkdir(parents=True)
            path, label, exact = _target_button_destination(target, str(library_root))
            self.assertEqual(path, target)
            self.assertEqual(label, "Open Target Dir")
            self.assertTrue(exact)

    def test_needs_overwrite_confirmation_for_non_empty_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            album_root = Path(tmpdir) / "Artist" / "Album"
            album_root.mkdir(parents=True)
            (album_root / "existing.txt").write_text("x")
            self.assertTrue(_needs_overwrite_confirmation(album_root))

    def test_needs_overwrite_confirmation_false_for_missing_or_empty_directory(self) -> None:
        with TemporaryDirectory() as tmpdir:
            album_root = Path(tmpdir) / "Artist" / "Album"
            self.assertFalse(_needs_overwrite_confirmation(album_root))
            album_root.mkdir(parents=True)
            self.assertFalse(_needs_overwrite_confirmation(album_root))

    def test_needs_overwrite_confirmation_for_non_empty_selected_output_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            album_root = Path(tmpdir) / "Artist" / "Album"
            flac_dir = album_root / "flac"
            flac_dir.mkdir(parents=True)
            (flac_dir / "01 - Track.flac").write_text("x")
            self.assertTrue(_needs_overwrite_confirmation(album_root, {"flac": True}))

    def test_target_label_text_is_empty_without_artist_and_album(self) -> None:
        self.assertEqual(_target_label_text("/music", "", "", ""), "")

    def test_target_label_text_formats_target_dir(self) -> None:
        self.assertIn("Target Dir:", _target_label_text("/music", "Artist", "Album", "2000"))


if __name__ == "__main__":
    unittest.main()
