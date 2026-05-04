"""Shared backup pipeline used by both CLI and TUI."""
from __future__ import annotations

import datetime
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from . import __version__
from .cleanup import Cleanup
from .metadata.types import DiscInfo, Metadata
from .tracks import compact_track_list

if TYPE_CHECKING:
    from .config import Config


@dataclass(frozen=True)
class OutputSelection:
    image: bool
    iso: bool
    flac: bool
    mp3: bool
    ogg: bool
    opus: bool
    alac: bool
    aac: bool
    wav: bool


@dataclass(frozen=True)
class EncodeOptions:
    """Encoding parameters that were previously threaded through argparse Namespace."""
    flac_compression: int = 8
    flac_verify: bool = True
    mp3_quality: int = 2
    mp3_bitrate: int = 320
    debug: bool = False


@dataclass
class BackupRunRequest:
    device: str
    disc_info: DiscInfo
    meta: Metadata
    artist: str
    album: str
    year: str
    outputs: OutputSelection
    selected_tracks: list[int]
    cfg: "Config"
    encode_opts: EncodeOptions
    cleanup: Cleanup
    cover_art_enabled: bool
    selected_extra_paths: list[str] = field(default_factory=list)
    extras_iso_path: Path | None = None
    extras_mount_root: Path | None = None
    # When set, overrides the auto-generated album_root path.
    album_root_override: Path | None = None
    # When True, stages skip work whose output is already present (and non-empty)
    # in the album root or work_dir, instead of re-running it. Used by --resume / TUI Resume.
    resume: bool = False


@dataclass
class BackupRunResult:
    album_root: Path
    completed_track_count: int
    accuraterip_detail: str = ""
    toc_path: Path | None = None
    cue_path: Path | None = None
    bin_path: Path | None = None
    iso_path: Path | None = None
    cover_art_path: Path | None = None
    extras_dir: Path | None = None
    copied_extra_count: int = 0


@dataclass
class BackupCallbacks:
    info: Callable[[str], None] | None = None
    warn: Callable[[str], None] | None = None
    success: Callable[[str], None] | None = None
    stage_start: Callable[[str, str, int | None], None] | None = None
    stage_progress: Callable[[str, int, int, str], None] | None = None
    stage_done: Callable[[str, str], None] | None = None
    set_process: Callable[[object | None], None] | None = None


class BackupRunError(RuntimeError):
    """Raised when a shared pipeline stage fails."""


# Prefix used in BackupRunError messages so the TUI can detect image rip failures
# and offer to retry with the alternative tool.
IMAGE_RIP_ERROR_PREFIX = "IMAGE_RIP:"


