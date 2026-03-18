"""Command-line interface and main orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import datetime
import signal
import subprocess
import sys
from pathlib import Path

from .cleanup import Cleanup
from .config import Config, first_run_setup
from .tracks import compact_track_list, parse_track_spec, resolve_selected_tracks
from .ui.console import console, log, success, warn, error, step


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    args = _parse_args()
    if args.tracks:
        try:
            parse_track_spec(args.tracks)
        except ValueError:
            error("Invalid --tracks value. Use formats like 1-10 or 1,2,4-9.")
            raise SystemExit(2)
    cfg = Config.load()

    # First-run wizard (only if interactive and no config file yet)
    if not args.dry_run:
        first_run_setup(cfg)

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
    if args.metadata_timeout:
        cfg.metadata_timeout = args.metadata_timeout
    if args.sample_offset is not None:
        cfg.cdparanoia_sample_offset = args.sample_offset
    if args.accuraterip:
        cfg.accuraterip_enabled = True
    if args.no_accuraterip:
        cfg.accuraterip_enabled = False
    if args.no_cover_art:
        cfg.download_cover_art = False
    if args.opus_bitrate:
        cfg.opus_bitrate = args.opus_bitrate
    if args.aac_bitrate:
        cfg.aac_bitrate = args.aac_bitrate

    # Use TUI by default when running interactively, unless --cli is given.
    use_tui = not args.cli and sys.stdin.isatty() and _textual_available()
    if use_tui:
        _run_tui(args, cfg)
    else:
        # Always show where files will go
        log(f"Library: {cfg.base_dir}")
        _run(args, cfg)


def _textual_available() -> bool:
    try:
        import textual  # noqa: F401
        return True
    except ImportError:
        return False


def _run_tui(args: argparse.Namespace, cfg: Config) -> None:
    try:
        from .ui.tui import DiscvaultApp
    except ImportError:
        error("Textual is not installed. Run: pip install discvault[tui]")
        sys.exit(1)
    app = DiscvaultApp(args, cfg)
    # Use run_async() with a plain event loop instead of asyncio.run().
    # asyncio.run() calls shutdown_default_executor() which blocks up to
    # 5 minutes waiting for network/IO threads to finish.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(app.run_async())
    finally:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)
    raise SystemExit(app.return_code or 0)


def _run(args: argparse.Namespace, cfg: Config) -> None:
    from . import alerts
    from . import artwork as artwork_mod
    from . import device as dev_mod
    from . import disc as disc_mod
    from . import library
    from . import rip as rip_mod
    from . import encode as enc_mod
    from . import verify as verify_mod
    from .metadata import lookup as meta_lookup
    from .ui.selector import select_candidate

    cleanup = Cleanup()

    def _abort(signum=None, frame=None):
        error("Interrupted — cleaning up...")
        cleanup.remove_all()
        sys.exit(130)

    signal.signal(signal.SIGINT, _abort)
    signal.signal(signal.SIGTERM, _abort)

    do_image = not args.no_image
    do_iso = args.iso
    do_flac = not args.no_flac
    do_mp3 = not args.no_mp3
    do_ogg = args.ogg
    do_opus = args.opus
    do_alac = args.alac
    do_aac = args.aac
    do_wav = args.wav
    try:
        requested_tracks = parse_track_spec(args.tracks) if args.tracks else None
    except ValueError:
        error("Invalid --tracks value. Use formats like 1-10 or 1,2,4-9.")
        sys.exit(2)
    if do_iso and not do_image:
        warn("ISO export requires the raw disc image. Enabling disc image output.")
        do_image = True

    # ------------------------------------------------------------------
    # 1. Device
    # ------------------------------------------------------------------
    step("Detecting CD device")
    device = args.device or dev_mod.detect()
    if not device:
        error("No CD device found. Use --device to specify one.")
        sys.exit(1)
    if not args.dry_run and not dev_mod.is_readable(device):
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
        if args.dry_run:
            log("Dry-run: disc read skipped.")
            from .metadata.types import DiscInfo
            disc_info = DiscInfo(device=device)
        else:
            error(f"Failed to read disc info: {exc}")
            sys.exit(1)
    disc_info.device = device
    log(
        f"Tracks: {disc_info.track_count}  |  "
        f"FreeDB ID: {disc_info.freedb_disc_id or '(none)'}  |  "
        f"MB ID: {disc_info.mb_disc_id or '(none)'}"
    )
    if disc_info.data_track_numbers:
        warn(
            "Data track(s) detected and excluded by default: "
            f"{compact_track_list(disc_info.data_track_numbers)}"
        )
    selected_tracks = resolve_selected_tracks(disc_info, requested_tracks)
    if not selected_tracks:
        error("No audio tracks remain selected. Adjust --tracks or choose a disc with audio tracks.")
        sys.exit(1)
    if args.tracks:
        log(f"Selected tracks: {compact_track_list(selected_tracks)}")
        omitted_tracks = sorted(set(requested_tracks or []) - set(selected_tracks))
        if omitted_tracks:
            warn(
                "Ignored non-audio or out-of-range tracks: "
                f"{compact_track_list(omitted_tracks)}"
            )

    # ------------------------------------------------------------------
    # 3. Metadata
    # ------------------------------------------------------------------
    step("Fetching metadata")
    meta_debug = args.metadata_debug or args.debug
    candidates = meta_lookup.fetch_candidates(
        disc_info,
        cfg,
        debug=meta_debug,
        metadata_file=args.metadata_file or "",
        metadata_url=getattr(args, "metadata_url", "") or "",
        manual_hints=(args.artist or "", args.album or "", args.year or ""),
    )

    if not candidates:
        warn("No metadata found from any source.")

    # ------------------------------------------------------------------
    # 4. Selection + confirm loop
    # ------------------------------------------------------------------
    back_to_meta = True
    meta = None
    artist = args.artist or ""
    album = args.album or ""
    year = args.year or ""

    while back_to_meta:
        back_to_meta = False

        # --- 4a. Pick a metadata candidate ---
        if candidates and sys.stdin.isatty():
            meta = select_candidate(candidates, disc_info=disc_info, tui=args.tui)
        elif candidates:
            meta = candidates[0]
            log(f"Auto-selected: {meta.album_artist} — {meta.album}")

        if meta is None:
            if not sys.stdin.isatty():
                if args.skip_metadata:
                    warn("Proceeding without metadata.")
                else:
                    warn("No metadata selected. Use --skip-metadata to proceed without it.")
                    sys.exit(0)
            elif not args.skip_metadata and not candidates:
                if args.strict_manual_fallback:
                    try:
                        answer = console.input(
                            "Metadata lookup failed. Continue with manual entry? [y/N] "
                        ).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer not in ("y", "yes"):
                        log("Aborted.")
                        sys.exit(0)
                else:
                    warn("No metadata found. Continuing with manual values.")
                    warn("Tip: run with --metadata-debug to see provider-level failures.")

        # --- 4b. Merge values from meta ---
        if meta:
            if not artist:
                artist = meta.album_artist or ""
            if not album:
                album = meta.album or ""
            if not year:
                year = meta.year or ""

        # Prompt for missing required values
        if sys.stdin.isatty():
            if not artist:
                try:
                    artist = console.input("Artist: ").strip()
                except (EOFError, KeyboardInterrupt):
                    sys.exit(0)
            if not album:
                try:
                    album = console.input("Album: ").strip()
                except (EOFError, KeyboardInterrupt):
                    sys.exit(0)
        else:
            if not artist:
                error("Artist not provided. Use --artist or ensure metadata is available.")
                sys.exit(1)
            if not album:
                error("Album not provided. Use --album or ensure metadata is available.")
                sys.exit(1)

        artist = artist.strip()
        album = album.strip()
        year = year.strip()

        if year and not year.isdigit():
            warn(f"Year '{year}' doesn't look like a 4-digit year; clearing it.")
            year = ""

        # --- 4c. Confirm before starting ---
        if sys.stdin.isatty() and not args.dry_run:
            while True:
                album_root = library.album_root(cfg.base_dir, artist, album, year)
                action, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav = _confirm_before_start(
                    artist, album, year,
                    meta.source if meta else "Manual",
                    album_root,
                    do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
                    args.flac_compression, args.mp3_bitrate, cfg.opus_bitrate, cfg.aac_bitrate,
                )
                if action == "proceed":
                    break
                elif action == "edit":
                    artist, album, year = _edit_tags(artist, album, year)
                    if meta:
                        meta.album_artist = artist
                        meta.album = album
                        meta.year = year
                elif action == "back":
                    back_to_meta = True
                    artist = args.artist or ""
                    album = args.album or ""
                    year = args.year or ""
                    break
        else:
            album_root = library.album_root(cfg.base_dir, artist, album, year)
            if album_root.exists():
                warn(f"Album folder already exists (may be overwritten): {album_root}")

    # ------------------------------------------------------------------
    # 5. Paths
    # ------------------------------------------------------------------
    album_root = library.album_root(cfg.base_dir, artist, album, year)
    img_dir = library.image_dir(album_root)
    fl_dir = library.flac_dir(album_root)
    mp_dir = library.mp3_dir(album_root)
    og_dir = library.ogg_dir(album_root)
    op_dir = library.opus_dir(album_root)
    al_dir = library.alac_dir(album_root)
    aa_dir = library.aac_dir(album_root)
    wa_dir = library.wav_dir(album_root)
    album_root_existed = album_root.exists()

    log(f"Album folder: {album_root}")

    if args.dry_run:
        _dry_run_summary(args, cfg, device, artist, album, year,
                         meta, album_root, img_dir, fl_dir, mp_dir, og_dir, op_dir, al_dir, aa_dir, wa_dir,
                         do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, selected_tracks)
        return

    # ------------------------------------------------------------------
    # 6. Work directory
    # ------------------------------------------------------------------
    work_dir = Path(cfg.work_dir)
    work_dir_existed = work_dir.exists()
    work_dir.mkdir(parents=True, exist_ok=True)
    cleanup.track_dir(work_dir, created=not work_dir_existed)

    # ------------------------------------------------------------------
    # 7. Disc image
    # ------------------------------------------------------------------
    toc_path = cue_path = bin_path = iso_path = None
    if do_image:
        step("Creating disc image")
        stem = library.image_stem(artist, album, year)
        cleanup.track_dir(album_root, created=not album_root_existed)
        img_dir_existed = img_dir.exists()
        img_dir.mkdir(parents=True, exist_ok=True)
        cleanup.track_dir(img_dir, created=not img_dir_existed)
        stem = library.unique_image_stem(img_dir, stem)
        toc_path = img_dir / f"{stem}.toc"
        bin_path = img_dir / f"{stem}.bin"

        ok = rip_mod.rip_image(
            device, toc_path, bin_path, cleanup,
            driver=cfg.cdrdao_driver, debug=args.debug,
        )
        if not ok:
            cleanup.remove_all()
            sys.exit(1)
        cue_path = img_dir / f"{stem}.cue"
        try:
            rip_mod.write_cue_file(cue_path, bin_path, disc_info, toc_path=toc_path, cleanup=cleanup)
            log(f"CUE sidecar saved: {cue_path.name}")
        except OSError as exc:
            error(f"Failed to write CUE sidecar: {exc}")
            cleanup.remove_all()
            sys.exit(1)

        if do_iso:
            step("Exporting ISO data image")
            iso_path = img_dir / f"{stem}.iso"
            exported_iso, detail = rip_mod.export_iso_from_bin(
                iso_path,
                bin_path,
                disc_info,
                toc_path=toc_path,
                cleanup=cleanup,
            )
            if exported_iso is not None:
                iso_path = exported_iso
                log(f"ISO saved: {iso_path.name}")
            else:
                iso_path = None
                warn(detail)

    # ------------------------------------------------------------------
    # 8. Rip audio
    # ------------------------------------------------------------------
    wav_files: list[Path] = []
    if do_flac or do_mp3 or do_ogg or do_opus or do_alac or do_aac or do_wav:
        step("Ripping audio tracks")
        wav_files = rip_mod.rip_audio(
            device,
            work_dir,
            disc_info.track_count,
            cleanup,
            debug=args.debug,
            selected_tracks=selected_tracks,
            sample_offset=cfg.cdparanoia_sample_offset,
        )
        if wav_files is None:
            cleanup.remove_all()
            sys.exit(1)

        if cfg.accuraterip_enabled:
            step("AccurateRip verification")
            if cfg.cdparanoia_sample_offset == 0:
                warn(
                    "AccurateRip is enabled with sample offset 0. "
                    "Verification is more meaningful when your drive offset is configured."
                )
            verified, detail = verify_mod.verify_accuraterip(wav_files, debug=args.debug)
            if verified is True:
                success(detail)
            elif verified is False:
                warn(detail)
            else:
                warn(detail)

    # ------------------------------------------------------------------
    # 9. Build Metadata object for encoding
    # ------------------------------------------------------------------
    if not meta:
        from .metadata.types import Metadata as MetaType
        meta = MetaType(source="Manual", album_artist=artist, album=album, year=year)
    else:
        meta.album_artist = artist
        meta.album = album
        meta.year = year

    # ------------------------------------------------------------------
    # 10. Encode
    # ------------------------------------------------------------------
    if do_flac or do_mp3 or do_ogg or do_opus or do_alac or do_aac or do_wav:
        step("Encoding")
        cleanup.track_dir(album_root, created=not album_root_existed)
        if do_flac:
            fl_dir_existed = fl_dir.exists()
            fl_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(fl_dir, created=not fl_dir_existed)
        if do_mp3:
            mp_dir_existed = mp_dir.exists()
            mp_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(mp_dir, created=not mp_dir_existed)
        if do_ogg:
            og_dir_existed = og_dir.exists()
            og_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(og_dir, created=not og_dir_existed)
        if do_opus:
            op_dir_existed = op_dir.exists()
            op_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(op_dir, created=not op_dir_existed)
        if do_alac:
            al_dir_existed = al_dir.exists()
            al_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(al_dir, created=not al_dir_existed)
        if do_aac:
            aa_dir_existed = aa_dir.exists()
            aa_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(aa_dir, created=not aa_dir_existed)
        if do_wav:
            wa_dir_existed = wa_dir.exists()
            wa_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(wa_dir, created=not wa_dir_existed)

        ok = enc_mod.encode_tracks(
            wav_files,
            meta,
            flac_dir=fl_dir if do_flac else None,
            mp3_dir=mp_dir if do_mp3 else None,
            ogg_dir=og_dir if do_ogg else None,
            opus_dir=op_dir if do_opus else None,
            alac_dir=al_dir if do_alac else None,
            aac_dir=aa_dir if do_aac else None,
            wav_dir=wa_dir if do_wav else None,
            flac_compression=args.flac_compression,
            flac_verify=not args.no_verify,
            mp3_quality=args.mp3_quality,
            mp3_bitrate=args.mp3_bitrate,
            opus_bitrate=cfg.opus_bitrate,
            aac_bitrate=cfg.aac_bitrate,
            cleanup=cleanup,
            debug=args.debug,
            track_total_hint=max(selected_tracks) if selected_tracks else None,
        )
        if not ok:
            cleanup.remove_all()
            sys.exit(1)
    else:
        log("Audio encoding disabled — disc image only.")

    cover_art_path = None
    if cfg.download_cover_art:
        log(f"Cover art: {artwork_mod.describe_cover_art(meta, enabled=True)}")
        cover_art_path = artwork_mod.download_cover_art(
            meta,
            album_root,
            cleanup=cleanup,
            timeout=cfg.metadata_timeout,
            debug=args.debug,
        )
        if cover_art_path:
            log(f"Cover art saved: {cover_art_path.name}")
        else:
            warn("Cover art not downloaded.")

    # ------------------------------------------------------------------
    # 11. backup-info.txt
    # ------------------------------------------------------------------
    _write_backup_info(
        album_root, device, artist, album, year, meta.source,
        wav_files, toc_path, cue_path, bin_path, iso_path,
        do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, args, cfg, cleanup,
        selected_tracks,
        accuraterip_enabled=cfg.accuraterip_enabled,
        cover_art_path=cover_art_path,
    )

    # ------------------------------------------------------------------
    # 12. Cleanup WAVs
    # ------------------------------------------------------------------
    if not cfg.keep_wav:
        for w in wav_files:
            w.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    # ------------------------------------------------------------------
    # 13. Eject
    # ------------------------------------------------------------------
    if cfg.eject_after:
        subprocess.run(["eject", device], capture_output=True)

    cleanup.clear()
    sound_ok = alerts.play_completion_sound(cfg.completion_sound)
    notify_ok = alerts.send_desktop_notification(
        "DiscVault rip complete",
        f"{artist} — {album}",
    )
    if cfg.completion_sound != "off" and not sound_ok:
        warn("Completion sound unavailable.")
    if not notify_ok:
        warn("Desktop notifications unavailable.")
    success(f"Done! Files saved to: {album_root}")


# ---------------------------------------------------------------------------
# Confirm / edit helpers
# ---------------------------------------------------------------------------

def _confirm_before_start(
    artist: str,
    album: str,
    year: str,
    meta_source: str,
    album_root: Path,
    do_image: bool,
    do_iso: bool,
    do_flac: bool,
    do_mp3: bool,
    do_ogg: bool,
    do_opus: bool,
    do_alac: bool,
    do_aac: bool,
    do_wav: bool,
    flac_compression: int,
    mp3_bitrate: int,
    opus_bitrate: int,
    aac_bitrate: int,
) -> tuple[str, bool, bool, bool, bool, bool, bool, bool, bool, bool]:
    """
    Show a pre-rip summary with toggleable outputs.
    Returns (action, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav).
    action is one of: 'proceed', 'edit', 'back'.
    """
    while True:
        def _check(val: bool) -> str:
            return "[bold green]x[/bold green]" if val else " "

        console.print("\n[bold]Ready to start backup:[/bold]")
        console.print(f"  Artist:          {artist}")
        console.print(f"  Album:           {album}")
        if year:
            console.print(f"  Year:            {year}")
        console.print(f"  Metadata source: {meta_source}")
        console.print(f"  Target folder:   {album_root}")
        if album_root.exists():
            warn("  Warning: this folder already exists — existing files may be overwritten.")
        console.print("\n  Outputs (1-9 to toggle):")
        console.print(f"    [{_check(do_image)}] 1. Disc image  (cdrdao)")
        console.print(f"    [{_check(do_iso)}] 2. ISO data     (derived when disc has one data track)")
        console.print(f"    [{_check(do_flac)}] 3. FLAC        (level {flac_compression}, verify)")
        mp3_desc = f"{mp3_bitrate} kbps CBR" if mp3_bitrate > 0 else "VBR"
        console.print(f"    [{_check(do_mp3)}] 4. MP3         ({mp3_desc})")
        console.print(f"    [{_check(do_ogg)}] 5. OGG Vorbis  (q6)")
        console.print(f"    [{_check(do_opus)}] 6. Opus        ({opus_bitrate} kbps)")
        console.print(f"    [{_check(do_alac)}] 7. ALAC        (m4a)")
        console.print(f"    [{_check(do_aac)}] 8. AAC/M4A     ({aac_bitrate} kbps)")
        console.print(f"    [{_check(do_wav)}] 9. WAV copy")

        try:
            answer = console.input(
                "\nProceed? [Y=yes, 1-9=toggle output, e=edit tags, b=back, q=quit]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if answer in ("", "y", "yes"):
            if do_iso and not do_image:
                warn("ISO export requires disc image output.")
                continue
            if not any((do_image, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav)):
                warn("Nothing to do — enable at least one output.")
                continue
            return "proceed", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav
        elif answer == "1":
            do_image = not do_image
        elif answer == "2":
            do_iso = not do_iso
        elif answer == "3":
            do_flac = not do_flac
        elif answer == "4":
            do_mp3 = not do_mp3
        elif answer == "5":
            do_ogg = not do_ogg
        elif answer == "6":
            do_opus = not do_opus
        elif answer == "7":
            do_alac = not do_alac
        elif answer == "8":
            do_aac = not do_aac
        elif answer == "9":
            do_wav = not do_wav
        elif answer in ("e", "edit"):
            return "edit", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav
        elif answer in ("b", "back"):
            return "back", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav
        elif answer in ("q", "quit"):
            log("Aborted.")
            sys.exit(0)
        else:
            console.print("[warning]Please enter Y, 1-9, e, b, or q.[/warning]")


def _edit_tags(artist: str, album: str, year: str) -> tuple[str, str, str]:
    console.print("\n[bold]Edit tags[/bold] (press Enter to keep current value):")
    try:
        new = console.input(f"  Artist [{artist}]: ").strip()
        if new:
            artist = new
        new = console.input(f"  Album  [{album}]: ").strip()
        if new:
            album = new
        new = console.input(f"  Year   [{year or '(none)'}]: ").strip()
        if new:
            year = new
    except (EOFError, KeyboardInterrupt):
        pass
    return artist, album, year


# ---------------------------------------------------------------------------
# Dry-run summary
# ---------------------------------------------------------------------------

def _dry_run_summary(
    args, cfg, device, artist, album, year, meta, album_root,
    img_dir, fl_dir, mp_dir, og_dir, op_dir, al_dir, aa_dir, wa_dir,
    do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
    selected_tracks,
) -> None:
    console.print("\n[bold yellow]Dry-run mode — no disc access or files written.[/bold yellow]")
    console.print(f"  Device:      {device}")
    console.print(f"  Artist:      {artist}")
    console.print(f"  Album:       {album}")
    if year:
        console.print(f"  Year:        {year}")
    console.print(f"  Meta source: {meta.source if meta else 'Manual'}")
    console.print(f"  Tracks:      {compact_track_list(selected_tracks)}")
    console.print(f"  Album root:  {album_root}")
    if do_image:
        console.print(f"  Image dir:   {img_dir}")
    if do_iso:
        console.print("  ISO export:  yes (when the disc has a supported data track)")
    if do_flac:
        console.print(f"  FLAC dir:    {fl_dir}")
    if do_mp3:
        console.print(f"  MP3 dir:     {mp_dir}")
    if do_ogg:
        console.print(f"  OGG dir:     {og_dir}")
    if do_opus:
        console.print(f"  Opus dir:    {op_dir}")
    if do_alac:
        console.print(f"  ALAC dir:    {al_dir}")
    if do_aac:
        console.print(f"  AAC dir:     {aa_dir}")
    if do_wav:
        console.print(f"  WAV dir:     {wa_dir}")
    console.print(f"  Work dir:    {cfg.work_dir}")
    console.print(f"  Sample off:  {cfg.cdparanoia_sample_offset}")
    console.print(f"  AccurateRip: {'yes' if cfg.accuraterip_enabled else 'no'}")
    console.print(f"  Cover art:   {'yes' if cfg.download_cover_art else 'no'}")
    console.print("\nDry-run: would execute the selected rip stages and write backup-info.txt")


# ---------------------------------------------------------------------------
# backup-info.txt
# ---------------------------------------------------------------------------

def _write_backup_info(
    album_root: Path,
    device: str,
    artist: str,
    album: str,
    year: str,
    meta_source: str,
    wav_files: list[Path],
    toc_path,
    cue_path,
    bin_path,
    iso_path,
    do_image: bool,
    do_iso: bool,
    do_flac: bool,
    do_mp3: bool,
    do_ogg: bool,
    do_opus: bool,
    do_alac: bool,
    do_aac: bool,
    do_wav: bool,
    args,
    cfg,
    cleanup: Cleanup,
    selected_tracks: list[int],
    *,
    accuraterip_enabled: bool,
    cover_art_path: Path | None,
) -> None:
    info_path = album_root / "backup-info.txt"
    cleanup.track_file(info_path)
    lines = [
        f"Backup timestamp: {datetime.datetime.now().astimezone().isoformat()}",
        f"Device: {device}",
        f"Artist: {artist}",
        f"Album: {album}",
    ]
    if year:
        lines.append(f"Year: {year}")
    lines.append(f"Metadata source: {meta_source}")
    lines.append(f"Track count: {len(wav_files) or len(selected_tracks)}")
    lines.append(f"Selected tracks: {compact_track_list(selected_tracks)}")
    if do_image and toc_path:
        lines.append(f"Image TOC: {toc_path}")
        lines.append(f"Image CUE: {cue_path}")
        lines.append(f"Image BIN: {bin_path}")
    lines.append(f"ISO export: {'yes' if do_iso else 'no'}")
    if iso_path is not None:
        lines.append(f"Image ISO: {iso_path}")
    lines.append(f"FLAC: {'yes' if do_flac else 'no'}")
    lines.append(f"MP3: {'yes' if do_mp3 else 'no'}")
    lines.append(f"OGG: {'yes' if do_ogg else 'no'}")
    lines.append(f"Opus: {'yes' if do_opus else 'no'}")
    lines.append(f"ALAC: {'yes' if do_alac else 'no'}")
    lines.append(f"AAC/M4A: {'yes' if do_aac else 'no'}")
    lines.append(f"WAV copy: {'yes' if do_wav else 'no'}")
    lines.append(f"AccurateRip: {'yes' if accuraterip_enabled else 'no'}")
    lines.append(f"Sample offset: {cfg.cdparanoia_sample_offset}")
    lines.append(f"Cover art enabled: {'yes' if cfg.download_cover_art else 'no'}")
    if cover_art_path is not None:
        lines.append(f"Cover art: {cover_art_path}")
    try:
        info_path.write_text("\n".join(lines) + "\n")
    except OSError as exc:
        warn(f"Could not write backup-info.txt: {exc}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="discvault",
        description="Rip and archive CDs to FLAC/MP3 with full disc image.",
    )

    p.add_argument("-d", "--device", metavar="DEV",
                   help="CD device (default: auto-detect)")
    p.add_argument("-o", "--base-dir", metavar="DIR",
                   help="Library base directory (overrides config)")
    p.add_argument("--work-dir", metavar="DIR",
                   help="Temporary work directory (overrides config)")
    p.add_argument("--tracks", metavar="SPEC",
                   help="Track selection, e.g. 1-10 or 1,2,4-9")
    p.add_argument("--metadata-file", metavar="FILE",
                   help="Import metadata from a .cue, .toc, .json, or .toml file")
    p.add_argument("--metadata-url", "--bandcamp-url", dest="metadata_url", metavar="URL",
                   help="Import metadata from a supported page URL (currently Bandcamp albums)")

    # Manual metadata override
    p.add_argument("--artist", metavar="NAME",
                   help="Artist name (overrides metadata lookup)")
    p.add_argument("--album", metavar="NAME",
                   help="Album name (overrides metadata lookup)")
    p.add_argument("--year", metavar="YYYY",
                   help="Album year (overrides metadata lookup)")

    # Metadata
    p.add_argument("--skip-metadata", action="store_true",
                   help="Proceed without metadata lookup")
    p.add_argument("--strict-manual-fallback", action="store_true",
                   help="Confirm before falling back to manual entry when lookup fails")
    p.add_argument("--metadata-timeout", type=int, metavar="SEC",
                   help="Metadata lookup timeout in seconds (overrides config)")
    p.add_argument("--metadata-debug", action="store_true",
                   help="Print metadata provider debug output")
    p.add_argument("--cli", action="store_true",
                   help="Force plain text CLI (default: TUI when interactive)")
    # kept for backward compat
    p.add_argument("--tui", action="store_true", help=argparse.SUPPRESS)

    # Encoding (on by default, use --no-X to disable)
    enc = p.add_argument_group("encoding")
    enc.add_argument("--no-flac", action="store_true",
                     help="Skip FLAC encoding")
    enc.add_argument("--no-mp3", action="store_true",
                     help="Skip MP3 encoding")
    enc.add_argument("--ogg", action="store_true",
                     help="Enable OGG Vorbis encoding (requires oggenc)")
    enc.add_argument("--opus", action="store_true",
                     help="Enable Opus encoding (requires opusenc)")
    enc.add_argument("--alac", action="store_true",
                     help="Enable ALAC encoding (requires ffmpeg)")
    enc.add_argument("--aac", action="store_true",
                     help="Enable AAC/M4A encoding (requires ffmpeg)")
    enc.add_argument("--wav", action="store_true",
                     help="Save final WAV copies in the library")
    enc.add_argument("--no-verify", action="store_true",
                     help="Skip FLAC --verify (faster but no integrity check)")
    enc.add_argument("--flac-compression", type=int, default=8, metavar="N",
                     help="FLAC compression level 0–8 (default: 8)")
    enc.add_argument("--mp3-quality", type=int, default=2, metavar="N",
                     help="lame -V quality for VBR 0–9 (used when --mp3-bitrate=0)")
    enc.add_argument("--mp3-bitrate", type=int, default=320, metavar="KBPS",
                     help="lame CBR bitrate (default: 320; set 0 for VBR)")
    enc.add_argument("--opus-bitrate", type=int, metavar="KBPS",
                     help="Opus bitrate in kbps (default: config value)")
    enc.add_argument("--aac-bitrate", type=int, metavar="KBPS",
                     help="AAC bitrate in kbps (default: config value)")

    # Image (on by default)
    img = p.add_argument_group("disc image")
    img.add_argument("--no-image", action="store_true",
                     help="Skip full disc image (cdrdao)")
    img.add_argument("--iso", action="store_true",
                     help="Also export an ISO when the disc has a supported data track")
    img.add_argument("--cdrdao-driver", metavar="DRV",
                     help="cdrdao driver override")
    img.add_argument("--sample-offset", type=int, metavar="SAMPLES",
                     help="cdparanoia sample offset correction (overrides config)")

    verify_group = p.add_argument_group("verification")
    verify_toggle = verify_group.add_mutually_exclusive_group()
    verify_toggle.add_argument("--accuraterip", action="store_true",
                               help="Enable optional AccurateRip verification if a helper is installed")
    verify_toggle.add_argument("--no-accuraterip", action="store_true",
                               help="Disable AccurateRip verification even if enabled in config")
    p.add_argument("--no-cover-art", action="store_true",
                   help="Disable downloading cover art")

    # Misc
    p.add_argument("--keep-wav", action="store_true",
                   help="Keep intermediate WAV files")
    p.add_argument("--eject", action="store_true",
                   help="Eject disc when done")
    p.add_argument("--dry-run", action="store_true",
                   help="Show what would be done without accessing the disc")
    p.add_argument("--debug", action="store_true",
                   help="Print subprocess commands and verbose output")
    p.add_argument("--version", action="version", version="discvault 0.1.0")

    return p.parse_args()
