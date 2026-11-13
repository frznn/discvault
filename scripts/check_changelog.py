#!/usr/bin/env python3
"""Fail when a commit range changes the package without touching CHANGELOG.md.

Purpose: RULES "Releases" 2 requires a line under [Unreleased] for every user-visible
change, and a rule nobody checks gets skipped. This is the mechanical check.

Usage: check_changelog.py [<range>]      (default: origin/master..HEAD)

A commit counts as user-visible when it touches a path under `discvault/` other than
`discvault/__init__.py` (a version bump belongs to a release, which rewrites the
changelog itself). A commit whose message carries a `Changelog: none` trailer is waived
(refactors, internal fixes). The check is over the whole range, not per commit, because
a branch's fixups are amended into their commit and the final shape is what lands: it
fails only if some unwaived user-visible commit exists and the range's combined diff
leaves CHANGELOG.md untouched.
"""
from __future__ import annotations

import re
import subprocess
import sys

CHANGELOG = "CHANGELOG.md"
PACKAGE_PREFIX = "discvault/"
VERSION_FILE = "discvault/__init__.py"
WAIVER = re.compile(r"^Changelog:\s*none\s*$", re.IGNORECASE | re.MULTILINE)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def is_user_visible(paths: list[str]) -> bool:
    return any(p.startswith(PACKAGE_PREFIX) and p != VERSION_FILE for p in paths)


def offending_commits(rev_range: str) -> tuple[list[str], bool]:
    """Return (unwaived user-visible commits as 'sha subject', changelog touched)."""
    touched = CHANGELOG in _git("diff", "--name-only", rev_range).split("\n")
    offenders: list[str] = []
    for sha in _git("rev-list", "--no-merges", "--reverse", rev_range).split():
        paths = _git("show", "--name-only", "--format=", sha).split()
        message = _git("show", "-s", "--format=%B", sha)
        if is_user_visible(paths) and not WAIVER.search(message):
            offenders.append(f"{sha[:7]} {message.splitlines()[0]}")
    return offenders, touched


def main(argv: list[str]) -> int:
    rev_range = argv[1] if len(argv) > 1 else "origin/master..HEAD"
    try:
        offenders, touched = offending_commits(rev_range)
    except subprocess.CalledProcessError as exc:
        print(f"check_changelog: cannot read range {rev_range!r}: {exc.stderr.strip()}",
              file=sys.stderr)
        return 2
    if not offenders or touched:
        return 0
    print(f"{CHANGELOG} is untouched but these commits change the package:",
          file=sys.stderr)
    for line in offenders:
        print(f"  {line}", file=sys.stderr)
    print("Add a line under [Unreleased], or add a `Changelog: none` trailer to a commit "
          "that is not user-visible.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