def run_backup(request: BackupRunRequest, callbacks: BackupCallbacks | None = None) -> BackupRunResult:
    from . import artwork as artwork_mod
    from . import encode as enc_mod
    from . import extras as extras_mod
    from . import library
    from . import rip as rip_mod
    from . import verify as verify_mod

    callbacks = callbacks or BackupCallbacks()
    cfg = request.cfg
    enc = request.encode_opts
    disc_info = request.disc_info
    cleanup = request.cleanup
    outputs = request.outputs

    if request.album_root_override is not None:
        album_root = request.album_root_override
    else:
        album_root = library.album_root(cfg.base_dir, request.artist, request.album, request.year)
    album_root_existed = album_root.exists()
    artist_dir = album_root.parent
    if not artist_dir.exists():
        cleanup.track_prune_dir(artist_dir)
    img_dir = library.image_dir(album_root)
    fl_dir = library.flac_dir(album_root)
    mp_dir = library.mp3_dir(album_root)
    og_dir = library.ogg_dir(album_root)
    op_dir = library.opus_dir(album_root)
    al_dir = library.alac_dir(album_root)
    aa_dir = library.aac_dir(album_root)
    wa_dir = library.wav_dir(album_root)
    ex_dir = library.extras_dir(album_root)

    work_dir = Path(cfg.work_dir)
    work_dir_existed = work_dir.exists()
    work_dir.mkdir(parents=True, exist_ok=True)
    cleanup.track_dir(work_dir, created=not work_dir_existed)

    toc_path = cue_path = bin_path = iso_path = None
    wav_files: list[Path] = []
    accuraterip_detail = ""
    cover_art_path = None
    copied_extra_paths: list[Path] = []

    audio_formats = _audio_formats(outputs)

    # Disc image
    if outputs.image:
        tool = cfg.image_ripper
        tool_label = "readom" if tool == "readom" else "cdrdao"
        stem = library.image_stem(request.artist, request.album, request.year)
        cleanup.track_dir(album_root, created=not album_root_existed)
        img_dir_existed = img_dir.exists()
        img_dir.mkdir(parents=True, exist_ok=True)
        cleanup.track_dir(img_dir, created=not img_dir_existed)

        existing = _existing_image_artifacts(img_dir, stem) if request.resume else None
        if existing is not None:
            bin_path, cue_path, toc_path = existing
            _info(callbacks, f"Disc image already present, reusing ({bin_path.name}).")
            _stage_done(callbacks, "image", "✓ Disc image (reused)")
            if outputs.iso:
                existing_iso = img_dir / f"{stem}.iso"
                if existing_iso.exists() and existing_iso.stat().st_size > 0:
                    iso_path = existing_iso
                    _info(callbacks, f"ISO already present, reusing ({iso_path.name}).")
                    _stage_done(callbacks, "iso", "✓ ISO data image (reused)")
                else:
                    _stage_start(callbacks, "iso", "Exporting ISO data image...", None)
                    iso_path = _export_iso(
                        img_dir, stem, bin_path, disc_info, toc_path, cleanup, callbacks
                    )
        else:
            _info(callbacks, f"Creating disc image ({tool_label})...")
            _stage_start(callbacks, "image", f"Creating disc image ({tool_label})...", disc_info.track_count or None)
            stem = library.unique_image_stem(img_dir, stem)
            bin_path = img_dir / f"{stem}.bin"

            if tool == "readom":
                toc_path = None
                ok, rip_detail = rip_mod.rip_image_readom(
                    request.device,
                    bin_path,
                    disc_info,
                    cleanup,
                    debug=enc.debug,
                    process_callback=lambda proc: _set_process(callbacks, proc),
                    progress_callback=_progress_callback(callbacks, "image"),
                )
            else:
                toc_path = img_dir / f"{stem}.toc"
                ok, rip_detail = rip_mod.rip_image(
                    request.device,
                    toc_path,
                    bin_path,
                    cleanup,
                    command_template=cfg.cdrdao_command,
                    debug=enc.debug,
                    process_callback=lambda proc: _set_process(callbacks, proc),
                    progress_callback=_progress_callback(callbacks, "image"),
                    track_count=disc_info.track_count,
                    track_offsets=disc_info.track_offsets,
                    leadout=disc_info.leadout,
                )
            _set_process(callbacks, None)
            if not ok:
                msg = f"Disc image failed ({tool_label}): {rip_detail}" if rip_detail else f"Disc image failed ({tool_label})"
                raise BackupRunError(f"{IMAGE_RIP_ERROR_PREFIX}{msg}")
            _success(callbacks, "Disc image created.")
            _stage_done(callbacks, "image", "✓ Disc image")

            if toc_path is not None:
                cue_path = img_dir / f"{stem}.cue"
                try:
                    rip_mod.write_cue_file(cue_path, bin_path, disc_info, toc_path=toc_path, cleanup=cleanup)
                except OSError as exc:
                    raise BackupRunError(f"Failed to write CUE sidecar: {exc}") from exc
                _success(callbacks, f"CUE sidecar saved: {cue_path.name}")
            else:
                # readom: synthesize CUE from disc_info (no .toc available)
                cue_path = img_dir / f"{stem}.cue"
                try:
                    rip_mod.write_cue_file(cue_path, bin_path, disc_info, toc_path=None, cleanup=cleanup)
                except OSError as exc:
                    _warn(callbacks, f"Could not write CUE sidecar: {exc}")
                    cue_path = None
                else:
                    _success(callbacks, f"CUE sidecar saved: {cue_path.name}")

            if outputs.iso:
                _info(callbacks, "Exporting ISO data image...")
                _stage_start(callbacks, "iso", "Exporting ISO data image...", None)
                iso_path = _export_iso(
                    img_dir, stem, bin_path, disc_info, toc_path, cleanup, callbacks
                )

    # Audio extraction
    if audio_formats:
        existing_wavs = (
            _existing_wav_files(work_dir, disc_info.track_count, request.selected_tracks)
            if request.resume
            else None
        )
        if existing_wavs is not None:
            wav_files = existing_wavs
            _info(callbacks, f"Audio WAVs already present in work_dir, reusing {len(wav_files)} file(s).")
            _stage_done(callbacks, "rip", "✓ Audio tracks (reused)")
            # AccurateRip on reused WAVs is a no-op for the user — the prior run already
            # verified them, and re-verifying produces the same answer.
            if cfg.accuraterip_enabled:
                _info(callbacks, "AccurateRip skipped on reuse (already verified in the prior run).")
        else:
            _info(callbacks, "Ripping audio tracks...")
            _stage_start(callbacks, "rip", "Ripping audio tracks...", len(request.selected_tracks) or None)
            wav_files, rip_detail = rip_mod.rip_audio(
                request.device,
                work_dir,
                disc_info.track_count,
                cleanup,
                debug=enc.debug,
                progress_callback=_audio_progress_callback(callbacks),
                process_callback=lambda proc: _set_process(callbacks, proc),
                selected_tracks=request.selected_tracks,
                sample_offset=cfg.cdparanoia_sample_offset,
            )
            _set_process(callbacks, None)
            if wav_files is None:
                raise BackupRunError(f"Audio track extraction failed: {rip_detail}" if rip_detail else "Failed to rip audio tracks")
            _success(callbacks, "Audio tracks ripped.")
            _stage_done(callbacks, "rip", "✓ Audio tracks")

            if cfg.accuraterip_enabled:
                _info(callbacks, "Running AccurateRip verification...")
                if cfg.cdparanoia_sample_offset == 0:
                    _warn(
                        callbacks,
                        "AccurateRip is enabled with sample offset 0. Set your drive offset for more reliable results.",
                    )
                verified, detail = verify_mod.verify_accuraterip(wav_files, debug=enc.debug)
                accuraterip_detail = detail
                if verified is True:
                    _success(callbacks, detail)
                else:
                    _warn(callbacks, detail)

        cleanup.track_dir(album_root, created=not album_root_existed)

        for fmt_key, fmt_name in audio_formats:
            out_dir = _ensure_output_dir(fmt_key, fl_dir, mp_dir, og_dir, op_dir, al_dir, aa_dir, wa_dir)
            out_dir_existed = out_dir.exists()
            out_dir.mkdir(parents=True, exist_ok=True)
            cleanup.track_dir(out_dir, created=not out_dir_existed)

            stage_label = _output_stage_label(fmt_key, fmt_name)
            _info(callbacks, f"{stage_label}...")
            _stage_start(callbacks, fmt_key, f"{stage_label}...", len(wav_files) or None)
            ok = enc_mod.encode_tracks(
                wav_files,
                request.meta,
                flac_dir=fl_dir if fmt_key == "flac" else None,
                mp3_dir=mp_dir if fmt_key == "mp3" else None,
                ogg_dir=og_dir if fmt_key == "ogg" else None,
                opus_dir=op_dir if fmt_key == "opus" else None,
                alac_dir=al_dir if fmt_key == "alac" else None,
                aac_dir=aa_dir if fmt_key == "aac" else None,
                wav_dir=wa_dir if fmt_key == "wav" else None,
                flac_compression=enc.flac_compression,
                flac_verify=enc.flac_verify,
                mp3_quality=enc.mp3_quality,
                mp3_bitrate=enc.mp3_bitrate,
                opus_bitrate=cfg.opus_bitrate,
                aac_bitrate=cfg.aac_bitrate,
                cleanup=cleanup,
                debug=enc.debug,
                progress_callback=_encode_progress_callback(callbacks, fmt_key, stage_label),
                track_total_hint=request.meta.track_count or disc_info.track_count or None,
                skip_existing=request.resume,
            )
            if not ok:
                raise BackupRunError(f"Encoding to {fmt_name} format failed.")
            _success(callbacks, f"{fmt_name} format complete.")
            _stage_done(callbacks, fmt_key, f"✓ {fmt_name} format")

    cover_art_enabled = request.cover_art_enabled
    if cover_art_enabled:
        existing_cover = _existing_cover_art(album_root) if request.resume else None
        if existing_cover is not None:
            cover_art_path = existing_cover
            _info(callbacks, f"Cover art already present, reusing ({cover_art_path.name}).")
        else:
            _info(callbacks, f"Cover art: {artwork_mod.describe_cover_art(request.meta, enabled=True)}")
            cover_art_path = artwork_mod.download_cover_art(
                request.meta,
                album_root,
                cleanup=cleanup,
                timeout=cfg.metadata_timeout,
                debug=enc.debug,
            )
            if cover_art_path is not None:
                _success(callbacks, f"Cover art saved: {cover_art_path.name}")
            else:
                _warn(callbacks, "Cover art not downloaded.")

    extra_paths = list(dict.fromkeys(path for path in request.selected_extra_paths if path))
    if extra_paths and request.resume and _existing_extras_present(ex_dir):
        _info(callbacks, f"Extras already present in {ex_dir.name}, reusing.")
        copied_extra_paths = sorted(p for p in ex_dir.iterdir() if p.is_file())
        _stage_done(callbacks, "extras", "✓ Extra files (reused)")
        extra_paths = []
    if extra_paths:
        cleanup.track_dir(album_root, created=not album_root_existed)
        _info(callbacks, f"Saving {len(extra_paths)} extra file(s)...")
        stage_label = "Saving extra files..."
        cached_mount_root = (
            request.extras_mount_root
            if request.extras_mount_root and request.extras_mount_root.exists()
            else None
        )
        cached_iso = request.extras_iso_path if request.extras_iso_path and request.extras_iso_path.exists() else None
        _stage_start(
            callbacks,
            "extras",
            stage_label,
            len(extra_paths) if cached_mount_root is not None or cached_iso is not None or iso_path is not None else None,
        )
        temp_workspace: tempfile.TemporaryDirectory[str] | None = None
        temp_scan_bundle = None
        extras_iso_path = cached_iso
        extras_mount_root = cached_mount_root
        try:
            if extras_mount_root is not None:
                copied_extra_paths, detail = extras_mod.copy_mounted_extra_files(
                    extras_mount_root,
                    extra_paths,
                    ex_dir,
                    cleanup=cleanup,
                    progress_callback=_progress_callback(callbacks, "extras"),
                )
            elif extras_iso_path is None and iso_path is not None and iso_path.exists():
                extras_iso_path = iso_path
                copied_extra_paths, detail = extras_mod.copy_extra_files(
                    extras_iso_path,
                    extra_paths,
                    ex_dir,
                    cleanup=cleanup,
                    progress_callback=_progress_callback(callbacks, "extras"),
                )
            elif extras_iso_path is None and bin_path is not None and bin_path.exists():
                temp_workspace = tempfile.TemporaryDirectory(prefix="discvault-extras-", dir=str(work_dir))
                temp_iso_path = Path(temp_workspace.name) / "extras.iso"
                exported_iso, detail = rip_mod.export_iso_from_bin(
                    temp_iso_path,
                    bin_path,
                    disc_info,
                    toc_path=toc_path,
                    progress_callback=_progress_callback(callbacks, "extras"),
                )
                if exported_iso is None:
                    raise BackupRunError(detail or "Extra files failed while exporting the data track.")
                extras_iso_path = exported_iso
                copied_extra_paths, detail = extras_mod.copy_extra_files(
                    extras_iso_path,
                    extra_paths,
                    ex_dir,
                    cleanup=cleanup,
                    progress_callback=_progress_callback(callbacks, "extras"),
                )
            else:
                temp_scan_bundle, detail = extras_mod.scan_disc_extras(
                    request.device,
                    disc_info,
                    cfg,
                    meta=request.meta,
                    work_dir=work_dir,
                    debug=enc.debug,
                    process_callback=lambda proc: _set_process(callbacks, proc),
                    progress_callback=_progress_callback(callbacks, "extras"),
                )
                _set_process(callbacks, None)
                if temp_scan_bundle is None:
                    raise BackupRunError(detail or "Extra files failed while reading the disc.")
                if temp_scan_bundle.mount_root is not None:
                    copied_extra_paths, detail = extras_mod.copy_mounted_extra_files(
                        temp_scan_bundle.mount_root,
                        extra_paths,
                        ex_dir,
                        cleanup=cleanup,
                        progress_callback=_progress_callback(callbacks, "extras"),
                    )
                else:
                    extras_iso_path = temp_scan_bundle.iso_path
                    copied_extra_paths, detail = extras_mod.copy_extra_files(
                        extras_iso_path,
                        extra_paths,
                        ex_dir,
                        cleanup=cleanup,
                        progress_callback=_progress_callback(callbacks, "extras"),
                    )
            if copied_extra_paths is None:
                raise BackupRunError(detail or "Extra files failed while copying the selected files.")
        finally:
            _set_process(callbacks, None)
            if temp_scan_bundle is not None:
                temp_scan_bundle.close()
            if temp_workspace is not None:
                temp_workspace.cleanup()
        _success(callbacks, f"Saved {len(copied_extra_paths)} extra file(s).")
        _stage_done(callbacks, "extras", "✓ Extra files")

    write_backup_info(
        album_root=album_root,
        device=request.device,
        artist=request.artist,
        album=request.album,
        year=request.year,
        meta_source=request.meta.source,
        wav_files=wav_files,
        track_count=disc_info.track_count,
        toc_path=toc_path,
        cue_path=cue_path,
        bin_path=bin_path,
        iso_path=iso_path,
        outputs=outputs,
        encode_opts=enc,
        cfg=cfg,
        cleanup=cleanup,
        selected_tracks=request.selected_tracks,
        accuraterip_enabled=cfg.accuraterip_enabled,
        accuraterip_detail=accuraterip_detail,
        cover_art_path=cover_art_path,
        cover_art_enabled=cover_art_enabled,
        extras_dir=ex_dir if copied_extra_paths else None,
        copied_extra_paths=copied_extra_paths,
        selected_extra_paths=extra_paths,
        warn=callbacks.warn,
    )

    if not cfg.keep_wav:
        for wav_path in wav_files:
            wav_path.unlink(missing_ok=True)
        try:
            work_dir.rmdir()
        except OSError:
            pass

    if cfg.eject_after:
        subprocess.run(["eject", request.device], capture_output=True)

    cleanup.clear()
    return BackupRunResult(
        album_root=album_root,
        completed_track_count=len(wav_files) or disc_info.track_count,
        accuraterip_detail=accuraterip_detail,
        toc_path=toc_path,
        cue_path=cue_path,
        bin_path=bin_path,
        iso_path=iso_path,
        cover_art_path=cover_art_path,
        extras_dir=ex_dir if copied_extra_paths else None,
        copied_extra_count=len(copied_extra_paths),
    )


