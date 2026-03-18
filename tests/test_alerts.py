from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import call, patch

import discvault.alerts as alerts


class AlertsTests(unittest.TestCase):
    def test_play_completion_sound_defaults_to_bell(self) -> None:
        with patch.object(alerts, "play_completion_bell", return_value=True) as bell:
            self.assertTrue(alerts.play_completion_sound("bell"))
        bell.assert_called_once_with()

    def test_play_completion_sound_both_accepts_either_backend(self) -> None:
        with patch.object(alerts, "play_completion_bell", return_value=False) as bell, \
            patch.object(alerts, "play_completion_chime", return_value=True) as chime:
            self.assertTrue(alerts.play_completion_sound("both"))
        bell.assert_called_once_with()
        chime.assert_called_once_with()

    def test_play_completion_bell_writes_bel(self) -> None:
        with patch("discvault.alerts.sys.stdout.write") as write, \
            patch("discvault.alerts.sys.stdout.flush") as flush:
            self.assertTrue(alerts.play_completion_bell())
        write.assert_called_once_with("\a")
        flush.assert_called_once_with()

    def test_ensure_chime_file_creates_wav(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            chime_path = Path(tmp) / "complete.wav"
            with patch.object(alerts, "_CHIME_PATH", chime_path):
                path = alerts.ensure_chime_file()

            self.assertEqual(path, chime_path)
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 44)

    def test_play_completion_chime_falls_back_to_next_backend(self) -> None:
        with patch.object(alerts, "ensure_chime_file", return_value=Path("/tmp/chime.wav")), \
            patch.object(alerts, "_audio_commands", return_value=[["pw-play", "/tmp/chime.wav"], ["aplay", "-q", "/tmp/chime.wav"]]), \
            patch.object(alerts, "_run_quiet", side_effect=[False, True]) as run_quiet:
            self.assertTrue(alerts.play_completion_chime())

        run_quiet.assert_has_calls(
            [
                call(["pw-play", "/tmp/chime.wav"], timeout=8),
                call(["aplay", "-q", "/tmp/chime.wav"], timeout=8),
            ]
        )

    def test_send_desktop_notification_checks_command_result(self) -> None:
        with patch("discvault.alerts.shutil.which", return_value="/usr/bin/notify-send"), \
            patch.object(alerts, "_run_quiet", return_value=False) as run_quiet:
            self.assertFalse(alerts.send_desktop_notification("Done", "Finished"))

        run_quiet.assert_called_once()


if __name__ == "__main__":
    unittest.main()
