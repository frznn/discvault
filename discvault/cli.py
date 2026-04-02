"""Command-line interface and main orchestrator."""
from __future__ import annotations

import argparse
import asyncio
import signal
import subprocess
import sys
from pathlib import Path

from . import __version__
from .cleanup import Cleanup
from .config import Config, first_run_setup
from .tracks import compact_track_list, display_track_count, parse_track_spec, resolve_selected_tracks
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

    if args.check_deps:
        check_cfg = cfg.clone()
        _apply_cli_overrides(args, check_cfg)
        raise SystemExit(_run_dependency_check(args, check_cfg))

    # First-run wizard (only if interactive and no config file yet)
    if not args.dry_run:
        first_run_setup(cfg)

    _apply_cli_overrides(args, cfg)

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
        error("Textual is not available in this environment. Reinstall DiscVault or run with --cli.")
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
    from . import device as dev_mod
    from . import disc as disc_mod
    from . import extras as extras_mod
    from . import library
    from .metadata import lookup as meta_lookup
    from .metadata import urlimport
    from .pipeline import BackupCallbacks, BackupRunError, BackupRunRequest, EncodeOptions, OutputSelection, run_backup
    from .ui.selector import select_candidate

    cleanup = Cleanup()
    extra_scan_bundle = None
    selected_extra_paths: list[str] = []

    def _abort(signum=None, frame=None):
        error("Interrupted — cleaning up...")
        if extra_scan_bundle is not None:
            extra_scan_bundle.close()
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
        disc_info = disc_mod.load_disc_info(device, debug=args.debug)
    except Exception as exc:
        if args.dry_run:
            log("Dry-run: disc read skipped.")
            from .metadata.types import DiscInfo
            disc_info = DiscInfo(device=device)
        else:
            error(f"Failed to read disc info: {exc}")
            sys.exit(1)
    disc_info.device = device
    extra_scan_bundle, extra_probe_detail = extras_mod.probe_disc_extras(device)
    extra_track_number = extra_scan_bundle.track_number if extra_scan_bundle is not None else None
    has_data_session = extra_scan_bundle is not None
    log(
        f"Tracks: {display_track_count(disc_info, extra_track_number=extra_track_number, has_data_session=has_data_session)}  |  "
        f"FreeDB ID: {disc_info.freedb_disc_id or '(none)'}  |  "
        f"MB ID: {disc_info.mb_disc_id or '(none)'}"
    )
    mb_notice = disc_mod.musicbrainz_lookup_notice(disc_info)
    if mb_notice:
        warn(mb_notice)
    if disc_info.data_track_numbers:
        warn("This disc may include extra files.")
        if sys.stdin.isatty():
            log("Tip: you can scan for extra files and choose what to copy into extras/.")
    if extra_scan_bundle is not None:
        success(extra_probe_detail)
        if sys.stdin.isatty():
            log("Tip: use the extras picker to choose files to copy into extras/.")
    selected_tracks = resolve_selected_tracks(
        disc_info,
        requested_tracks,
        extra_track_number=extra_track_number,
        has_data_session=has_data_session,
    )
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
    metadata_url = getattr(args, "metadata_url", "") or ""
    if metadata_url and not urlimport.is_supported_url(metadata_url):
        provider = urlimport.provider_name(metadata_url)
        detail = provider or "unknown provider"
        warn(f"Metadata URL import skipped: unsupported provider ({detail}).")
        metadata_url = ""
    candidates = meta_lookup.fetch_candidates(
        disc_info,
        cfg,
        debug=meta_debug,
        metadata_file=args.metadata_file or "",
        metadata_url=metadata_url,
        manual_hints=(args.artist or "", args.album or "", args.year or ""),
    )

    if not candidates:
        warn("No metadata found from any source.")
        if sys.stdin.isatty():
            warn("Tip: use --artist/--album/--year or --metadata-file to supply metadata manually.")

    # ------------------------------------------------------------------
    # 4. Selection + confirm loop
    # ------------------------------------------------------------------
    back_to_meta = True
    meta = None
    artist = args.artist or ""
    album = args.album or ""
    year = args.year or ""
    target_dir_override: Path | None = None

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

        selected_tracks = resolve_selected_tracks(disc_info, requested_tracks, meta)
        if not selected_tracks:
            error("No audio tracks remain selected. Adjust --tracks or choose a disc with audio tracks.")
            sys.exit(1)

        # --- 4c. Confirm before starting ---
        if sys.stdin.isatty() and not args.dry_run:
            while True:
                album_root = target_dir_override or library.album_root(cfg.base_dir, artist, album, year)
                action, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override = _confirm_before_start(
                    artist, album, year,
                    meta.source if meta else "Manual",
                    album_root,
                    do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
                    args.flac_compression, args.mp3_bitrate, cfg.opus_bitrate, cfg.aac_bitrate,
                    len(selected_extra_paths),
                    target_dir_override,
                )
                if action == "proceed":
                    break
                elif action == "extras":
                    selected_extra_paths, extra_scan_bundle = _select_extra_files_cli(
                        device,
                        disc_info,
                        cfg,
                        meta=meta,
                        debug=args.debug,
                        existing_bundle=extra_scan_bundle,
                    )
                elif action == "edit":
                    artist, album, year = _edit_tags(artist, album, year)
                    if meta:
                        meta.album_artist = artist
                        meta.album = album
                        meta.year = year
                elif action == "back":
                    back_to_meta = True
                    target_dir_override = None
                    artist = args.artist or ""
                    album = args.album or ""
                    year = args.year or ""
                    break
        else:
            album_root = target_dir_override or library.album_root(cfg.base_dir, artist, album, year)
            if album_root.exists():
                warn(f"Album folder already exists (may be overwritten): {album_root}")

    outputs = OutputSelection(
        image=do_image,
        iso=do_iso,
        flac=do_flac,
        mp3=do_mp3,
        ogg=do_ogg,
        opus=do_opus,
        alac=do_alac,
        aac=do_aac,
        wav=do_wav,
    )

    # ------------------------------------------------------------------
    # 5. Paths / dry-run
    # ------------------------------------------------------------------
    album_root = target_dir_override or library.album_root(cfg.base_dir, artist, album, year)
    img_dir = library.image_dir(album_root)
    fl_dir = library.flac_dir(album_root)
    mp_dir = library.mp3_dir(album_root)
    og_dir = library.ogg_dir(album_root)
    op_dir = library.opus_dir(album_root)
    al_dir = library.alac_dir(album_root)
    aa_dir = library.aac_dir(album_root)
    wa_dir = library.wav_dir(album_root)

    log(f"Album folder: {album_root}")

    if args.dry_run:
        _dry_run_summary(
            args, cfg, device, artist, album, year,
            meta, album_root, img_dir, fl_dir, mp_dir, og_dir, op_dir, al_dir, aa_dir, wa_dir,
            do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
            selected_tracks, len(selected_extra_paths),
        )
        return

    # ------------------------------------------------------------------
    # 6. Finalize metadata and run shared backup pipeline
    # ------------------------------------------------------------------
    if not meta:
        from .metadata.types import Metadata as MetaType
        meta = MetaType(source="Manual", album_artist=artist, album=album, year=year)
    else:
        meta.album_artist = artist
        meta.album = album
        meta.year = year

    callbacks = BackupCallbacks(
        info=log,
        warn=warn,
        success=success,
    )
    encode_opts = EncodeOptions(
        flac_compression=args.flac_compression,
        flac_verify=not args.no_verify,
        mp3_quality=args.mp3_quality,
        mp3_bitrate=args.mp3_bitrate,
        debug=args.debug,
    )
    try:
        result = run_backup(
            BackupRunRequest(
                device=device,
                disc_info=disc_info,
                meta=meta,
                artist=artist,
                album=album,
                year=year,
                outputs=outputs,
                selected_tracks=selected_tracks,
                    cfg=cfg,
                    encode_opts=encode_opts,
                    cleanup=cleanup,
                    cover_art_enabled=cfg.download_cover_art,
                    selected_extra_paths=selected_extra_paths,
                    extras_iso_path=extra_scan_bundle.iso_path if extra_scan_bundle is not None else None,
                    extras_mount_root=extra_scan_bundle.mount_root if extra_scan_bundle is not None else None,
                    album_root_override=target_dir_override,
                ),
                callbacks,
            )
    except BackupRunError as exc:
        if extra_scan_bundle is not None:
            extra_scan_bundle.close()
        cleanup.remove_all()
        error(str(exc))
        sys.exit(1)

    if extra_scan_bundle is not None:
        extra_scan_bundle.close()

    sound_ok = alerts.play_completion_sound(cfg.completion_sound)
    notify_ok = alerts.send_desktop_notification(
        "DiscVault rip complete",
        f"{artist} — {album}",
    )
    if cfg.completion_sound != "off" and not sound_ok:
        warn("Completion sound unavailable.")
    if not notify_ok:
        warn("Desktop notifications unavailable.")
    if result.copied_extra_count and result.extras_dir is not None:
        success(f"Extra files saved: {result.copied_extra_count} -> {result.extras_dir}")
    success(f"Done! Files saved to: {result.album_root}")