def write_backup_info(
    *,
    album_root: Path,
    device: str,
    artist: str,
    album: str,
    year: str,
    meta_source: str,
    wav_files: list[Path],
    track_count: int,
    toc_path: Path | None,
    cue_path: Path | None,
    bin_path: Path | None,
    iso_path: Path | None,
    outputs: OutputSelection,
    encode_opts: EncodeOptions,
    cfg: "Config",
    cleanup: Cleanup,
    selected_tracks: list[int],
    accuraterip_enabled: bool,
    accuraterip_detail: str,
    cover_art_path: Path | None,
    cover_art_enabled: bool,
    extras_dir: Path | None,
    copied_extra_paths: list[Path],
    selected_extra_paths: list[str],
    warn: Callable[[str], None] | None = None,
) -> None:
    info_path = album_root / "backup-info.txt"
    cleanup.track_file(info_path, created=not info_path.exists())
    lines = [
        f"Backup timestamp: {datetime.datetime.now().astimezone().isoformat()}",
        f"DiscVault version: {__version__}",
        f"Device: {device}",
        f"Artist: {artist}",
        f"Album: {album}",
    ]
    if year:
        lines.append(f"Year: {year}")
    lines.append(f"Metadata source: {meta_source}")
    lines.append(f"Disc track count: {track_count or len(selected_tracks)}")
    lines.append(f"Selected tracks: {compact_track_list(selected_tracks) if selected_tracks else '(none)'}")
    lines.append(f"Audio tracks written: {len(wav_files)}")
    lines.append(f"Disc image: {'yes' if outputs.image else 'no'}")
    if bin_path is not None:
        lines.append(f"Image BIN: {bin_path}")
    if cue_path is not None:
        lines.append(f"Image CUE: {cue_path}")
    if toc_path is not None:
        lines.append(f"Image TOC: {toc_path}")
    lines.append(f"ISO export: {'yes' if outputs.iso else 'no'}")
    if iso_path is not None:
        lines.append(f"Image ISO: {iso_path}")
    lines.append(f"FLAC: {'yes' if outputs.flac else 'no'}")
    lines.append(f"MP3: {'yes' if outputs.mp3 else 'no'}")
    lines.append(f"OGG: {'yes' if outputs.ogg else 'no'}")
    lines.append(f"Opus: {'yes' if outputs.opus else 'no'}")
    lines.append(f"ALAC: {'yes' if outputs.alac else 'no'}")
    lines.append(f"AAC/M4A: {'yes' if outputs.aac else 'no'}")
    lines.append(f"WAV copy: {'yes' if outputs.wav else 'no'}")
    lines.append(f"Extra files selected: {len(selected_extra_paths)}")
    lines.append(f"Extra files saved: {len(copied_extra_paths)}")
    if extras_dir is not None:
        lines.append(f"Extras dir: {extras_dir}")
    lines.append(f"AccurateRip: {'yes' if accuraterip_enabled else 'no'}")
    if accuraterip_detail:
        lines.append(f"AccurateRip result: {accuraterip_detail}")
    lines.append(f"Sample offset: {cfg.cdparanoia_sample_offset}")
    lines.append(f"Cover art enabled: {'yes' if cover_art_enabled else 'no'}")
    if cover_art_path is not None:
        lines.append(f"Cover art: {cover_art_path}")
    lines.append(f"FLAC compression: {encode_opts.flac_compression}")
    mp3_desc = f"{encode_opts.mp3_bitrate} kbps" if encode_opts.mp3_bitrate > 0 else "VBR"
    lines.append(f"MP3 bitrate: {mp3_desc}")
    lines.append(f"Opus bitrate: {cfg.opus_bitrate}")
    lines.append(f"AAC bitrate: {cfg.aac_bitrate}")
    try:
        info_path.write_text("\n".join(lines) + "\n")
    except OSError as exc:
        _warn_raw(warn, f"Could not write backup-info.txt: {exc}")


