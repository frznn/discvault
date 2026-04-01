from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discvault.cleanup import Cleanup
from discvault.config import Config
from discvault.extras import (
    copy_extra_files,
    copy_mounted_extra_files,
    list_extra_files,
    list_mounted_extra_files,
    probe_disc_extras,
    scan_disc_extras,
)
from discvault.metadata.types import DiscInfo, Metadata, Track


def _both_endian_16(value: int) -> bytes:
    return value.to_bytes(2, "little") + value.to_bytes(2, "big")


def _both_endian_32(value: int) -> bytes:
    return value.to_bytes(4, "little") + value.to_bytes(4, "big")


def _dir_record(name: bytes, extent: int, size: int, *, is_dir: bool) -> bytes:
    name_len = len(name)
    record_len = 33 + name_len + (0 if name_len % 2 else 1)
    record = bytearray(record_len)
    record[0] = record_len
    record[1] = 0
    record[2:10] = _both_endian_32(extent)
    record[10:18] = _both_endian_32(size)
    record[18:25] = b"\x7e\x03\x1f\x12\x00\x00\x00"
    record[25] = 0x02 if is_dir else 0x00
    record[26] = 0
    record[27] = 0
    record[28:32] = _both_endian_16(1)
    record[32] = name_len
    record[33:33 + name_len] = name
    return bytes(record)


def _build_test_iso(path: Path) -> None:
    total_sectors = 24
    data = bytearray(total_sectors * 2048)

    readme = b"hello from the root file\n"
    manual = b"nested manual contents\n"

    root_entries = [
        _dir_record(b"\x00", 20, 0, is_dir=True),
        _dir_record(b"\x01", 20, 0, is_dir=True),
        _dir_record(b"README.TXT;1", 21, len(readme), is_dir=False),
        _dir_record(b"DIR", 22, 0, is_dir=True),
    ]
    dir_entries = [
        _dir_record(b"\x00", 22, 0, is_dir=True),
        _dir_record(b"\x01", 20, 0, is_dir=True),
        _dir_record(b"MANUAL.PDF;1", 23, len(manual), is_dir=False),
    ]

    root_dir = b"".join(root_entries)
    dir_dir = b"".join(dir_entries)
    root_size = len(root_dir)
    dir_size = len(dir_dir)

    root_entries[0] = _dir_record(b"\x00", 20, root_size, is_dir=True)
    root_entries[1] = _dir_record(b"\x01", 20, root_size, is_dir=True)
    root_entries[3] = _dir_record(b"DIR", 22, dir_size, is_dir=True)
    root_dir = b"".join(root_entries)

    dir_entries[0] = _dir_record(b"\x00", 22, dir_size, is_dir=True)
    dir_entries[1] = _dir_record(b"\x01", 20, root_size, is_dir=True)
    dir_dir = b"".join(dir_entries)

    pvd = bytearray(2048)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    pvd[80:88] = _both_endian_32(total_sectors)
    pvd[128:132] = _both_endian_16(2048)
    root_record = _dir_record(b"\x00", 20, len(root_dir), is_dir=True)
    pvd[156:156 + len(root_record)] = root_record

    terminator = bytearray(2048)
    terminator[0] = 255
    terminator[1:6] = b"CD001"
    terminator[6] = 1

    data[16 * 2048:17 * 2048] = pvd
    data[17 * 2048:18 * 2048] = terminator
    data[20 * 2048:20 * 2048 + len(root_dir)] = root_dir
    data[22 * 2048:22 * 2048 + len(dir_dir)] = dir_dir
    data[21 * 2048:21 * 2048 + len(readme)] = readme
    data[23 * 2048:23 * 2048 + len(manual)] = manual

    path.write_bytes(bytes(data))


