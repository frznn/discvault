from __future__ import annotations

import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from discvault.config import Config
import discvault.deps as deps_mod


def _args(**overrides) -> Namespace:
    values = {
        "device": None,
        "no_image": False,
        "no_flac": False,
        "no_mp3": False,
        "ogg": False,
        "opus": False,
        "alac": False,
        "aac": False,
        "wav": False,
        "accuraterip": False,
        "no_accuraterip": False,
        "no_cover_art": False,
        "cli": False,
    }
    values.update(overrides)
    return Namespace(**values)


def _which_from(commands: set[str]):
    return lambda command: f"/usr/bin/{command}" if command in commands else None


class DependencyReportTests(unittest.TestCase):
    def test_default_profile_requires_core_image_flac_and_mp3(self) -> None:
        cfg = Config()
        args = _args()
        report = deps_mod.build_dependency_report(
            args,
            cfg,
            which=_which_from({"cd-discid", "cdrdao", "cdparanoia", "flac", "lame"}),
            os_release_text='ID=ubuntu\nID_LIKE=debian\n',
            textual_available=True,
        )

        self.assertEqual(
            [item.spec.key for item in report.required],
            ["discid_core", "cdrdao", "cdparanoia", "flac", "lame"],
        )
        self.assertEqual(deps_mod.dependency_exit_code(report), 0)

    def test_audio_only_profile_skips_image_ripper(self) -> None:
        cfg = Config()
        args = _args(no_image=True, no_flac=True, no_mp3=False, ogg=True)
        report = deps_mod.build_dependency_report(
            args,
            cfg,
            which=_which_from({"discid", "cdparanoia", "lame", "oggenc"}),
            os_release_text="ID=arch\n",
            textual_available=True,
        )

        self.assertEqual(
            [item.spec.key for item in report.required],
            ["discid_core", "cdparanoia", "lame", "oggenc"],
        )

    def test_readom_profile_requires_readom_not_cdrdao(self) -> None:
        cfg = Config(image_ripper="readom")
        args = _args(no_flac=True, no_mp3=True)
        report = deps_mod.build_dependency_report(
            args,
            cfg,
            which=_which_from({"cd-discid", "readom"}),
            os_release_text="ID=fedora\n",
            textual_available=True,
        )

        self.assertEqual(
            [item.spec.key for item in report.required],
            ["discid_core", "readom"],
        )

    def test_optional_missing_tools_do_not_fail(self) -> None:
        cfg = Config()
        args = _args(no_image=True, no_flac=True, no_mp3=True, wav=True)
        report = deps_mod.build_dependency_report(
            args,
            cfg,
            which=_which_from({"cd-discid", "cdparanoia"}),
            os_release_text="ID=ubuntu\n",
            textual_available=True,
        )

        self.assertEqual(deps_mod.dependency_exit_code(report), 0)
        self.assertTrue(any(not item.available for item in report.optional))

    def test_missing_device_is_reported_as_note_not_failure(self) -> None:
        cfg = Config()
        args = _args(device="/definitely/missing", no_image=True, no_flac=True, no_mp3=True, wav=True)
        report = deps_mod.build_dependency_report(
            args,
            cfg,
            which=_which_from({"cd-discid", "cdparanoia"}),
            os_release_text="ID=ubuntu\n",
            textual_available=True,
        )

        self.assertEqual(deps_mod.dependency_exit_code(report), 0)
        self.assertTrue(any("does not exist" in note.detail for note in report.notes))

    def test_missing_discid_adds_musicbrainz_accuracy_note(self) -> None:
        cfg = Config()
        args = _args(no_image=True, no_flac=True, no_mp3=True, wav=True)
        with patch("discvault.deps._exact_discid_runtime_available", return_value=False):
            report = deps_mod.build_dependency_report(
                args,
                cfg,
                which=_which_from({"cd-discid", "cdparanoia"}),
                os_release_text="ID=ubuntu\n",
                textual_available=True,
            )

        self.assertTrue(any("install discid" in note.detail for note in report.notes))

    def test_libdiscid_runtime_suppresses_musicbrainz_accuracy_note(self) -> None:
        cfg = Config()
        args = _args(no_image=True, no_flac=True, no_mp3=True, wav=True)
        with patch("discvault.deps._exact_discid_runtime_available", return_value=True):
            report = deps_mod.build_dependency_report(
                args,
                cfg,
                which=_which_from({"cd-discid", "cdparanoia"}),
                os_release_text="ID=ubuntu\n",
                textual_available=True,
            )

        self.assertFalse(any("MusicBrainz accuracy" == note.label for note in report.notes))

    def test_readable_device_path_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            device = Path(tmp) / "cdrom"
            device.write_text("x")
            cfg = Config()
            args = _args(device=str(device), no_image=True, no_flac=True, no_mp3=True, wav=True)
            report = deps_mod.build_dependency_report(
                args,
                cfg,
                which=_which_from({"cd-discid", "cdparanoia"}),
                os_release_text="ID=ubuntu\n",
                textual_available=True,
            )

        self.assertTrue(any("is readable" in note.detail for note in report.notes))


class DistroDetectionTests(unittest.TestCase):
    def test_detect_package_manager_supports_common_linux_families(self) -> None:
        self.assertEqual(deps_mod.detect_package_manager("ID=ubuntu\nID_LIKE=debian\n"), "apt")
        self.assertEqual(deps_mod.detect_package_manager("ID=arch\n"), "pacman")
        self.assertEqual(deps_mod.detect_package_manager("ID=rocky\nID_LIKE=rhel fedora\n"), "dnf")
        self.assertIsNone(deps_mod.detect_package_manager("ID=gentoo\n"))

    def test_recommended_install_packages_are_deduplicated(self) -> None:
        self.assertEqual(
            deps_mod.recommended_install_packages("apt", ("flac", "lame", "flac")),
            ("flac", "lame"),
        )


if __name__ == "__main__":
    unittest.main()
