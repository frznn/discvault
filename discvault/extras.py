"""Extra-file scanning and extraction for supported data tracks."""
from __future__ import annotations

import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Callable

from .metadata.sanitize import sanitize_component
from .tracks import possible_data_track_numbers

if TYPE_CHECKING:
    from .cleanup import Cleanup
    from .config import Config
    from .metadata.types import DiscInfo, Metadata


_ISO_SECTOR_SIZE = 2048
_JOLIET_ESCAPES = (b"%/@", b"%/C", b"%/E")


@dataclass(frozen=True)
class ExtraFileEntry:
    path: str
    size: int


@dataclass
class ExtraScanBundle:
    entries: tuple[ExtraFileEntry, ...]
    detail: str
    track_number: int | None = None
    iso_path: Path | None = None
    mount_root: Path | None = None
    _workspace: tempfile.TemporaryDirectory[str] | None = None

    def close(self) -> None:
        if self._workspace is None:
            return
        try:
            self._workspace.cleanup()
        except Exception:
            pass


def probe_disc_extras(device: str) -> tuple[ExtraScanBundle | None, str]:
    """Return a mounted extra-file bundle when the OS already exposes a data filesystem."""
    mount_root = _find_mounted_data_root(device)
    if mount_root is None:
        return None, ""

    try:
        entries = list_mounted_extra_files(mount_root)
    except OSError as exc:
        return None, f"Extras probe failed: {exc}"

    if not entries:
        return None, ""

    detail = f"Found {len(entries)} extra file(s) on the mounted data session."
    return ExtraScanBundle(
        entries=tuple(entries),
        detail=detail,
        mount_root=mount_root,
    ), detail


@dataclass(frozen=True)
class _IsoEntry:
    path: str
    extent: int
    size: int


