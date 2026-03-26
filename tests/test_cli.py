from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from discvault.cli import _run
from discvault.config import Config
from discvault.metadata.types import DiscInfo, Metadata


class CliPipelineTests(unittest.TestCase):
    def test_image_only_run_skips_audio_rip_and_encode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(base_dir=tmp, work_dir=str(Path(tmp) / "work"))
            disc_info = DiscInfo(
                device="/dev/cdrom",
                track_count=3,
                track_offsets=[150, 15000, 30000],
                leadout=45000,
            )
            meta = Metadata(source="MusicBrainz", album_artist="Artist", album="Album", year="2000")

            args = Namespace(
                device="/dev/cdrom",
                dry_run=False,
                debug=False,
                metadata_debug=False,
                no_image=False,
                iso=False,
                no_flac=True,
                no_mp3=True,
                ogg=False,
                opus=False,
                alac=False,
                aac=False,
                wav=False,
                artist=None,
                album=None,
                year=None,
                metadata_file=None,
                metadata_url=None,
                skip_metadata=False,
                strict_manual_fallback=False,
                tui=False,
                flac_compression=8,
                mp3_bitrate=320,
                mp3_quality=2,
                opus_bitrate=None,
                aac_bitrate=None,
                no_verify=False,
                no_cover_art=False,
                sample_offset=None,
                accuraterip=False,
                no_accuraterip=False,
                tracks=None,
            )

            with patch("discvault.cli.signal.signal"), \
                patch("discvault.device.detect", return_value="/dev/cdrom"), \
                patch("discvault.device.is_readable", return_value=True), \
                patch("discvault.disc.load_disc_info", return_value=disc_info), \
                patch("discvault.metadata.lookup.fetch_candidates", return_value=[meta]), \
                patch("discvault.rip.rip_image", return_value=(True, "")), \
                patch("discvault.rip.rip_audio") as rip_audio, \
                patch("discvault.encode.encode_tracks") as encode_tracks, \
                patch("discvault.artwork.download_cover_art", return_value=None), \
                patch("discvault.alerts.play_completion_sound"), \
                patch("discvault.alerts.send_desktop_notification"), \
                patch("discvault.cli.success"):
                _run(args, cfg)

            rip_audio.assert_not_called()
            encode_tracks.assert_not_called()

    def test_unsupported_metadata_url_is_warned_and_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config(base_dir=tmp, work_dir=str(Path(tmp) / "work"))
            disc_info = DiscInfo(
                device="/dev/cdrom",
                track_count=3,
                track_offsets=[150, 15000, 30000],
                leadout=45000,
            )
            meta = Metadata(source="MusicBrainz", album_artist="Artist", album="Album", year="2000")

            args = Namespace(
                device="/dev/cdrom",
                dry_run=True,
                debug=False,
                metadata_debug=False,
                no_image=False,
                iso=False,
                no_flac=False,
                no_mp3=False,
                ogg=False,
                opus=False,
                alac=False,
                aac=False,
                wav=False,
                artist="Artist",
                album="Album",
                year="2000",
                metadata_file=None,
                metadata_url="https://example.com/album/test",
                skip_metadata=False,
                strict_manual_fallback=False,
                tui=False,
                flac_compression=8,
                mp3_bitrate=320,
                mp3_quality=2,
                opus_bitrate=None,
                aac_bitrate=None,
                no_verify=False,
                no_cover_art=False,
                sample_offset=None,
                accuraterip=False,
                no_accuraterip=False,
                tracks=None,
            )

            with patch("discvault.cli.signal.signal"), \
                patch("discvault.device.detect", return_value="/dev/cdrom"), \
                patch("discvault.device.is_readable", return_value=True), \
                patch("discvault.disc.load_disc_info", return_value=disc_info), \
                patch("discvault.metadata.lookup.fetch_candidates", return_value=[meta]) as fetch_candidates, \
                patch("discvault.cli.warn") as warn:
                _run(args, cfg)

            warn.assert_any_call("Metadata URL import skipped: unsupported provider (example.com).")
            self.assertEqual(fetch_candidates.call_args.kwargs["metadata_url"], "")


if __name__ == "__main__":
    unittest.main()
