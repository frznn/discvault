"""Command-line interface and main orchestrator."""
from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from .cleanup import Cleanup
from .config import Config
from .ui.console import console, log, success, warn, error, step


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    cfg = Config.load()

    # CLI overrides
    if args.base_dir:
        cfg.base_dir = args.base_dir
    if args.work_dir:
        cfg.work_dir = args.work_dir
    if args.cdrdao_driver:
        cfg.cdrdao_driver = args.cdrdao_driver
    if args.keep_wav:
        cfg.keep_wav = True
    if args.eject:
        cfg.eject_after = True

    _run(args, cfg)


def _run(args: argparse.Namespace, cfg: Config) -> None:
    from . import device as dev_mod
    from . import disc as disc_mod
    from . import library
    from .metadata.sanitize import sanitize_component
    from . import rip as rip_mod
    from . import encode as enc_mod
    from .metadata import lookup as meta_lookup
    from .ui.selector import select_candidate

    cleanup = Cleanup()

    def _abort(signum=None, frame=None):
        error("Interrupted — cleaning up...")
        cleanup.remove_all()
        sys.exit(130)

    signal.signal(signal.SIGINT, _abort)
    signal.signal(signal.SIGTERM, _abort)

    # ------------------------------------------------------------------
    # 1. Device
    # ------------------------------------------------------------------
    step("Detecting CD device")
    device = args.device or dev_mod.detect()
    if not device:
        error("No CD device found. Use --device to specify one.")
        sys.exit(1)
    if not dev_mod.is_readable(device):
        error(f"Device {device} is not readable or has no disc.")
        sys.exit(1)
    log(f"Using device: {device}")

    # ------------------------------------------------------------------
    # 2. Disc info
    # ------------------------------------------------------------------
    step("Reading disc TOC")
    try:
        disc_info = disc_mod.load_disc_info(device)
    except Exception as exc:
        error(f"Failed to read disc info: {exc}")
        sys.exit(1)
    disc_info.device = device
    log(f"Tracks: {disc_info.track_count}  |  FreeDB ID: {disc_info.freedb_disc_id or '(none)'}  |  MB ID: {disc_info.mb_disc_id or '(none)'}")

    # ------------------------------------------------------------------
    # 3. Metadata
    # ------------------------------------------------------------------
    step("Fetching metadata")
    candidates = meta_lookup.fetch_candidates(disc_info, cfg, debug=args.debug)

    if not candidates:
        warn("No metadata found.")

    meta = None
    if candidates and sys.stdin.isatty():
        meta = select_candidate(candidates, tui=args.tui)
    elif candidates:
        meta = candidates[0]
        log(f"Auto-selected: {meta.album_artist} — {meta.album}")

    if meta is None:
        if args.skip_metadata:
            warn("Proceeding without metadata.")
        else:
            warn("No metadata selected. Use --skip-metadata to proceed without it.")
            sys.exit(0)

    # ------------------------------------------------------------------
    # 4. Paths
    # ------------------------------------------------------------------
    artist = meta.album_artist if meta else "Unknown Artist"
    album = meta.album if meta else "Unknown Album"
    year = meta.year if meta else ""

    album_root = library.album_root(cfg.base_dir, artist, album, year)
    log(f"Album folder: {album_root}")

    if album_root.exists():
        if sys.stdin.isatty():
            warn(f"Album folder already exists — files may be overwritten:")
            console.print(f"  {album_root}")
            try:
                answer = console.input("  Continue? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer not in ("y", "yes"):
                log("Aborted.")
                sys.exit(0)
        else:
            warn(f"Album folder already exists (may be overwritten): {album_root}")

    # ------------------------------------------------------------------
    # 5. Work directory
    # ------------------------------------------------------------------
    work_dir = Path(cfg.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    cleanup.track_dir(work_dir)

    # ------------------------------------------------------------------
    # 6. Disc image (optional)
    # ------------------------------------------------------------------
    if args.image:
        step("Creating disc image")
        stem = library.image_stem(artist, album, year)
        image_dir = Path(cfg.base_dir) / sanitize_component(artist)
        image_dir.mkdir(parents=True, exist_ok=True)
        stem = library.unique_image_stem(image_dir, stem)
        toc_path = image_dir / f"{stem}.toc"
        bin_path = image_dir / f"{stem}.bin"

        ok = rip_mod.rip_image(
            device, toc_path, bin_path, cleanup,
            driver=cfg.cdrdao_driver, debug=args.debug,
        )
        if not ok:
            cleanup.remove_all()
            sys.exit(1)

    # ------------------------------------------------------------------
    # 7. Rip audio
    # ------------------------------------------------------------------
    step("Ripping audio tracks")
    wav_files = rip_mod.rip_audio(
        device, work_dir, disc_info.track_count, cleanup, debug=args.debug
    )
    if wav_files is None:
        cleanup.remove_all()
        sys.exit(1)

    # ------------------------------------------------------------------
    # 8. Encode
    # ------------------------------------------------------------------
    if not meta:
        warn("No metadata — files will have minimal tags.")
        from .metadata.types import Metadata
        meta = Metadata(source="none", album_artist=artist, album=album, year=year)

    flac = not args.no_flac
    mp3 = args.mp3

    if flac or mp3:
        step("Encoding")
        album_root.mkdir(parents=True, exist_ok=True)
        cleanup.track_dir(album_root)

        ok = enc_mod.encode_tracks(
            wav_files,
            album_root,
            meta,
            flac=flac,
            mp3=mp3,
            flac_compression=args.flac_compression,
            mp3_quality=args.mp3_quality,
            mp3_bitrate=args.mp3_bitrate,
            cleanup=cleanup,
            debug=args.debug,
        )
        if not ok:
            cleanup.remove_all()
            sys.exit(1)
    else:
        warn("Both FLAC and MP3 disabled — nothing encoded.")

    # ------------------------------------------------------------------
    # 9. Cleanup WAVs
    # ------------------------------------------------------------------
    if not cfg.keep_wav:
        for w in wav_files:
            w.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 10. Eject
    # ------------------------------------------------------------------
    if cfg.eject_after:
        subprocess.run(["eject", device], capture_output=True)

    cleanup.clear()
    success(f"Done! Files saved to: {album_root}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discvault",
        description="Rip and archive CDs to FLAC/MP3 with metadata.",
    )

    p.add_argument("-d", "--device", metavar="DEV",
                   help="CD device (default: auto-detect)")
    p.add_argument("-o", "--base-dir", metavar="DIR",
                   help="Library base directory (overrides config)")
    p.add_argument("--work-dir", metavar="DIR",
                   help="Temporary work directory (overrides config)")

    # Metadata
    p.add_argument("--skip-metadata", action="store_true",
                   help="Proceed without metadata")
    p.add_argument("--tui", action="store_true",
                   help="Use Textual TUI for metadata selection (requires textual)")

    # Encoding
    enc = p.add_argument_group("encoding")
    enc.add_argument("--no-flac", action="store_true",
                     help="Skip FLAC encoding")
    enc.add_argument("--mp3", action="store_true",
                     help="Also encode MP3")
    enc.add_argument("--flac-compression", type=int, default=8, metavar="N",
                     help="FLAC compression level 0–8 (default: 8)")
    enc.add_argument("--mp3-quality", type=int, default=2, metavar="N",
                     help="lame -V quality 0–9 (default: 2, VBR)")
    enc.add_argument("--mp3-bitrate", type=int, default=0, metavar="KBPS",
                     help="lame CBR bitrate (0 = use VBR quality)")

    # Image
    img = p.add_argument_group("disc image")
    img.add_argument("--image", action="store_true",
                     help="Also rip a full disc image (cdrdao)")
    img.add_argument("--cdrdao-driver", metavar="DRV",
                     help="cdrdao driver override")

    # Misc
    p.add_argument("--keep-wav", action="store_true",
                   help="Keep intermediate WAV files")
    p.add_argument("--eject", action="store_true",
                   help="Eject disc when done")
    p.add_argument("--debug", action="store_true",
                   help="Print debug information")
    p.add_argument("--version", action="version", version="discvault 0.1.0")

    return p.parse_args()