def _existing_image_artifacts(
    img_dir: Path, preferred_stem: str
) -> tuple[Path, Path, Path | None] | None:
    """Detect a usable disc image already on disk for resume.

    Returns ``(bin_path, cue_path, toc_path)`` when a non-empty BIN with a
    matching CUE sidecar exists in ``img_dir``. ``toc_path`` may be ``None`` for
    readom-produced images (no .toc on disk). Tries the preferred stem first,
    then any BIN+CUE pair.
    """
    if not img_dir.is_dir():
        return None

    def _candidate(stem: str) -> tuple[Path, Path, Path | None] | None:
        bin_path = img_dir / f"{stem}.bin"
        cue_path = img_dir / f"{stem}.cue"
        if not bin_path.exists() or bin_path.stat().st_size == 0:
            return None
        if not cue_path.exists() or cue_path.stat().st_size == 0:
            return None
        toc_path = img_dir / f"{stem}.toc"
        return bin_path, cue_path, toc_path if toc_path.exists() else None

    found = _candidate(preferred_stem)
    if found is not None:
        return found
    for bin_file in sorted(img_dir.glob("*.bin")):
        candidate = _candidate(bin_file.stem)
        if candidate is not None:
            return candidate
    return None


def _export_iso(
    img_dir: Path,
    stem: str,
    bin_path: Path,
    disc_info: DiscInfo,
    toc_path: Path | None,
    cleanup: Cleanup,
    callbacks: BackupCallbacks,
) -> Path | None:
    from . import rip as rip_mod

    iso_path = img_dir / f"{stem}.iso"
    exported_iso, detail = rip_mod.export_iso_from_bin(
        iso_path,
        bin_path,
        disc_info,
        toc_path=toc_path,
        cleanup=cleanup,
        progress_callback=_progress_callback(callbacks, "iso"),
    )
    if exported_iso is not None:
        _success(callbacks, f"ISO saved: {exported_iso.name}")
        _stage_done(callbacks, "iso", "✓ ISO data image")
        return exported_iso
    _warn(callbacks, detail)
    _stage_done(callbacks, "iso", "✓ ISO skipped")
    return None


