#!/usr/bin/env python3
"""Manual real-drive smoke test for DiscVault.

This script exercises the same high-value manual checks used during
stabilization:

1. Dry-run metadata and disc detection
2. Real subset FLAC rip with tag verification
3. Optional image-only readom pass
4. Image-only cdrdao pass with no-eject verification

The script is intentionally conservative:
- it uses isolated HOME directories so the user's real config is untouched
- it writes only under a dedicated output root
- it disables auto-eject in the temporary configs
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


TRACK_COUNT_RE = re.compile(r"Tracks:\s+(\d+)\s+\|")
SUMMARY_RE = re.compile(r"^([A-Za-z /]+):\s*(.+)$", re.MULTILINE)


class SmokeError(RuntimeError):
    """Raised when the smoke test finds an unexpected failure."""


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    require_tools("cdrdao", "cdparanoia", "flac", "metaflac")
    if not args.skip_readom:
        require_tools("readom")

    device = args.device or detect_device()
    if device is None:
        raise SmokeError("No optical drive device found. Pass --device explicitly.")

    print(f"== DiscVault real-drive smoke test ==")
    print(f"Device:      {device}")
    print(f"Repo root:   {repo_root}")
    print(f"Output root: {output_root}")
    print()

    dry_run_root = output_root / "dry-run"
    reset_scenario_root(dry_run_root)
    dry_run_output = run_discvault(
        repo_root,
        home_dir=dry_run_root / "home",
        device=device,
        base_dir=dry_run_root / "library",
        work_dir=dry_run_root / "work",
        extra_args=["--dry-run", "--no-cover-art"],
        image_ripper="cdrdao",
    )
    track_count = parse_track_count(dry_run_output)
    subset_tracks = choose_subset_tracks(track_count)
    print(f"[ok] dry-run succeeded; detected {track_count} track(s)")
    print(f"[ok] subset test will use tracks {','.join(str(track) for track in subset_tracks)}")
    print()

    subset_root = output_root / "subset"
    reset_scenario_root(subset_root)
    subset_output = run_discvault(
        repo_root,
        home_dir=subset_root / "home",
        device=device,
        base_dir=subset_root / "library",
        work_dir=subset_root / "work",
        extra_args=[
            "--tracks",
            ",".join(str(track) for track in subset_tracks),
            "--no-image",
            "--no-mp3",
            "--no-cover-art",
        ],
        image_ripper="cdrdao",
    )
    subset_album = find_album_root(subset_root / "library")
    verify_subset_run(subset_album, subset_tracks, track_count)
    print(f"[ok] subset FLAC run verified in {subset_album}")
    print()

    if not args.skip_readom:
        readom_root = output_root / "readom"
        reset_scenario_root(readom_root)
        try:
            run_discvault(
                repo_root,
                home_dir=readom_root / "home",
                device=device,
                base_dir=readom_root / "library",
                work_dir=readom_root / "work",
                extra_args=["--no-flac", "--no-mp3", "--no-cover-art"],
                image_ripper="readom",
            )
        except SmokeError as exc:
            if args.require_readom_success:
                raise
            verify_readom_cleanup(readom_root / "library")
            print(f"[warn] readom did not succeed on this disc/drive: {exc}")
            print("[ok] readom cleanup verified")
        else:
            readom_album = find_album_root(readom_root / "library")
            verify_image_run(readom_album, expect_toc=False)
            print(f"[ok] readom image-only run verified in {readom_album}")
        print()

    cdrdao_root = output_root / "cdrdao"
    reset_scenario_root(cdrdao_root)
    run_discvault(
        repo_root,
        home_dir=cdrdao_root / "home",
        device=device,
        base_dir=cdrdao_root / "library",
        work_dir=cdrdao_root / "work",
        extra_args=["--no-flac", "--no-mp3", "--no-cover-art"],
        image_ripper="cdrdao",
    )
    cdrdao_album = find_album_root(cdrdao_root / "library")
    verify_image_run(cdrdao_album, expect_toc=True)
    verify_disc_still_present(device)
    print(f"[ok] cdrdao image-only run verified in {cdrdao_album}")
    print(f"[ok] no-eject behavior verified on {device}")
    print()

    print("Smoke test completed successfully.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device",
        default="",
        help="optical drive path (defaults to /dev/cdrom or /dev/sr0 when present)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/tmp/discvault-smoke-script"),
        help="directory where temporary configs and test output trees will be written",
    )
    parser.add_argument(
        "--skip-readom",
        action="store_true",
        help="skip the optional readom image smoke test",
    )
    parser.add_argument(
        "--require-readom-success",
        action="store_true",
        help="treat readom failure as fatal instead of reporting it as compatibility data",
    )
    return parser.parse_args()


def require_tools(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise SmokeError(f"Missing required tool(s): {', '.join(missing)}")


def detect_device() -> str | None:
    for candidate in ("/dev/cdrom", "/dev/sr0"):
        if Path(candidate).exists():
            return candidate
    return None


def reset_scenario_root(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def run_discvault(
    repo_root: Path,
    *,
    home_dir: Path,
    device: str,
    base_dir: Path,
    work_dir: Path,
    extra_args: list[str],
    image_ripper: str,
) -> str:
    write_temp_config(home_dir, image_ripper=image_ripper)
    command = [
        sys.executable,
        "-m",
        "discvault",
        "--cli",
        "--device",
        device,
        "--base-dir",
        str(base_dir),
        "--work-dir",
        str(work_dir),
        *extra_args,
    ]
    return run(command, cwd=repo_root, env={**os.environ, "HOME": str(home_dir)})


def write_temp_config(home_dir: Path, *, image_ripper: str) -> None:
    config_dir = home_dir / ".config" / "discvault"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"
    config_path.write_text(
        "\n".join(
            [
                "[discvault]",
                "eject_after = false",
                "download_cover_art = false",
                f'image_ripper = "{image_ripper}"',
                "",
            ]
        ),
        encoding="utf-8",
    )


def run(command: list[str], *, cwd: Path, env: dict[str, str]) -> str:
    print("$", " ".join(command))
    proc = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
        capture_output=True,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise SmokeError(combined.strip() or f"command failed with exit {proc.returncode}")
    return combined


def parse_track_count(output: str) -> int:
    match = TRACK_COUNT_RE.search(output)
    if not match:
        raise SmokeError("Could not parse track count from dry-run output.")
    return int(match.group(1))


def choose_subset_tracks(track_count: int) -> list[int]:
    if track_count >= 3:
        return [1, 3]
    if track_count >= 2:
        return [1, 2]
    if track_count == 1:
        return [1]
    raise SmokeError("Disc reports zero tracks.")


def find_album_root(base_dir: Path) -> Path:
    manifests = sorted(base_dir.rglob("backup-info.txt"))
    if len(manifests) != 1:
        raise SmokeError(f"Expected exactly one backup-info.txt under {base_dir}, found {len(manifests)}")
    return manifests[0].parent


def verify_subset_run(album_root: Path, subset_tracks: list[int], track_count: int) -> None:
    manifest = parse_manifest(album_root / "backup-info.txt")
    selected_spec = ",".join(str(track) for track in subset_tracks)
    if manifest.get("Selected tracks") != selected_spec:
        raise SmokeError(f"Manifest selected tracks mismatch: {manifest.get('Selected tracks')!r}")
    if manifest.get("Audio tracks written") != str(len(subset_tracks)):
        raise SmokeError(f"Manifest audio count mismatch: {manifest.get('Audio tracks written')!r}")
    if manifest.get("Disc image") != "no":
        raise SmokeError("Subset run unexpectedly reports disc image output.")

    flac_dir = album_root / "flac"
    flac_files = sorted(flac_dir.glob("*.flac"))
    if len(flac_files) != len(subset_tracks):
        raise SmokeError(f"Expected {len(subset_tracks)} FLAC files, found {len(flac_files)}")

    seen_tracks: set[int] = set()
    for flac_file in flac_files:
        tags = read_flac_tags(flac_file)
        track_number = int(tags["TRACKNUMBER"])
        track_total = int(tags["TRACKTOTAL"])
        seen_tracks.add(track_number)
        if track_total != track_count:
            raise SmokeError(f"{flac_file.name} has TRACKTOTAL={track_total}, expected {track_count}")
    if seen_tracks != set(subset_tracks):
        raise SmokeError(f"Subset FLAC tags mismatch: saw {sorted(seen_tracks)}, expected {subset_tracks}")


def verify_readom_cleanup(base_dir: Path) -> None:
    leftover_files = sorted(path for path in base_dir.rglob("*") if path.is_file())
    if leftover_files:
        raise SmokeError(f"readom failure left partial files behind: {leftover_files}")


def verify_image_run(album_root: Path, *, expect_toc: bool) -> None:
    manifest = parse_manifest(album_root / "backup-info.txt")
    image_dir = album_root / "image"
    bin_files = sorted(image_dir.glob("*.bin"))
    cue_files = sorted(image_dir.glob("*.cue"))
    toc_files = sorted(image_dir.glob("*.toc"))

    if manifest.get("Disc image") != "yes":
        raise SmokeError("Image run manifest does not report disc image output.")
    if len(bin_files) != 1:
        raise SmokeError(f"Expected exactly one BIN file, found {len(bin_files)}")
    if len(cue_files) != 1:
        raise SmokeError(f"Expected exactly one CUE file, found {len(cue_files)}")
    if expect_toc and len(toc_files) != 1:
        raise SmokeError(f"Expected exactly one TOC file, found {len(toc_files)}")
    if not expect_toc and toc_files:
        raise SmokeError("readom image run should not leave a TOC file behind.")

    if manifest.get("Image BIN") != str(bin_files[0]):
        raise SmokeError("Manifest Image BIN path mismatch.")
    if manifest.get("Image CUE") != str(cue_files[0]):
        raise SmokeError("Manifest Image CUE path mismatch.")
    if expect_toc and manifest.get("Image TOC") != str(toc_files[0]):
        raise SmokeError("Manifest Image TOC path mismatch.")
    if not expect_toc and "Image TOC" in manifest:
        raise SmokeError("Manifest unexpectedly recorded an Image TOC for readom.")

    ensure_nonempty(bin_files[0])
    ensure_nonempty(cue_files[0])
    if expect_toc:
        ensure_nonempty(toc_files[0])


def verify_disc_still_present(device: str) -> None:
    proc = subprocess.run(
        ["cdparanoia", "-d", device, "-Q"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SmokeError("Disc is no longer readable after the no-eject image test.")


def parse_manifest(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    result: dict[str, str] = {}
    for key, value in SUMMARY_RE.findall(text):
        result[key.strip()] = value.strip()
    return result


def read_flac_tags(path: Path) -> dict[str, str]:
    proc = subprocess.run(
        [
            "metaflac",
            "--show-tag=TRACKNUMBER",
            "--show-tag=TRACKTOTAL",
            str(path),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SmokeError(f"metaflac failed for {path}")

    tags: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        tags[key] = value
    if "TRACKNUMBER" not in tags or "TRACKTOTAL" not in tags:
        raise SmokeError(f"Missing FLAC tags in {path}")
    return tags


def ensure_nonempty(path: Path) -> None:
    if not path.exists():
        raise SmokeError(f"Expected file does not exist: {path}")
    if path.stat().st_size <= 0:
        raise SmokeError(f"Expected file is empty: {path}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeError as exc:
        print(f"[fail] {exc}", file=sys.stderr)
        raise SystemExit(1)
