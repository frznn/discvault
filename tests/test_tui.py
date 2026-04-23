from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from argparse import Namespace

from textual import events

from discvault.config import Config
from discvault import __version__
from discvault import library
from discvault.metadata.types import DiscInfo, Metadata, Track
from discvault.ui.tui import _folder_open_command
from discvault.ui.tui import _extras_announcement_text
from discvault.ui.tui import _extras_button_label
from discvault.ui.tui import _extras_notice_text
from discvault.ui.tui import _needs_overwrite_confirmation
from discvault.ui.tui import _output_stage_label
from discvault.ui.tui import MetadataDataTable
from discvault.ui.tui import StatusRichLog
from discvault.ui.tui import _target_button_destination
from discvault.ui.tui import _target_label_text
from discvault.ui.tui import DiscvaultApp


class TuiHelpersTests(unittest.TestCase):
    def test_status_log_scrolls_one_line_per_pointer_step(self) -> None:
        log = StatusRichLog()

        with patch.object(log, "_scroll_to", return_value=True) as scroll_to:
            log._scroll_down_for_pointer()
            scroll_to.assert_called_once()
            self.assertEqual(scroll_to.call_args.kwargs["y"], 1)

        with patch.object(log, "_scroll_to", return_value=True) as scroll_to:
            log._scroll_up_for_pointer()
            scroll_to.assert_called_once()
            self.assertEqual(scroll_to.call_args.kwargs["y"], -1)

    def test_metadata_table_scrolls_one_line_per_pointer_step(self) -> None:
        table = MetadataDataTable()

        with patch.object(table, "_scroll_to", return_value=True) as scroll_to:
            table._scroll_down_for_pointer()
            scroll_to.assert_called_once()
            self.assertEqual(scroll_to.call_args.kwargs["y"], 1)

        with patch.object(table, "_scroll_to", return_value=True) as scroll_to:
            table._scroll_up_for_pointer()
            scroll_to.assert_called_once()
            self.assertEqual(scroll_to.call_args.kwargs["y"], -1)

    def test_metadata_table_coalesces_duplicate_pointer_scroll_events(self) -> None:
        table = MetadataDataTable()
        first = events.MouseScrollDown(
            None, x=1, y=1, delta_x=0, delta_y=0, button=0, shift=False, meta=False, ctrl=False
        )
        second = events.MouseScrollDown(
            None, x=1, y=1, delta_x=0, delta_y=0, button=0, shift=False, meta=False, ctrl=False
        )
        second.time = first.time + 0.01
        third = events.MouseScrollDown(
            None, x=1, y=1, delta_x=0, delta_y=0, button=0, shift=False, meta=False, ctrl=False
        )
        third.time = second.time + 0.05

        self.assertFalse(table._is_duplicate_pointer_scroll(1, first))
        self.assertTrue(table._is_duplicate_pointer_scroll(1, second))
        self.assertFalse(table._is_duplicate_pointer_scroll(1, third))

    def test_metadata_table_pointer_scroll_prevents_default_base_handler(self) -> None:
        table = MetadataDataTable()
        event = events.MouseScrollDown(
            None, x=1, y=1, delta_x=0, delta_y=0, button=0, shift=False, meta=False, ctrl=False
        )

        with patch.object(type(table), "allow_vertical_scroll", new_callable=PropertyMock, return_value=True):
            with patch.object(table, "_scroll_down_for_pointer", return_value=True) as scroll_down:
                table._on_mouse_scroll_down(event)

        scroll_down.assert_called_once_with(animate=False)
        self.assertTrue(event._no_default_action)

    def test_title_bar_includes_version(self) -> None:
        self.assertEqual(DiscvaultApp.TITLE, "DiscVault")
        self.assertEqual(DiscvaultApp.SUB_TITLE, f"v{__version__}")
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
        self.assertEqual(app.scroll_sensitivity_y, 1.0)
        self.assertEqual(str(app.format_title(app.TITLE, app.SUB_TITLE)), f"DiscVault v{__version__}")

    def test_compose_includes_metadata_title(self) -> None:
        self.assertIn('Label("Metadata", id="metadata-title")', inspect.getsource(DiscvaultApp.compose))

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
        self.assertEqual(
            app._sources_dict(),
            {
                "musicbrainz": False,
                "gnudb": True,
                "cdtext": False,
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

    def test_extras_button_label_prefers_available_count(self) -> None:
        self.assertEqual(_extras_button_label(0, 2), "Extras (2)")
        self.assertEqual(_extras_button_label(1, 2), "Extras (1/2)")
        self.assertEqual(_extras_button_label(0, 0), "Extras")

    def test_extras_notice_text_reports_count_and_selection(self) -> None:
        self.assertIn("2", _extras_notice_text(0, 2, has_data_session=True))
        self.assertIn("selected for copy", _extras_notice_text(1, 2, has_data_session=True))
        fallback = _extras_notice_text(0, 0, has_data_session=True)
        self.assertIn("extra files", fallback)
        self.assertIn("Extras", fallback)
        self.assertNotIn("Extras…", fallback)

    def test_extras_announcement_text_prefers_available_count(self) -> None:
        with_count = _extras_announcement_text(3, has_data_session=True)
        self.assertIn("3 extra files", with_count)
        self.assertIn("Open Extras", with_count)
        self.assertNotIn("Extras…", with_count)
        fallback = _extras_announcement_text(0, has_data_session=True)
        self.assertIn("extra files", fallback)
        self.assertEqual(_extras_announcement_text(0, has_data_session=False), "")

    def test_announce_uses_embedded_status_toast(self) -> None:
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

        with patch.object(app, "_show_status_toast") as show:
            app._announce("Ready")
            show.assert_called_once_with("Ready", severity="information")

        with patch.object(app, "_show_status_toast") as show:
            app._announce("Careful", severity="warning")
            show.assert_called_once_with("Careful", severity="warning")

        with patch.object(app, "_show_status_toast") as show:
            app._announce("Nope", severity="error")
            show.assert_called_once_with("Nope", severity="error")

    def test_extras_announcement_waits_until_ready(self) -> None:
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
        app._disc_signature = ("disc",)
        app._extra_scan_bundle = SimpleNamespace(entries=[object(), object()])
        app.phase = "detecting"

        with patch.object(app, "_announce") as announce:
            app._maybe_notify_extras()
            announce.assert_not_called()

            app.phase = "ready"
            app._maybe_notify_extras()
            announce.assert_called_once()
            self.assertEqual(app._extras_announced_signature, ("disc",))

    def test_refresh_extras_button_stays_disabled_without_detected_extras(self) -> None:
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
        app.phase = "ready"
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=12)
        button = SimpleNamespace(label="", disabled=False)

        with patch.object(app, "query_one", return_value=button):
            app._refresh_extras_button()

        self.assertEqual(button.label, "Extras")
        self.assertTrue(button.disabled)

    def test_refresh_extras_button_enables_for_detected_data_track(self) -> None:
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
        app.phase = "ready"
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=14, track_modes={14: "data"})
        button = SimpleNamespace(label="", disabled=True)

        with patch.object(app, "query_one", return_value=button):
            app._refresh_extras_button()

        self.assertFalse(button.disabled)

    def test_refresh_extras_button_enables_for_metadata_extra_hint(self) -> None:
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
        app.phase = "ready"
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13)
        app._manual_meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=number, title=f"Track {number}") for number in range(1, 13)],
        )
        button = SimpleNamespace(label="", disabled=True)

        with patch.object(app, "query_one", return_value=button):
            app._refresh_extras_button()

        self.assertFalse(button.disabled)

    def test_run_meta_fetch_uses_audio_track_count_for_manual_search_on_extra_disc(self) -> None:
        cfg = Config()
        cfg.discogs.token = "token"
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=14)
        app._disc_signature = ("disc",)
        app._extra_scan_bundle = SimpleNamespace(track_number=14, entries=[object()])

        with patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup, \
            patch.object(app, "_tlog"), \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "musicbrainz": True,
                    "gnudb": False,
                },
                manual_query="Artist Album",
                manual_search=True,
            )

        self.assertEqual(search_releases.call_args.kwargs["disc_info"].track_count, 13)
        self.assertEqual(discogs_lookup.call_args.args[0].track_count, 13)

    def test_run_meta_fetch_queries_cdtext_when_enabled(self) -> None:
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13)
        expected = Metadata(
            source="CD-Text",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=1, title="Track 1")],
            match_quality="cdtext",
        )

        with patch("discvault.metadata.cdtext.lookup", return_value=[expected]) as cdtext_lookup, \
            patch.object(app, "_tlog"), \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "cdtext": True,
                    "musicbrainz": False,
                    "gnudb": False,
                }
            )

        self.assertEqual(app._candidates, [expected])
        self.assertEqual(cdtext_lookup.call_args.args[0], app._disc_info)
        self.assertEqual(cdtext_lookup.call_args.kwargs["driver"], cfg.cdrdao_driver)
        self.assertEqual(cdtext_lookup.call_args.kwargs["timeout"], cfg.metadata_timeout)
        self.assertFalse(cdtext_lookup.call_args.kwargs["debug"])

    def test_run_meta_fetch_auto_mode_ignores_manual_query_terms(self) -> None:
        cfg = Config()
        cfg.discogs.token = "token"
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13, mb_disc_id="disc-id")

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as lookup_release, \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup, \
            patch.object(app, "_tlog"), \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "cdtext": False,
                    "musicbrainz": True,
                    "gnudb": False,
                },
                manual_query="extraño weys rodrigo",
            )

        lookup_release.assert_called_once()
        search_releases.assert_not_called()
        discogs_lookup.assert_not_called()

    def test_run_meta_fetch_manual_query_skips_disc_lookup_and_seeds_discogs_from_search_results(self) -> None:
        cfg = Config()
        cfg.discogs.token = "token"
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13, mb_disc_id="disc-id")
        seeded = Metadata(
            source="MusicBrainz",
            album_artist="Extraño Weys",
            album="Rodrigo",
            tracks=[Track(number=1, title="Track 1")],
            match_quality="search",
        )

        with patch("discvault.metadata.musicbrainz.lookup", return_value=[]) as lookup_release, \
            patch("discvault.metadata.musicbrainz.search_releases", return_value=[seeded]) as search_releases, \
            patch("discvault.metadata.discogs.lookup", return_value=[]) as discogs_lookup, \
            patch.object(app, "_tlog"), \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "musicbrainz": True,
                    "gnudb": False,
                },
                manual_query="extraño weys rodrigo",
                manual_search=True,
            )

        lookup_release.assert_not_called()
        search_releases.assert_called_once()
        self.assertEqual(discogs_lookup.call_args.kwargs["seed_candidates"], [seeded])

    def test_run_meta_fetch_manual_query_ranks_best_match_first(self) -> None:
        cfg = Config()
        cfg.discogs.token = "token"
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13)

        wrong = Metadata(
            source="MusicBrainz",
            album_artist="Rodrigo",
            album="Random Album",
            tracks=[Track(number=1, title="Track 1")],
            match_quality="search",
        )
        right = Metadata(
            source="Discogs",
            album_artist="Extraño Weys",
            album="Rodrigo Laviña y Su Combo",
            tracks=[Track(number=1, title="Track 1")],
            match_quality="search",
        )

        with patch("discvault.metadata.musicbrainz.search_releases", return_value=[wrong]), \
            patch("discvault.metadata.discogs.lookup", return_value=[right]), \
            patch.object(app, "_tlog"), \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "musicbrainz": True,
                    "gnudb": False,
                },
                manual_query="extraño weys rodrigo",
                manual_search=True,
            )

        self.assertEqual(app._candidates[0], right)

    def test_run_meta_fetch_reports_gnudb_hint_when_configured_but_disabled(self) -> None:
        cfg = Config()
        cfg.gnudb.host = "gnudb.gnudb.org"
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
            debug=False,
            metadata_debug=False,
        )
        app = DiscvaultApp(args, cfg)
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=8, mb_toc="1 8 1000 150")

        with patch("discvault.metadata.cdtext.lookup", return_value=[]), \
            patch("discvault.metadata.musicbrainz.lookup", return_value=[]), \
            patch.object(app, "_tlog") as tlog, \
            patch.object(app, "call_from_thread"):
            app._run_meta_fetch(
                {
                    "cdtext": True,
                    "musicbrainz": True,
                    "gnudb": False,
                }
            )

        logged = "\n".join(call.args[0] for call in tlog.call_args_list if call.args)
        self.assertIn("GnuDB is configured but disabled", logged)

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

    def test_needs_overwrite_confirmation_for_non_empty_extras_dir(self) -> None:
        with TemporaryDirectory() as tmpdir:
            album_root = Path(tmpdir) / "Artist" / "Album"
            extras_dir = album_root / "extras"
            extras_dir.mkdir(parents=True)
            (extras_dir / "README.TXT").write_text("x")
            self.assertTrue(_needs_overwrite_confirmation(album_root, {"extras": True}))

    def test_target_label_text_is_empty_without_artist_and_album(self) -> None:
        self.assertEqual(_target_label_text("/music", "", "", ""), "")

    def test_target_label_text_formats_target_dir(self) -> None:
        self.assertIn("Target Dir:", _target_label_text("/music", "Artist", "Album", "2000"))

    def test_browse_base_directory_keeps_tracking_metadata_year(self) -> None:
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
        fields = {
            "input-artist": "Led Zeppelin",
            "input-album": "[Led Zeppelin IV]",
            "input-year": "1994",
        }
        target_input = SimpleNamespace(value="", placeholder="")

        def fake_query_one(selector: str, *_args, **_kwargs):
            if selector == "#target-dir-input":
                return target_input
            raise AssertionError(f"Unexpected selector: {selector}")

        def fake_input_val(widget_id: str) -> str:
            if widget_id == "target-dir-input":
                return target_input.value.strip()
            return fields.get(widget_id, "")

        with patch.object(app, "query_one", side_effect=fake_query_one), \
            patch.object(app, "_input_val", side_effect=fake_input_val), \
            patch.object(app, "_refresh_target_button"):
            app._apply_browse_dest((Path("/music"), True))

            self.assertTrue(app._target_is_base)
            self.assertEqual(app._target_base_dir, "/music")
            self.assertEqual(
                target_input.value,
                str(library.album_root("/music", "Led Zeppelin", "[Led Zeppelin IV]", "1994")),
            )
            self.assertEqual(
                app._target_album_root(),
                library.album_root("/music", "Led Zeppelin", "[Led Zeppelin IV]", "1994"),
            )

            fields["input-year"] = "2003"
            app._update_target_input()
            self.assertEqual(
                target_input.value,
                str(library.album_root("/music", "Led Zeppelin", "[Led Zeppelin IV]", "2003")),
            )
            self.assertEqual(
                app._target_album_root(),
                library.album_root("/music", "Led Zeppelin", "[Led Zeppelin IV]", "2003"),
            )

    def test_target_dir_changed_only_breaks_base_tracking_for_real_user_edits(self) -> None:
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
        app._target_is_base = True
        app._target_base_dir = "/music"

        with patch.object(app, "_refresh_target_button"):
            app._on_target_dir_changed(SimpleNamespace(input=SimpleNamespace(has_focus=False)))
            self.assertTrue(app._target_is_base)
            self.assertEqual(app._target_base_dir, "/music")

            app._on_target_dir_changed(SimpleNamespace(input=SimpleNamespace(has_focus=True)))
            self.assertFalse(app._target_is_base)
            self.assertEqual(app._target_base_dir, "")

    def test_ensure_meta_tracks_omits_trailing_extra_track_from_editor(self) -> None:
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
        app._disc_info = DiscInfo(device="/dev/cdrom", track_count=13)
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=number, title=f"Track {number}") for number in range(1, 13)],
        )

        tracks = app._ensure_meta_tracks(meta)

        self.assertEqual([track.number for track in tracks], list(range(1, 13)))
        self.assertEqual(app._possible_extra_tracks(meta), [13])


if __name__ == "__main__":
    unittest.main()
