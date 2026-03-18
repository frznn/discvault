from __future__ import annotations

import unittest
from unittest.mock import patch

import discvault.device as device_mod


class DeviceTests(unittest.TestCase):
    def test_drive_status_maps_disc_ok(self) -> None:
        with patch("discvault.device.os.open", return_value=10), \
            patch("discvault.device.os.close"), \
            patch("discvault.device.fcntl.ioctl", return_value=device_mod._CDS_DISC_OK):
            self.assertEqual(device_mod.drive_status("/dev/cdrom"), "disc_ok")

    def test_media_changed_uses_ioctl_flag(self) -> None:
        with patch("discvault.device.os.open", return_value=10), \
            patch("discvault.device.os.close"), \
            patch("discvault.device.fcntl.ioctl", return_value=1):
            self.assertTrue(device_mod.media_changed("/dev/cdrom"))

    def test_is_readable_short_circuits_on_disc_ok(self) -> None:
        with patch("discvault.device.drive_status", return_value="disc_ok"), \
            patch("discvault.device.subprocess.run") as run:
            self.assertTrue(device_mod.is_readable("/dev/cdrom"))
        run.assert_not_called()

    def test_is_readable_falls_back_to_cdparanoia_when_status_unknown(self) -> None:
        with patch("discvault.device.drive_status", return_value="unknown"), \
            patch("discvault.device.subprocess.run") as run:
            run.return_value.returncode = 0
            self.assertTrue(device_mod.is_readable("/dev/cdrom"))
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
