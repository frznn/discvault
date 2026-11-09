from __future__ import annotations

import unittest

from discvault.metadata.types import Metadata, Track
from discvault.pipeline import BackupCallbacks, _audio_progress_callback, _image_progress_callback


class AudioProgressLabelTests(unittest.TestCase):
    def _run(self, meta, selected, current, fname="track02.cdda.wav"):
        seen = []
        cb = BackupCallbacks(stage_progress=lambda which, cur, tot, label: seen.append((which, cur, tot, label)))
        _audio_progress_callback(cb, meta, selected)(current, len(selected), fname)
        return seen[0]

    def test_label_uses_title_of_nth_selected_track(self):
        meta = Metadata("t", "A", "B", tracks=[Track(1, "One"), Track(2, "Two"), Track(5, "Five")])
        which, cur, tot, label = self._run(meta, [2, 5], 2)
        self.assertEqual((which, cur, tot), ("rip", 1, 2))
        self.assertEqual(label, "Ripping audio tracks (2/2): 05 – Five")

    def test_falls_back_to_filename_without_title(self):
        meta = Metadata("t", "A", "B", tracks=[Track(2, "  ")])
        self.assertTrue(self._run(meta, [2], 1)[3].endswith(": track02.cdda.wav"))

    def test_without_metadata_keeps_filename(self):
        seen = []
        cb = BackupCallbacks(stage_progress=lambda *a: seen.append(a))
        _audio_progress_callback(cb)(1, 3, "x.wav")
        self.assertEqual(seen[0][3], "Ripping audio tracks (1/3): x.wav")


class ImageProgressLabelTests(unittest.TestCase):
    def _labels(self, label):
        seen = []
        cb = BackupCallbacks(stage_progress=lambda which, cur, tot, lbl: seen.append((which, cur, tot, lbl)))
        meta = Metadata("t", "A", "B", tracks=[Track(1, "One"), Track(2, " ")])
        _image_progress_callback(cb, meta)(5, 10, label)
        return seen[0]

    def test_track_label_gets_title(self):
        self.assertEqual(self._labels("Disc image: track 1/12"), ("image", 5, 10, "Disc image: track 1/12 \u2013 One"))

    def test_percent_label_gets_title(self):
        self.assertEqual(self._labels("Disc image: track 1 (40%)")[3], "Disc image: track 1 (40%) \u2013 One")

    def test_untitled_track_and_byte_labels_unchanged(self):
        self.assertEqual(self._labels("Disc image: track 2/12")[3], "Disc image: track 2/12")
        self.assertEqual(self._labels("Disc image: 3/700 MB")[3], "Disc image: 3/700 MB")
        self.assertEqual(self._labels("Disc image: track 9/12")[3], "Disc image: track 9/12")


if __name__ == "__main__":
    unittest.main()