def scan_disc_extras(
    device: str,
    disc_info: "DiscInfo",
    cfg: "Config",
    *,
    meta: "Metadata | None" = None,
    work_dir: Path,
    debug: bool = False,
    process_callback: Callable[[object | None], None] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[ExtraScanBundle | None, str]:
    """Build a temporary ISO for the supported data track and list its files."""
    from . import rip as rip_mod

    mounted_bundle, mounted_detail = probe_disc_extras(device)
    if mounted_bundle is not None:
        return mounted_bundle, mounted_detail

    explicit_data_tracks = disc_info.data_track_numbers
    track_candidates = possible_data_track_numbers(disc_info, meta)
    if not track_candidates:
        return None, "Extras unavailable: disc has no data track."
    if explicit_data_tracks and len(explicit_data_tracks) != 1:
        return None, "Extras unavailable: supports discs with exactly one data track."
    if not disc_info.track_offsets or disc_info.track_count <= 0:
        return None, "Extras unavailable: disc layout is incomplete."

    work_dir.mkdir(parents=True, exist_ok=True)
    workspace = tempfile.TemporaryDirectory(prefix="discvault-extras-", dir=str(work_dir))
    temp_root = Path(workspace.name)
    bin_path = temp_root / "extras.bin"
    toc_path = temp_root / "extras.toc"
    iso_path = temp_root / "extras.iso"

    def _fail(detail: str) -> tuple[ExtraScanBundle | None, str]:
        workspace.cleanup()
        return None, detail

    try:
        if cfg.image_ripper == "readom":
            ok, detail = rip_mod.rip_image_readom(
                device,
                bin_path,
                disc_info,
                cleanup=_NoopCleanup(),
                debug=debug,
                process_callback=process_callback,
                progress_callback=progress_callback,
            )
            toc_file: Path | None = None
        else:
            ok, detail = rip_mod.rip_image(
                device,
                toc_path,
                bin_path,
                cleanup=_NoopCleanup(),
                command_template=cfg.cdrdao_command,
                debug=debug,
                process_callback=process_callback,
                progress_callback=progress_callback,
                track_count=disc_info.track_count,
                track_offsets=disc_info.track_offsets,
                leadout=disc_info.leadout,
            )
            toc_file = toc_path
        if not ok:
            return _fail(detail or "Extras scan failed while reading the disc.")

        chosen_track: int | None = None
        entries: list[ExtraFileEntry] = []
        failures: list[str] = []

        for track_no in track_candidates:
            exported_iso, detail = rip_mod.export_iso_from_bin(
                iso_path,
                bin_path,
                disc_info,
                toc_path=toc_file,
                track_no=track_no,
            )
            if exported_iso is None:
                failures.append(f"track {track_no}: {detail or 'could not export'}")
                iso_path.unlink(missing_ok=True)
                continue

            try:
                entries = list_extra_files(exported_iso)
            except OSError as exc:
                failures.append(f"track {track_no}: {exc}")
                iso_path.unlink(missing_ok=True)
                continue

            if not entries:
                failures.append(f"track {track_no}: no files found")
                iso_path.unlink(missing_ok=True)
                continue

            chosen_track = track_no
            break

        if chosen_track is None:
            detail = _scan_failure_detail(failures)
            return _fail(detail)

        bin_path.unlink(missing_ok=True)
        if toc_file is not None:
            toc_file.unlink(missing_ok=True)

        label = "data track" if chosen_track in explicit_data_tracks else "track"
        detail = f"Found {len(entries)} extra file(s) on {label} {chosen_track}."
        return ExtraScanBundle(
            entries=tuple(entries),
            detail=detail,
            track_number=chosen_track,
            iso_path=exported_iso,
            _workspace=workspace,
        ), detail
    except Exception:
        workspace.cleanup()
        raise


def _scan_failure_detail(failures: list[str]) -> str:
    if not failures:
        return "Extras scan found no supported files."
    if len(failures) == 1:
        return f"Extras scan failed: {failures[0]}"
    preview = "; ".join(failures[:2])
    if len(failures) > 2:
        preview = f"{preview}; ..."
    return f"Extras scan failed: {preview}"


def list_extra_files(iso_path: Path) -> list[ExtraFileEntry]:
    """Return extractable files from an ISO image."""
    return [ExtraFileEntry(path=entry.path, size=entry.size) for entry in _read_iso_entries(iso_path)]


def list_mounted_extra_files(root: Path) -> list[ExtraFileEntry]:
    """Return extra files from an already-mounted data session."""
    if not root.exists() or not root.is_dir():
        raise OSError(f"Mounted extras root is unavailable: {root}")

    entries: list[ExtraFileEntry] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(root).as_posix()
        try:
            size = path.stat().st_size
        except OSError:
            continue
        entries.append(ExtraFileEntry(path=rel_path, size=size))
    entries.sort(key=lambda entry: entry.path.casefold())
    return entries


def copy_extra_files(
    iso_path: Path,
    selected_paths: list[str],
    extras_dir: Path,
    *,
    cleanup: "Cleanup | None" = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Path] | None, str]:
    """Copy the selected extra files from *iso_path* into *extras_dir*."""
    wanted = list(dict.fromkeys(path for path in selected_paths if path))
    if not wanted:
        return [], ""

    entries = {entry.path: entry for entry in _read_iso_entries(iso_path)}
    missing = [path for path in wanted if path not in entries]
    if missing:
        sample = ", ".join(missing[:3])
        if len(missing) > 3:
            sample = f"{sample}, ..."
        return None, f"Extras copy failed: missing ISO entries ({sample})."

    created_root = not extras_dir.exists()
    extras_dir.mkdir(parents=True, exist_ok=True)
    if cleanup is not None:
        cleanup.track_dir(extras_dir, created=created_root)

    copied: list[Path] = []
    used_destinations: set[Path] = set()
    total = len(wanted)

    try:
        with iso_path.open("rb") as handle:
            for index, source_path in enumerate(wanted, start=1):
                entry = entries[source_path]
                rel_path = _safe_destination_path(source_path)
                dest_path = _claim_destination(extras_dir, rel_path, used_destinations)
                _ensure_parent_dirs(dest_path.parent, cleanup)
                if cleanup is not None:
                    cleanup.track_file(dest_path, created=not dest_path.exists())
                _copy_iso_entry(handle, entry, dest_path)
                copied.append(dest_path)
                if progress_callback is not None:
                    progress_callback(
                        index,
                        total,
                        f"Copying extras ({index}/{total}): {PurePosixPath(source_path).name}",
                    )
    except OSError as exc:
        return None, f"Extras copy failed: {exc}"

    return copied, ""


