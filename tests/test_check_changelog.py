from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_changelog", Path(__file__).resolve().parents[1] / "scripts" / "check_changelog.py"
)
check_changelog = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(check_changelog)


class RangeCheckTests(unittest.TestCase):
    """Each test builds a throwaway repository: the script reads real git history."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name)
        cwd = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.git("config", "commit.gpgsign", "false")
        self.commit({"CHANGELOG.md": "x\n", "discvault/a.py": "1\n"}, "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], check=True, capture_output=True,
                              text=True).stdout

    def commit(self, files: dict[str, str], message: str) -> None:
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_check(self) -> int:
        return check_changelog.main(["x", f"{self.base}..HEAD"])

    def test_package_change_without_changelog_fails(self) -> None:
        self.commit({"discvault/a.py": "2\n"}, "Fix a")
        self.assertEqual(self.run_check(), 1)

    def test_package_change_with_changelog_passes(self) -> None:
        self.commit({"discvault/a.py": "2\n"}, "Fix a")
        self.commit({"CHANGELOG.md": "y\n"}, "Note it")
        self.assertEqual(self.run_check(), 0)

    def test_waiver_trailer_passes(self) -> None:
        self.commit({"discvault/a.py": "2\n"}, "Refactor a\n\nChangelog: none")
        self.assertEqual(self.run_check(), 0)

    def test_non_package_change_passes(self) -> None:
        self.commit({"tests/t.py": "1\n", "discvault/__init__.py": "v\n"}, "Tests")
        self.assertEqual(self.run_check(), 0)

    def test_bad_range_is_an_error(self) -> None:
        self.assertEqual(check_changelog.main(["x", "nope..HEAD"]), 2)


if __name__ == "__main__":
    unittest.main()
