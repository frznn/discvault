from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from discvault.disc import _try_cd_discid_mb, load_disc_info
from discvault.metadata.types import DiscInfo


class DiscInfoTests(unittest.TestCase):
    def test_try_cd_discid_mb_parses_musicbrainz_toc_output(self) -> None:
        info = DiscInfo(device="/dev/cdrom")
        response = Mock(stdout="3 150 15000 30000 45000\n")

        with patch("discvault.disc.subprocess.run", return_value=response):
            _try_cd_discid_mb("/dev/cdrom", info)

        self.assertEqual(info.track_count, 3)
        self.assertEqual(info.track_offsets, [150, 15000, 30000])
        self.assertEqual(info.leadout, 45000)
        self.assertEqual(info.mb_toc, "1 3 45000 150 15000 30000")

    def test_load_disc_info_keeps_musicbrainz_geometry_when_freedb_id_is_filled_later(self) -> None:
        mb_response = Mock(stdout="3 150 15000 30000 45000\n")
        freedb_response = Mock(stdout="deadbeef 3 150 15000 30000 598\n")

        with patch("discvault.disc.shutil.which") as which, patch(
            "discvault.disc.subprocess.run",
            side_effect=[mb_response, freedb_response],
        ):
            which.side_effect = lambda name: {
                "cd-discid": "/usr/bin/cd-discid",
            }.get(name)
            info = load_disc_info("/dev/cdrom")

        self.assertEqual(info.freedb_disc_id, "deadbeef")
        self.assertEqual(info.track_count, 3)
        self.assertEqual(info.track_offsets, [150, 15000, 30000])
        self.assertEqual(info.leadout, 45000)
        self.assertEqual(info.mb_toc, "1 3 45000 150 15000 30000")

    def test_load_disc_info_uses_libdiscid_when_discid_binary_is_missing(self) -> None:
        fake_module = Mock()
        fake_module.read.return_value = SimpleNamespace(
            id="mb-disc-id",
            freedb_id="free-db-id",
            track_offsets=[150, 15000, 30000],
            sectors=45000,
            first_track_num=1,
            last_track_num=3,
            toc_string="1 3 45000 150 15000 30000",
        )

        with patch("discvault.disc.shutil.which", return_value=None), patch(
            "discvault.disc._load_libdiscid",
            return_value=fake_module,
        ):
            info = load_disc_info("/dev/cdrom")

        self.assertEqual(info.mb_disc_id, "mb-disc-id")
        self.assertEqual(info.freedb_disc_id, "free-db-id")
        self.assertEqual(info.track_count, 3)
        self.assertEqual(info.track_offsets, [150, 15000, 30000])
        self.assertEqual(info.leadout, 45000)
        self.assertEqual(info.mb_toc, "1 3 45000 150 15000 30000")


if __name__ == "__main__":
    unittest.main()