def copy_mounted_extra_files(
    mount_root: Path,
    selected_paths: list[str],
    extras_dir: Path,
    *,
    cleanup: "Cleanup | None" = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> tuple[list[Path] | None, str]:
    """Copy selected extra files from a mounted data session."""
    wanted = list(dict.fromkeys(path for path in selected_paths if path))
    if not wanted:
        return [], ""

    created_root = not extras_dir.exists()
    extras_dir.mkdir(parents=True, exist_ok=True)
    if cleanup is not None:
        cleanup.track_dir(extras_dir, created=created_root)

    copied: list[Path] = []
    used_destinations: set[Path] = set()
    total = len(wanted)

    try:
        for index, source_path in enumerate(wanted, start=1):
            src_path = _mounted_source_path(mount_root, source_path)
            if not src_path.is_file():
                return None, f"Extras copy failed: missing mounted entry ({source_path})."

            rel_path = _safe_destination_path(source_path)
            dest_path = _claim_destination(extras_dir, rel_path, used_destinations)
            _ensure_parent_dirs(dest_path.parent, cleanup)
            if cleanup is not None:
                cleanup.track_file(dest_path, created=not dest_path.exists())
            shutil.copyfile(src_path, dest_path)
            copied.append(dest_path)
            if progress_callback is not None:
                progress_callback(
                    index,
                    total,
                    f"Copying extras ({index}/{total}): {PurePosixPath(source_path).name}",
                )
    except OSError as exc:
        return None, f"Extras copy failed: {exc}"

    return copied, ""


def human_size(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(max(size, 0))
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{int(size)} B"


def _find_mounted_data_root(device: str) -> Path | None:
    try:
        result = subprocess.run(
            ["findmnt", "-P", "-n", "-S", device, "-o", "TARGET,FSTYPE"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        try:
            fields = dict(part.split("=", 1) for part in shlex.split(line))
        except ValueError:
            continue
        fstype = fields.get("FSTYPE", "").lower()
        target = fields.get("TARGET", "")
        if fstype not in {"iso9660", "udf"} or not target:
            continue
        mount_root = Path(target)
        if mount_root.exists() and mount_root.is_dir():
            return mount_root
    return None


def _read_iso_entries(iso_path: Path) -> list[_IsoEntry]:
    with iso_path.open("rb") as handle:
        root_record, decode_name = _select_volume_root(handle)
        seen_dirs: set[tuple[int, int]] = set()
        entries = _walk_directory(handle, root_record, decode_name, parent="", seen_dirs=seen_dirs)
    entries.sort(key=lambda entry: entry.path.casefold())
    return entries


def _select_volume_root(
    handle: BinaryIO,
) -> tuple[bytes, Callable[[bytes], str]]:
    primary_root: bytes | None = None
    joliet_root: bytes | None = None

    sector = 16
    while True:
        descriptor = _read_sector(handle, sector)
        dtype = descriptor[0]
        ident = descriptor[1:6]
        if ident != b"CD001":
            sector += 1
            continue
        if dtype == 255:
            break
        if dtype == 1 and primary_root is None:
            primary_root = _root_record_from_descriptor(descriptor)
        elif dtype == 2 and descriptor[88:91] in _JOLIET_ESCAPES and joliet_root is None:
            joliet_root = _root_record_from_descriptor(descriptor)
        sector += 1

    if joliet_root is not None:
        return joliet_root, _decode_joliet_name
    if primary_root is not None:
        return primary_root, _decode_primary_name
    raise OSError("ISO image does not contain a readable volume descriptor.")


def _root_record_from_descriptor(descriptor: bytes) -> bytes:
    record_len = descriptor[156]
    if record_len <= 0:
        raise OSError("ISO image root directory record is missing.")
    return descriptor[156:156 + record_len]


def _walk_directory(
    handle: BinaryIO,
    record: bytes,
    decode_name: Callable[[bytes], str],
    *,
    parent: str,
    seen_dirs: set[tuple[int, int]],
) -> list[_IsoEntry]:
    extent = int.from_bytes(record[2:6], "little")
    size = int.from_bytes(record[10:14], "little")
    key = (extent, size)
    if key in seen_dirs:
        return []
    seen_dirs.add(key)

    raw = _read_extent(handle, extent, size)
    entries: list[_IsoEntry] = []
    offset = 0
    total = len(raw)

    while offset < total:
        record_len = raw[offset]
        if record_len == 0:
            offset = ((offset // _ISO_SECTOR_SIZE) + 1) * _ISO_SECTOR_SIZE
            continue
        record_bytes = raw[offset:offset + record_len]
        offset += record_len
        if len(record_bytes) < 34:
            continue

        name_len = record_bytes[32]
        name_bytes = record_bytes[33:33 + name_len]
        if name_bytes in (b"\x00", b"\x01"):
            continue

        name = _clean_iso_name(decode_name(name_bytes))
        if not name:
            continue

        flags = record_bytes[25]
        child_extent = int.from_bytes(record_bytes[2:6], "little")
        child_size = int.from_bytes(record_bytes[10:14], "little")
        child_path = f"{parent}/{name}" if parent else name

        if flags & 0x02:
            entries.extend(
                _walk_directory(
                    handle,
                    record_bytes,
                    decode_name,
                    parent=child_path,
                    seen_dirs=seen_dirs,
                )
            )
            continue

        if child_extent <= 0 or child_size < 0:
            continue
        entries.append(_IsoEntry(path=child_path, extent=child_extent, size=child_size))

    return entries


def _clean_iso_name(name: str) -> str:
    name = name.strip().replace("\\", "/")
    if ";" in name:
        name = name.split(";", 1)[0]
    if name.endswith("."):
        name = name[:-1]
    return name.strip()


def _decode_primary_name(raw: bytes) -> str:
    return raw.decode("ascii", errors="replace")


def _decode_joliet_name(raw: bytes) -> str:
    return raw.decode("utf-16-be", errors="replace")


def _read_sector(handle: BinaryIO, sector: int) -> bytes:
    handle.seek(sector * _ISO_SECTOR_SIZE)
    data = handle.read(_ISO_SECTOR_SIZE)
    if len(data) != _ISO_SECTOR_SIZE:
        raise OSError("Unexpected end of ISO image.")
    return data


def _read_extent(handle: BinaryIO, extent: int, size: int) -> bytes:
    handle.seek(extent * _ISO_SECTOR_SIZE)
    data = handle.read(size)
    if len(data) != size:
        raise OSError("Unexpected end of ISO directory data.")
    return data


def _copy_iso_entry(handle: BinaryIO, entry: _IsoEntry, dest_path: Path) -> None:
    handle.seek(entry.extent * _ISO_SECTOR_SIZE)
    remaining = entry.size
    with dest_path.open("wb") as out:
        while remaining > 0:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise OSError(f"Unexpected end of ISO image while copying {entry.path}.")
            out.write(chunk)
            remaining -= len(chunk)


def _mounted_source_path(root: Path, source_path: str) -> Path:
    parts = [
        part
        for part in PurePosixPath(source_path).parts
        if part not in ("", ".", "/")
    ]
    if not parts or any(part == ".." for part in parts):
        raise OSError(f"Invalid mounted extras path: {source_path}")
    return root.joinpath(*parts)


def _safe_destination_path(source_path: str) -> Path:
    parts: list[str] = []
    for part in PurePosixPath(source_path).parts:
        if part in ("", ".", "..", "/"):
            continue
        parts.append(sanitize_component(part))
    if not parts:
        parts = ["Unknown"]
    return Path(*parts)


def _claim_destination(root: Path, rel_path: Path, used_destinations: set[Path]) -> Path:
    candidate = root / rel_path
    if candidate not in used_destinations:
        used_destinations.add(candidate)
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        alt = candidate.with_name(f"{stem}-{counter}{suffix}")
        if alt not in used_destinations:
            used_destinations.add(alt)
            return alt
        counter += 1


def _ensure_parent_dirs(path: Path, cleanup: "Cleanup | None") -> None:
    if path == path.parent:
        return
    pending: list[Path] = []
    current = path
    while not current.exists() and current != current.parent:
        pending.append(current)
        current = current.parent
    for directory in reversed(pending):
        directory.mkdir(exist_ok=True)
        if cleanup is not None:
            cleanup.track_dir(directory, created=True)


class _NoopCleanup:
    def track_file(self, path: str | Path, *, created: bool | None = None) -> Path:
        return Path(path)

    def track_dir(self, path: str | Path, *, created: bool | None = None) -> Path:
        return Path(path)