class ExtrasIsoTests(unittest.TestCase):
    def test_list_extra_files_reads_primary_iso_directory_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            iso_path = Path(tmp) / "disc.iso"
            _build_test_iso(iso_path)

            entries = list_extra_files(iso_path)

        self.assertEqual(
            [(entry.path, entry.size) for entry in entries],
            [
                ("DIR/MANUAL.PDF", len(b"nested manual contents\n")),
                ("README.TXT", len(b"hello from the root file\n")),
            ],
        )

    def test_copy_extra_files_preserves_nested_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            iso_path = tmp_path / "disc.iso"
            extras_dir = tmp_path / "extras"
            _build_test_iso(iso_path)

            copied, detail = copy_extra_files(
                iso_path,
                ["README.TXT", "DIR/MANUAL.PDF"],
                extras_dir,
                cleanup=Cleanup(),
            )

            self.assertEqual(detail, "")
            self.assertIsNotNone(copied)
            assert copied is not None
            self.assertEqual((extras_dir / "README.TXT").read_bytes(), b"hello from the root file\n")
            self.assertEqual((extras_dir / "DIR" / "MANUAL.PDF").read_bytes(), b"nested manual contents\n")

    def test_copy_extra_files_reports_missing_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            iso_path = Path(tmp) / "disc.iso"
            _build_test_iso(iso_path)

            copied, detail = copy_extra_files(iso_path, ["MISSING.BIN"], Path(tmp) / "extras")

        self.assertIsNone(copied)
        self.assertIn("missing ISO entries", detail)

    def test_scan_disc_extras_uses_metadata_hint_for_trailing_track(self) -> None:
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=13,
            track_offsets=[150 + (index * 75) for index in range(13)],
            leadout=150 + (13 * 75),
        )
        meta = Metadata(
            source="MusicBrainz",
            album_artist="Artist",
            album="Album",
            tracks=[Track(number=number, title=f"Track {number}") for number in range(1, 13)],
        )
        cfg = Config()

        def fake_rip_image(
            device,
            toc_path,
            bin_path,
            cleanup,
            *,
            command_template=None,
            debug=False,
            process_callback=None,
            progress_callback=None,
            track_count=None,
            track_offsets=None,
            leadout=None,
            driver=None,
        ):
            toc_path.write_text("TRACK AUDIO\nTRACK MODE1_RAW\n")
            bin_path.write_bytes(b"\x00" * 4096)
            return True, ""

        def fake_export_iso_from_bin(
            iso_path,
            bin_path,
            disc_info,
            *,
            toc_path=None,
            cleanup=None,
            progress_callback=None,
            track_no=None,
        ):
            self.assertEqual(track_no, 13)
            _build_test_iso(iso_path)
            return iso_path, ""

        with tempfile.TemporaryDirectory() as tmp:
            with patch("discvault.rip.rip_image", side_effect=fake_rip_image), patch(
                "discvault.rip.export_iso_from_bin",
                side_effect=fake_export_iso_from_bin,
            ):
                bundle, detail = scan_disc_extras(
                    "/dev/cdrom",
                    disc_info,
                    cfg,
                    meta=meta,
                    work_dir=Path(tmp),
                )

            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertEqual(bundle.track_number, 13)
            self.assertEqual(len(bundle.entries), 2)
            self.assertIn("track 13", detail.lower())
            bundle.close()

    def test_probe_disc_extras_reads_mounted_data_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mount_root = Path(tmp) / "mounted"
            mount_root.mkdir()
            (mount_root / "README.TXT").write_text("hello")
            (mount_root / "DIR").mkdir()
            (mount_root / "DIR" / "MANUAL.PDF").write_text("manual")

            with patch("discvault.extras._find_mounted_data_root", return_value=mount_root):
                bundle, detail = probe_disc_extras("/dev/cdrom")

            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertEqual(bundle.mount_root, mount_root)
            self.assertEqual(
                [(entry.path, entry.size) for entry in bundle.entries],
                [
                    ("DIR/MANUAL.PDF", len("manual")),
                    ("README.TXT", len("hello")),
                ],
            )
            self.assertIn("mounted data session", detail.lower())

    def test_scan_disc_extras_prefers_mounted_data_session(self) -> None:
        disc_info = DiscInfo(
            device="/dev/cdrom",
            track_count=3,
            track_offsets=[150, 300, 450],
            leadout=600,
        )
        cfg = Config()

        with tempfile.TemporaryDirectory() as tmp:
            mount_root = Path(tmp) / "mounted"
            mount_root.mkdir()
            (mount_root / "README.TXT").write_text("hello")

            with patch("discvault.extras._find_mounted_data_root", return_value=mount_root), \
                patch("discvault.rip.rip_image") as rip_image:
                bundle, detail = scan_disc_extras("/dev/cdrom", disc_info, cfg, work_dir=Path(tmp))

            self.assertIsNotNone(bundle)
            assert bundle is not None
            self.assertEqual(bundle.mount_root, mount_root)
            rip_image.assert_not_called()
            self.assertIn("mounted data session", detail.lower())

    def test_copy_mounted_extra_files_preserves_nested_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mount_root = tmp_path / "mounted"
            extras_dir = tmp_path / "extras"
            mount_root.mkdir()
            (mount_root / "README.TXT").write_text("hello")
            (mount_root / "DIR").mkdir()
            (mount_root / "DIR" / "MANUAL.PDF").write_text("manual")

            copied, detail = copy_mounted_extra_files(
                mount_root,
                ["README.TXT", "DIR/MANUAL.PDF"],
                extras_dir,
                cleanup=Cleanup(),
            )

            self.assertEqual(detail, "")
            self.assertIsNotNone(copied)
            assert copied is not None
            self.assertEqual((extras_dir / "README.TXT").read_text(), "hello")
            self.assertEqual((extras_dir / "DIR" / "MANUAL.PDF").read_text(), "manual")


if __name__ == "__main__":
    unittest.main()
