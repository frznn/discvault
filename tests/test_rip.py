from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discvault.metadata.types import DiscInfo
from discvault.rip import export_iso_from_bin, write_cue_file


class ImageExportTests(unittest.TestCase):
    def test_write_cue_file_creates_raw_cue_sidecar(self) -> None:
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=3,
            track_offsets=[150, 300, 450],
            leadout=600,
            track_modes={1: "audio", 2: "audio", 3: "data"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cue_path = tmp_path / "disc.cue"
            bin_path = tmp_path / "disc.bin"
            bin_path.write_bytes(b"")

            ok = write_cue_file(cue_path, bin_path, disc_info)

            self.assertTrue(ok)
            text = cue_path.read_text()

        self.assertIn('FILE "disc.bin" BINARY', text)
        self.assertIn("TRACK 01 AUDIO", text)
        self.assertIn("INDEX 01 00:00:00", text)
        self.assertIn("TRACK 03 MODE1/2352", text)
        self.assertIn("INDEX 01 00:04:00", text)

    def test_export_iso_from_bin_extracts_mode1_payload(self) -> None:
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=1,
            track_offsets=[150],
            leadout=153,
            track_modes={1: "data"},
        )

        payloads = [bytes([index]) * 2048 for index in (1, 2, 3)]
        raw_frames = []
        for payload in payloads:
            sector = bytearray(2352)
            sector[16:16 + 2048] = payload
            raw_frames.append(bytes(sector))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_path = tmp_path / "disc.bin"
            iso_path = tmp_path / "disc.iso"
            bin_path.write_bytes(b"".join(raw_frames))

            exported_iso, detail = export_iso_from_bin(iso_path, bin_path, disc_info)

            self.assertEqual(detail, "")
            self.assertEqual(exported_iso, iso_path)
            self.assertEqual(iso_path.read_bytes(), b"".join(payloads))

    def test_export_iso_from_bin_skips_audio_only_disc(self) -> None:
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=2,
            track_offsets=[150, 300],
            leadout=450,
            track_modes={1: "audio", 2: "audio"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bin_path = tmp_path / "disc.bin"
            iso_path = tmp_path / "disc.iso"
            bin_path.write_bytes(b"\x00" * (2352 * 300))

            exported_iso, detail = export_iso_from_bin(iso_path, bin_path, disc_info)

        self.assertIsNone(exported_iso)
        self.assertIn("no data track", detail.lower())


if __name__ == "__main__":
    unittest.main()