def _apply_cli_overrides(args: argparse.Namespace, cfg: Config) -> None:
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


def _run_dependency_check(args: argparse.Namespace, cfg: Config) -> int:
    from . import deps as deps_mod

    report = deps_mod.build_dependency_report(args, cfg, textual_available=_textual_available())
    for line in deps_mod.format_dependency_report(report):
        console.print(line)
    return deps_mod.dependency_exit_code(report)


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
    selected_extra_count: int,
    target_dir_override: Path | None = None,
) -> tuple[str, bool, bool, bool, bool, bool, bool, bool, bool, bool, Path | None]:
    """
    Show a pre-rip summary with toggleable outputs.
    Returns (action, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override).
    action is one of: 'proceed', 'extras', 'edit', 'back'.
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
        if target_dir_override:
            console.print(f"  Target folder:   [bold]{album_root}[/bold] [dim](override)[/dim]")
        else:
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
        console.print(f"  Extra files:      {selected_extra_count} selected")

        try:
            answer = console.input(
                "\nProceed? [Y=yes, 1-9=toggle output, x=extras, d=change dir, e=edit tags, b=back, q=quit]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if answer in ("", "y", "yes"):
            if do_iso and not do_image:
                warn("ISO export requires disc image output.")
                continue
            if not any((do_image, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav)) and not selected_extra_count:
                warn("Nothing to do — enable at least one output or select extra files.")
                continue
            return "proceed", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override
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
        elif answer in ("x", "extras"):
            return "extras", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override
        elif answer in ("d", "dir"):
            try:
                current = str(target_dir_override) if target_dir_override else ""
                raw = console.input(
                    f"  Target directory [{current or 'auto'}] (blank to reset): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                raw = ""
            if raw:
                target_dir_override = Path(raw).expanduser()
                album_root = target_dir_override
                log(f"Target directory set to: {target_dir_override}")
            else:
                target_dir_override = None
                log("Target directory reset to auto.")
        elif answer in ("e", "edit"):
            return "edit", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override
        elif answer in ("b", "back"):
            return "back", do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, target_dir_override
        elif answer in ("q", "quit"):
            log("Aborted.")
            sys.exit(0)
        else:
            console.print("[warning]Please enter Y, 1-9, x, d, e, b, or q.[/warning]")


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


def _select_extra_files_cli(
    device: str,
    disc_info,
    cfg: Config,
    *,
    meta=None,
    debug: bool = False,
    existing_bundle=None,
):
    from . import extras as extras_mod

    bundle = existing_bundle
    if bundle is None:
        try:
            answer = console.input("Scan extra files from the disc? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes"):
            return [], None

        log("Scanning extra files from the disc...")
        bundle, detail = extras_mod.scan_disc_extras(
            device,
            disc_info,
            cfg,
            meta=meta,
            work_dir=Path(cfg.work_dir),
            debug=debug,
        )
        if bundle is None:
            warn(detail)
            return [], None
        success(detail)

    console.print("\n[bold]Extra files[/bold]")
    for index, entry in enumerate(bundle.entries, start=1):
        console.print(f"  {index:>2}. {entry.path} ({extras_mod.human_size(entry.size)})")

    while True:
        try:
            answer = console.input(
                "Select extra files [Enter=none, all, or 1-3,5]: "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""

        if not answer:
            return [], bundle
        if answer == "all":
            return [entry.path for entry in bundle.entries], bundle
        try:
            chosen = parse_track_spec(answer)
        except ValueError:
            warn("Invalid selection. Use formats like 1-3 or 1,4,9.")
            continue

        max_index = len(bundle.entries)
        invalid = [num for num in chosen if num < 1 or num > max_index]
        if invalid:
            warn(f"Ignored out-of-range entries: {compact_track_list(invalid)}")
        selected = [bundle.entries[num - 1].path for num in chosen if 1 <= num <= max_index]
        return selected, bundle


# ---------------------------------------------------------------------------
# Dry-run summary
# ---------------------------------------------------------------------------

def _dry_run_summary(
    args, cfg, device, artist, album, year, meta, album_root,
    img_dir, fl_dir, mp_dir, og_dir, op_dir, al_dir, aa_dir, wa_dir,
    do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
    selected_tracks, selected_extra_count,
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
    if selected_extra_count:
        console.print(f"  Extras dir:  {album_root / 'extras'}")
        console.print(f"  Extras:      {selected_extra_count} selected")
    console.print(f"  Work dir:    {cfg.work_dir}")
    console.print(f"  Sample off:  {cfg.cdparanoia_sample_offset}")
    console.print(f"  AccurateRip: {'yes' if cfg.accuraterip_enabled else 'no'}")
    console.print(f"  Cover art:   {'yes' if cfg.download_cover_art else 'no'}")
    console.print("\nDry-run: would execute the selected rip stages and write backup-info.txt")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="discvault",
        description="Rip and archive CDs to audio files and full disc images.",
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
    p.add_argument("--check-deps", action="store_true",
                   help="Check helper-tool dependencies for the current selection and exit")
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
    p.add_argument("--version", action="version", version=f"discvault {__version__}")

    return p


def _parse_args() -> argparse.Namespace:
    return build_parser().parse_args()
