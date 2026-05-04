from __future__ import annotations

import unittest
from unittest.mock import patch

from discvault.config import Config, DriveProfile
from discvault.ui.settings import ConfigScreen


class InitialActiveDriveTests(unittest.TestCase):
    def test_active_drive_is_auto_when_cfg_device_is_empty(self) -> None:
        cfg = Config()
        screen = ConfigScreen(cfg)
        self.assertEqual(screen._active_drive_key, screen._AUTO_DEVICE_VALUE)

    def test_active_drive_is_cfg_device_when_set(self) -> None:
        cfg = Config()
        cfg.device = "/dev/sr1"
        screen = ConfigScreen(cfg)
        self.assertEqual(screen._active_drive_key, "/dev/sr1")


class InitialRipRowValuesTests(unittest.TestCase):
    def test_auto_uses_global_cfg_values(self) -> None:
        cfg = Config()
        cfg.cdparanoia_sample_offset = 7
        cfg.image_ripper = "readom"
        cfg.cdrdao_command = "cdrdao read-cd ..."
        screen = ConfigScreen(cfg)
        self.assertEqual(screen._initial_rip_sample_offset(), 7)
        self.assertEqual(screen._initial_rip_image_ripper(), "readom")
        self.assertEqual(screen._initial_rip_cdrdao_command(), "cdrdao read-cd ...")

    def test_specific_drive_with_profile_uses_profile_values(self) -> None:
        cfg = Config()
        cfg.device = "/dev/sr0"
        cfg.cdparanoia_sample_offset = 0
        cfg.image_ripper = "cdrdao"
        cfg.drives["/dev/sr0"] = DriveProfile(sample_offset=12, image_ripper="readom")
        screen = ConfigScreen(cfg)
        self.assertEqual(screen._initial_rip_sample_offset(), 12)
        self.assertEqual(screen._initial_rip_image_ripper(), "readom")
        # cdrdao_command not overridden → falls back to global
        self.assertEqual(screen._initial_rip_cdrdao_command(), cfg.cdrdao_command)

    def test_specific_drive_without_profile_uses_global_values(self) -> None:
        cfg = Config()
        cfg.device = "/dev/sr0"
        cfg.cdparanoia_sample_offset = 0
        cfg.image_ripper = "cdrdao"
        screen = ConfigScreen(cfg)
        self.assertEqual(screen._initial_rip_sample_offset(), 0)
        self.assertEqual(screen._initial_rip_image_ripper(), "cdrdao")


class DeviceOptionsTests(unittest.TestCase):
    def test_auto_detect_first_then_present_drives(self) -> None:
        cfg = Config()
        with patch(
            "discvault.ui.settings.dev_mod.list_available",
            return_value=["/dev/sr0", "/dev/sr1"],
        ):
            options = ConfigScreen(cfg)._device_options()
        self.assertEqual(
            options,
            [
                ("Auto-detect", ConfigScreen._AUTO_DEVICE_VALUE),
                ("/dev/sr0", "/dev/sr0"),
                ("/dev/sr1", "/dev/sr1"),
            ],
        )

    def test_saved_drive_profiles_are_listed_even_when_unplugged(self) -> None:
        cfg = Config()
        cfg.drives["/dev/sr2"] = DriveProfile(sample_offset=5)
        cfg.device = "/dev/cdrom"
        with patch(
            "discvault.ui.settings.dev_mod.list_available",
            return_value=["/dev/sr0"],
        ):
            options = ConfigScreen(cfg)._device_options()
        values = [v for _, v in options]
        self.assertEqual(values[0], ConfigScreen._AUTO_DEVICE_VALUE)
        self.assertIn("/dev/sr0", values)
        self.assertIn("/dev/cdrom", values)  # saved cfg.device
        self.assertIn("/dev/sr2", values)  # saved profile

    def test_no_present_drives_still_lists_auto_detect(self) -> None:
        cfg = Config()
        with patch(
            "discvault.ui.settings.dev_mod.list_available",
            return_value=[],
        ):
            options = ConfigScreen(cfg)._device_options()
        self.assertEqual(options, [("Auto-detect", ConfigScreen._AUTO_DEVICE_VALUE)])


if __name__ == "__main__":
    unittest.main()
