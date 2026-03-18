from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from discvault.metadata import fileimport


class FileImportTests(unittest.TestCase):
    def test_import_json_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "album.json"
            path.write_text(
                '{'
                '"album_artist":"Artist",'
                '"album":"Album",'
                '"year":"2001",'
                '"tracks":[{"number":1,"title":"One"},{"number":2,"title":"Two","artist":"Guest"}]'
                '}'
            )

            results = fileimport.lookup(path)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].album_artist, "Artist")
        self.assertEqual(results[0].tracks[1].artist, "Guest")

    def test_import_cue_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "disc.cue"
            path.write_text(
                'PERFORMER "Artist"\n'
                'TITLE "Album"\n'
                'FILE "disc.bin" BINARY\n'
                '  TRACK 01 AUDIO\n'
                '    TITLE "Intro"\n'
                '  TRACK 02 AUDIO\n'
                '    TITLE "Song"\n'
                '    PERFORMER "Guest"\n'
            )

            results = fileimport.lookup(path)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].album, "Album")
        self.assertEqual(results[0].tracks[0].title, "Intro")
        self.assertEqual(results[0].tracks[1].artist, "Guest")


if __name__ == "__main__":
    unittest.main()
