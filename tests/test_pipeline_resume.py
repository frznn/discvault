from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discvault.pipeline import (
    _existing_cover_art,
    _existing_extras_present,
    _existing_image_artifacts,
    _existing_wav_files,
)


class ExistingImageArtifactsTests(unittest.TestCase):
    def _write(self, path: Path, payload: bytes = b"x") -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    def test_returns_bin_cue_when_preferred_stem_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp)
            self._write(img_dir / "Album.bin")
            self._write(img_dir / "Album.cue")
            result = _existing_image_artifacts(img_dir, "Album")
        assert result is not None
        bin_path, cue_path, toc_path = result
        self.assertEqual(bin_path.name, "Album.bin")
        self.assertEqual(cue_path.name, "Album.cue")
        self.assertIsNone(toc_path)

    def test_returns_toc_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp)
            self._write(img_dir / "Album.bin")
            self._write(img_dir / "Album.cue")
            self._write(img_dir / "Album.toc")
            result = _existing_image_artifacts(img_dir, "Album")
        assert result is not None
        _, _, toc_path = result
        self.assertIsNotNone(toc_path)
        self.assertEqual(toc_path.name, "Album.toc")

    def test_returns_none_when_only_bin_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp)
            self._write(img_dir / "Album.bin")
            self.assertIsNone(_existing_image_artifacts(img_dir, "Album"))

    def test_returns_none_when_bin_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp)
            self._write(img_dir / "Album.bin", b"")
            self._write(img_dir / "Album.cue")
            self.assertIsNone(_existing_image_artifacts(img_dir, "Album"))

    def test_falls_back_to_any_bin_cue_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            img_dir = Path(tmp)
            self._write(img_dir / "Different.bin")
            self._write(img_dir / "Different.cue")
            result = _existing_image_artifacts(img_dir, "Album")
        assert result is not None
        self.assertEqual(result[0].name, "Different.bin")

    def test_returns_none_when_dir_missing(self) -> None:
        self.assertIsNone(_existing_image_artifacts(Path("/nonexistent"), "Album"))


class ExistingWavFilesTests(unittest.TestCase):
    def _wav(self, work_dir: Path, num: int, total: int, *, empty: bool = False) -> Path:
        from discvault.rip import _wav_name_for_track
        path = work_dir / _wav_name_for_track(num, total)
        path.write_bytes(b"" if empty else b"riff")
        return path

    def test_returns_paths_when_all_selected_tracks_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self._wav(work_dir, 1, 3)
            self._wav(work_dir, 2, 3)
            self._wav(work_dir, 3, 3)
            result = _existing_wav_files(work_dir, 3, [1, 2, 3])
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual([p.name for p in result], ["track01.cdda.wav", "track02.cdda.wav", "track03.cdda.wav"])

    def test_returns_none_when_one_wav_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self._wav(work_dir, 1, 3)
            self._wav(work_dir, 3, 3)  # track 2 missing
            result = _existing_wav_files(work_dir, 3, [1, 2, 3])
        self.assertIsNone(result)

    def test_returns_none_when_a_wav_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            work_dir = Path(tmp)
            self._wav(work_dir, 1, 2)
            self._wav(work_dir, 2, 2, empty=True)
            self.assertIsNone(_existing_wav_files(work_dir, 2, [1, 2]))

    def test_returns_none_when_dir_missing(self) -> None:
        self.assertIsNone(_existing_wav_files(Path("/nonexistent"), 1, [1]))

    def test_returns_none_when_no_selected_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_existing_wav_files(Path(tmp), 1, []))


class ExistingCoverArtTests(unittest.TestCase):
    def test_finds_jpg_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cover.jpg").write_bytes(b"x")
            (root / "cover.png").write_bytes(b"x")
            self.assertEqual(_existing_cover_art(root).name, "cover.jpg")  # type: ignore[union-attr]

    def test_falls_through_to_png_when_jpg_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cover.png").write_bytes(b"x")
            self.assertEqual(_existing_cover_art(root).name, "cover.png")  # type: ignore[union-attr]

    def test_returns_none_for_empty_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cover.jpg").write_bytes(b"")
            self.assertIsNone(_existing_cover_art(root))

    def test_returns_none_when_no_cover(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_existing_cover_art(Path(tmp)))


class ExistingExtrasPresentTests(unittest.TestCase):
    def test_true_when_at_least_one_file_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extras = Path(tmp) / "extras"
            extras.mkdir()
            (extras / "booklet.pdf").write_bytes(b"x")
            self.assertTrue(_existing_extras_present(extras))

    def test_false_when_dir_missing(self) -> None:
        self.assertFalse(_existing_extras_present(Path("/nonexistent")))

    def test_false_when_dir_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_existing_extras_present(Path(tmp)))


if __name__ == "__main__":
    unittest.main()