def _existing_extras_present(extras_dir: Path) -> bool:
    """True when ``extras_dir`` exists and already contains at least one file."""
    if not extras_dir.is_dir():
        return False
    return any(p.is_file() for p in extras_dir.iterdir())


def _existing_cover_art(album_root: Path) -> Path | None:
    """Return the cover-art file already present in ``album_root``, or None."""
    if not album_root.is_dir():
        return None
    for ext in ("jpg", "jpeg", "png", "webp"):
        candidate = album_root / f"cover.{ext}"
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
    return None


def _existing_wav_files(
    work_dir: Path, track_total: int, selected_tracks: list[int]
) -> list[Path] | None:
    """Return the WAV files in ``work_dir`` for resume, or None if any are missing.

    Naming matches ``rip_audio``'s ``_wav_name_for_track`` so reuse is exact.
    """
    from .rip import _is_nonempty_file, _wav_name_for_track

    if not work_dir.is_dir() or not selected_tracks:
        return None
    candidates = [work_dir / _wav_name_for_track(num, track_total) for num in selected_tracks]
    if all(_is_nonempty_file(p) for p in candidates):
        return candidates
    return None


def _audio_formats(outputs: OutputSelection) -> list[tuple[str, str]]:
    formats: list[tuple[str, str]] = []
    if outputs.flac:
        formats.append(("flac", "FLAC"))
    if outputs.mp3:
        formats.append(("mp3", "MP3"))
    if outputs.ogg:
        formats.append(("ogg", "OGG Vorbis"))
    if outputs.opus:
        formats.append(("opus", "Opus"))
    if outputs.alac:
        formats.append(("alac", "ALAC"))
    if outputs.aac:
        formats.append(("aac", "AAC/M4A"))
    if outputs.wav:
        formats.append(("wav", "WAV"))
    return formats


