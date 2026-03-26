from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from discvault.cleanup import Cleanup
from discvault.encode import encode_tracks
from discvault.metadata.types import Metadata, Track


class EncodeTests(unittest.TestCase):
    def test_wav_output_copies_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wav_path = tmp_path / "track01.cdda.wav"
            wav_path.write_bytes(b"RIFFtest")
            wav_dir = tmp_path / "wav"

            ok = encode_tracks(
                [wav_path],
                Metadata(
                    source="Manual",
                    album_artist="Artist",
                    album="Album",
                    tracks=[Track(number=1, title="Intro")],
                ),
                wav_dir=wav_dir,
                cleanup=Cleanup(),
            )

            out = wav_dir / "01 - Intro.wav"
            self.assertTrue(ok)
            self.assertTrue(out.exists())
            self.assertEqual(out.read_bytes(), b"RIFFtest")

    def test_encoder_success_requires_non_empty_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            wav_path = tmp_path / "track01.cdda.wav"
            wav_path.write_bytes(b"RIFFtest")
            flac_dir = tmp_path / "flac"

            class FakeResult:
                returncode = 0
                stderr = ""

            with patch("discvault.encode.subprocess.run", return_value=FakeResult()):
                ok = encode_tracks(
                    [wav_path],
                    Metadata(
                        source="Manual",
                        album_artist="Artist",
                        album="Album",
                        tracks=[Track(number=1, title="Intro")],
                    ),
                    flac_dir=flac_dir,
                    cleanup=Cleanup(),
                )

            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