def _output_stage_label(fmt_key: str, fmt_name: str) -> str:
    action = "Saving" if fmt_key == "wav" else "Encoding"
    return f"{action} tracks to {fmt_name} format"


def _ensure_output_dir(
    fmt_key: str,
    fl_dir: Path,
    mp_dir: Path,
    og_dir: Path,
    op_dir: Path,
    al_dir: Path,
    aa_dir: Path,
    wa_dir: Path,
) -> Path:
    return {
        "flac": fl_dir,
        "mp3": mp_dir,
        "ogg": og_dir,
        "opus": op_dir,
        "alac": al_dir,
        "aac": aa_dir,
        "wav": wa_dir,
    }[fmt_key]


def _progress_callback(
    callbacks: BackupCallbacks,
    which: str,
) -> Callable[[int, int, str], None] | None:
    if callbacks.stage_progress is None:
        return None

    def _callback(current: int, total: int, label: str) -> None:
        callbacks.stage_progress(which, current, total, label)

    return _callback


def _audio_progress_callback(callbacks: BackupCallbacks) -> Callable[[int, int, str], None] | None:
    if callbacks.stage_progress is None:
        return None

    def _callback(current: int, total: int, fname: str = "") -> None:
        label = f"Ripping audio tracks ({current}/{total})"
        if fname:
            label = f"{label}: {fname}"
        # Report tracks *completed* (current - 1) so the bar only reaches 100%
        # when stage_done fires, not while the last track is still being ripped.
        callbacks.stage_progress("rip", current - 1, max(total, 1), label)

    return _callback


def _encode_progress_callback(
    callbacks: BackupCallbacks,
    which: str,
    stage_label: str,
) -> Callable[[int, int], None] | None:
    if callbacks.stage_progress is None:
        return None

    def _callback(done: int, total: int) -> None:
        callbacks.stage_progress(which, done, max(total, 1), f"{stage_label} ({done}/{total})")

    return _callback


def _set_process(callbacks: BackupCallbacks, proc: object | None) -> None:
    if callbacks.set_process is not None:
        callbacks.set_process(proc)


def _stage_start(callbacks: BackupCallbacks, which: str, label: str, total: int | None) -> None:
    if callbacks.stage_start is not None:
        callbacks.stage_start(which, label, total)


def _stage_done(callbacks: BackupCallbacks, which: str, label: str) -> None:
    if callbacks.stage_done is not None:
        callbacks.stage_done(which, label)


def _info(callbacks: BackupCallbacks, message: str) -> None:
    if callbacks.info is not None:
        callbacks.info(message)


def _warn(callbacks: BackupCallbacks, message: str) -> None:
    _warn_raw(callbacks.warn, message)


def _warn_raw(warn: Callable[[str], None] | None, message: str) -> None:
    if warn is not None:
        warn(message)


def _success(callbacks: BackupCallbacks, message: str) -> None:
    if callbacks.success is not None:
        callbacks.success(message)
