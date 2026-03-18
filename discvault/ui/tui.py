"""Full Textual TUI for discvault."""
from __future__ import annotations

import datetime
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.containers import ScrollableContainer
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    RichLog,
    Static,
)
from textual import on, work

if TYPE_CHECKING:
    from ..config import Config
    from ..metadata.types import Metadata, DiscInfo

from ..tracks import compact_track_list, default_selected_tracks, parse_track_spec, resolve_selected_tracks
from .import_prompt import ImportPromptScreen
from .settings import ConfigScreen


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
Screen {
    background: $background;
}

#metadata-box {
    height: auto;
    margin: 1 1 1 1;
    padding: 0 1;
    border: round $surface;
}

#sources-row {
    height: auto;
    min-height: 1;
    margin: 0;
    padding: 0;
    align: left middle;
}

#sources-lbl {
    width: auto;
    padding: 0 1 0 0;
    color: $text-muted;
}

#sources-row Checkbox {
    width: auto;
    min-width: 0;
    margin-right: 1;
}

#metadata-actions-row {
    height: auto;
    min-height: 1;
    margin: 1 0 0 0;
    align: left middle;
}

#btn-more {
    min-width: 16;
    margin-right: 2;
}

#btn-import-file {
    min-width: 12;
    margin-right: 1;
}

#btn-import-url {
    min-width: 12;
}

#status-log {
    height: 6;
    margin: 1 1;
    border: round $surface;
}

/* --- ready phase --- */
#candidates-section {
    height: 6;
    margin: 0 1;
    border: round $surface;
    display: none;
}

#tracklist-scroll {
    height: auto;
    max-height: 16;
    margin: 0 1;
    border: round $surface;
    display: none;
}

#tracklist-section {
    padding: 0 1;
    height: auto;
}

.track-row {
    height: auto;
    min-height: 1;
    align: left middle;
    margin-bottom: 1;
}

.track-enable {
    width: auto;
    min-width: 0;
    margin-right: 1;
}

.track-no {
    width: 4;
    color: $text-muted;
}

.track-title {
    width: 2fr;
}

.track-artist {
    width: 1fr;
    margin-left: 1;
}

.track-len {
    width: 8;
    color: $text-muted;
    padding-left: 1;
}

.track-kind {
    width: 6;
    color: $warning;
    padding-left: 1;
}

.track-placeholder {
    color: $text-muted;
}

#tags-row {
    height: auto;
    min-height: 1;
    margin: 0 1;
    align: left middle;
    display: none;
}

.tag-lbl {
    width: auto;
    padding: 0 1 0 0;
}

#input-artist { width: 1fr; margin-right: 2; }
#input-album  { width: 1fr; margin-right: 2; }
#input-year   { width: 12; }

#target-label {
    height: 1;
    margin: 1 2;
    color: $text-muted;
    display: none;
}

#cover-art-label {
    height: 1;
    margin: 0 2 1 2;
    color: $text-muted;
    display: none;
}

#outputs-row {
    height: auto;
    min-height: 1;
    margin: 0 1;
    padding: 0;
    align: left middle;
    display: none;
}

#outputs-row Checkbox {
    width: auto;
    min-width: 0;
    margin-right: 1;
}

/* --- running phase --- */
#progress-section {
    margin: 0 1;
    padding: 0 1;
    display: none;
}

.prog-row {
    display: none;
}

.prog-lbl {
    height: 1;
    margin-top: 0;
    color: $text-muted;
}

/* --- done phase --- */
#done-section {
    margin: 1 2;
    display: none;
}

#done-title {
    height: 2;
    color: $success;
    text-style: bold;
}

#done-details {
    height: auto;
    color: $text-muted;
}

/* --- outer layout wrapper (fills between header and footer) --- */
#outer {
    height: 1fr;
}

/* --- scrollable content wrapper --- */
#main-scroll {
    height: 1fr;
    overflow-y: auto;
}

/* --- action bar --- */
#action-bar {
    height: auto;
    align: left middle;
    padding: 0 2;
    margin-bottom: 1;
    border-top: solid $surface;
    background: $background;
}

#action-right {
    width: 1fr;
    height: auto;
    align: right middle;
}

#btn-config { min-width: 12; }
#btn-target { min-width: 14; margin-left: 1; }
#btn-eject  { min-width: 12; margin-left: 2; }
#btn-start  { min-width: 12; margin-left: 2; }
#btn-cancel { min-width: 12; margin-left: 2; }
"""


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def _folder_open_command(path: Path) -> list[str] | None:
    """Return the best available command to open a folder in the file manager."""
    if shutil.which("xdg-open"):
        return ["xdg-open", str(path)]
    if shutil.which("gio"):
        return ["gio", "open", str(path)]
    if shutil.which("open"):
        return ["open", str(path)]
    return None


_PROGRESS_KEYS = ("image", "iso", "rip", "flac", "mp3", "ogg", "opus", "alac", "aac", "wav")


def _output_stage_label(fmt_key: str, fmt_name: str) -> str:
    action = "Saving" if fmt_key == "wav" else "Encoding"
    return f"{action} tracks to {fmt_name} format"

class DiscvaultApp(App[None]):
    """Full discvault TUI."""

    CSS = _CSS
    TITLE = "DiscVault"
    COMMAND_PALETTE_BINDING = "ctrl+k"

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", priority=True),
        Binding("escape", "cancel_or_quit", "Cancel / Quit"),
        Binding("ctrl+comma", "open_settings", "Settings", show=False),
        Binding(
            "ctrl+k",
            "command_palette",
            "",
            show=False,
            key_display="Commands",
            tooltip="Open commands",
            priority=True,
        ),
        Binding("f5", "refresh_meta", "Re-fetch metadata", show=False),
    ]

    # Current phase: init | detecting | ready | running | done | error
    phase: reactive[str] = reactive("init")

    def __init__(self, args, cfg: "Config") -> None:
        super().__init__()
        self._args = args
        self._cfg = cfg
        self._disc_info: DiscInfo | None = None
        self._disc_signature: tuple | None = None
        self._watch_disc_present: bool | None = None
        self._disc_watch_busy = False
        self._disc_watch_timer = None
        self._candidates: list[Metadata] = []
        self._manual_meta: Metadata | None = None
        self._selected_idx: int = 0
        self._selected_tracks: dict[int, bool] = {}
        try:
            self._requested_tracks = (
                parse_track_spec(args.tracks) if getattr(args, "tracks", "") else None
            )
        except ValueError:
            self._requested_tracks = None
        self._current_proc: subprocess.Popen | None = None
        self._operation_busy = False  # guard against overlapping fetch/rip actions
        self._target_open_busy = False
        self._shutting_down = False
        self._last_meta_fetch_all_sources = True
        self._last_accuraterip_status = ""
        # Source enable/disable — initialized from preferred_metadata_source config
        preferred = cfg.preferred_metadata_source or "musicbrainz"
        self._src_mb = (preferred == "musicbrainz")
        self._src_gnudb = (preferred == "gnudb")
        self._src_cdtext = (preferred == "cdtext")
        self._src_discogs = (preferred == "discogs")
        self._metadata_file_path = getattr(args, "metadata_file", "") or ""
        self._metadata_url = getattr(args, "metadata_url", getattr(args, "bandcamp_url", "")) or ""
        self._auto_import_file_pending = bool(self._metadata_file_path)
        self._auto_import_url_pending = bool(self._metadata_url)
        from ..cleanup import Cleanup
        self._cleanup = Cleanup()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        with Vertical(id="outer"):
            with ScrollableContainer(id="main-scroll"):
                # Always-visible status log
                yield RichLog(id="status-log", highlight=True, markup=True, max_lines=200)

                with Vertical(id="metadata-box"):
                    # Metadata source toggles
                    with Horizontal(id="sources-row"):
                        yield Label("Metadata Sources:", id="sources-lbl")
                        yield Checkbox("MusicBrainz", value=self._src_mb, id="chk-src-mb", compact=True)
                        yield Checkbox("GnuDB", value=self._src_gnudb, id="chk-src-gnudb", compact=True)
                        yield Checkbox("CD-Text", value=self._src_cdtext, id="chk-src-cdtext", compact=True)
                        yield Checkbox(self._discogs_source_label(), value=self._src_discogs, id="chk-src-discogs", compact=True)

                    with Horizontal(id="metadata-actions-row"):
                        yield Button("Fetch Metadata", id="btn-more", disabled=True)
                        yield Button("Import File", id="btn-import-file", disabled=True)
                        yield Button("Import URL", id="btn-import-url", disabled=True)

                # Ready phase: candidates table
                with Vertical(id="candidates-section"):
                    yield DataTable(id="meta-table", cursor_type="row", zebra_stripes=True)

                # Ready phase: tag inputs
                with Horizontal(id="tags-row"):
                    yield Label("Artist", classes="tag-lbl")
                    yield Input(placeholder="Artist", id="input-artist", compact=True)
                    yield Label("Album", classes="tag-lbl")
                    yield Input(placeholder="Album", id="input-album", compact=True)
                    yield Label("Year", classes="tag-lbl")
                    yield Input(placeholder="Year", id="input-year", max_length=4, compact=True)

                # Ready phase: tracklist of selected candidate (scrollable)
                with ScrollableContainer(id="tracklist-scroll"):
                    yield Vertical(id="tracklist-section")

                # Ready phase: output checkboxes
                mp3_label = f"MP3 {self._args.mp3_bitrate} kbps" if self._args.mp3_bitrate > 0 else "MP3 VBR"
                with Horizontal(id="outputs-row"):
                    yield Checkbox("Disc image", value=not self._args.no_image, id="chk-image", compact=True)
                    yield Checkbox("ISO data", value=getattr(self._args, "iso", False), id="chk-iso", compact=True)
                    yield Checkbox(f"FLAC lvl {self._args.flac_compression}", value=not self._args.no_flac, id="chk-flac", compact=True)
                    yield Checkbox(mp3_label, value=not self._args.no_mp3, id="chk-mp3", compact=True)
                    yield Checkbox("OGG Vorbis", value=getattr(self._args, "ogg", False), id="chk-ogg", compact=True)
                    yield Checkbox(f"Opus {self._cfg.opus_bitrate} kbps", value=getattr(self._args, "opus", False), id="chk-opus", compact=True)
                    yield Checkbox("ALAC", value=getattr(self._args, "alac", False), id="chk-alac", compact=True)
                    yield Checkbox(f"AAC {self._cfg.aac_bitrate} kbps", value=getattr(self._args, "aac", False), id="chk-aac", compact=True)
                    yield Checkbox("WAV copy", value=getattr(self._args, "wav", False), id="chk-wav", compact=True)

                yield Label("", id="target-label", markup=True)
                yield Label("", id="cover-art-label", markup=True)

                # Running phase: progress bars
                with Vertical(id="progress-section"):
                    with Vertical(id="prog-image-row", classes="prog-row"):
                        yield Label("", id="prog-image-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-image", show_eta=False)
                    with Vertical(id="prog-iso-row", classes="prog-row"):
                        yield Label("", id="prog-iso-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-iso", show_eta=False)
                    with Vertical(id="prog-rip-row", classes="prog-row"):
                        yield Label("", id="prog-rip-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-rip", show_eta=False)
                    with Vertical(id="prog-flac-row", classes="prog-row"):
                        yield Label("", id="prog-flac-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-flac", show_eta=False)
                    with Vertical(id="prog-mp3-row", classes="prog-row"):
                        yield Label("", id="prog-mp3-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-mp3", show_eta=False)
                    with Vertical(id="prog-ogg-row", classes="prog-row"):
                        yield Label("", id="prog-ogg-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-ogg", show_eta=False)
                    with Vertical(id="prog-opus-row", classes="prog-row"):
                        yield Label("", id="prog-opus-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-opus", show_eta=False)
                    with Vertical(id="prog-alac-row", classes="prog-row"):
                        yield Label("", id="prog-alac-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-alac", show_eta=False)
                    with Vertical(id="prog-aac-row", classes="prog-row"):
                        yield Label("", id="prog-aac-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-aac", show_eta=False)
                    with Vertical(id="prog-wav-row", classes="prog-row"):
                        yield Label("", id="prog-wav-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-wav", show_eta=False)

                # Done phase: summary
                with Vertical(id="done-section"):
                    yield Label("", id="done-title", markup=True)
                    yield Static("", id="done-details", markup=True)

            # Action bar — inside #outer, always visible below the scroll area
            with Horizontal(id="action-bar"):
                yield Button("Settings", id="btn-config")
                yield Button("Open Target", id="btn-target", disabled=True)
                with Horizontal(id="action-right"):
                    yield Button("Eject CD", id="btn-eject", disabled=True)
                    yield Button("Start", id="btn-start", variant="success", disabled=True)
                    yield Button("Quit", id="btn-cancel", variant="error")

        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.phase = "detecting"
        self._log(f"[bold]discvault[/bold] starting up...")
        self._disc_watch_timer = self.set_interval(4.0, self._schedule_disc_watch)
        self._refresh_eject_button()
        self._refresh_target_button()
        self._refresh_import_buttons()
        self._start_detection(self._sources_dict(from_ui=True))

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        if event.state == WorkerState.ERROR:
            self._log(
                f"[bold red]✗ Worker '{event.worker.name}' error: "
                f"{event.worker.error}[/bold red]"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str) -> None:
        log = self.query_one("#status-log", RichLog)
        log.write(msg)
        log.scroll_end(animate=False)

    def _tlog(self, msg: str) -> None:
        """Thread-safe log."""
        self.call_from_thread(self._log, msg)

    def _disc_sig(self, disc_info: "DiscInfo") -> tuple:
        return (
            disc_info.device,
            disc_info.freedb_disc_id,
            disc_info.mb_disc_id,
            disc_info.track_count,
            tuple(disc_info.track_offsets),
            disc_info.leadout,
            tuple(sorted(disc_info.track_modes.items())),
        )

    def _show(self, widget_id: str) -> None:
        self.query_one(f"#{widget_id}").styles.display = "block"

    def _hide(self, widget_id: str) -> None:
        self.query_one(f"#{widget_id}").styles.display = "none"

    def _input_val(self, widget_id: str) -> str:
        try:
            return self.query_one(f"#{widget_id}", Input).value.strip()
        except Exception:
            return ""

    def _checkbox_val(self, widget_id: str) -> bool:
        try:
            return self.query_one(f"#{widget_id}", Checkbox).value
        except Exception:
            return False

    def _manual_search_hints(self) -> tuple[str, str, str]:
        return (
            self._input_val("input-artist"),
            self._input_val("input-album"),
            self._input_val("input-year"),
        )

    def _metadata_file_value(self) -> str:
        return self._metadata_file_path

    def _metadata_url_value(self) -> str:
        return self._metadata_url

    def _has_manual_search_terms(self) -> bool:
        artist, album, _year = self._manual_search_hints()
        return bool(artist and album)

    def _track_is_audio(self, track_number: int) -> bool:
        return self._disc_info.is_audio_track(track_number) if self._disc_info else True

    def _sync_track_selection(self) -> None:
        if self._disc_info is None:
            self._selected_tracks = {}
            return

        if self._requested_tracks is None:
            defaults = set(default_selected_tracks(self._disc_info))
        else:
            defaults = set(resolve_selected_tracks(self._disc_info, self._requested_tracks))
        self._selected_tracks = {
            track_number: self._selected_tracks.get(track_number, track_number in defaults)
            for track_number in range(1, self._disc_info.track_count + 1)
        }
        for track_number in list(self._selected_tracks):
            if not self._track_is_audio(track_number):
                self._selected_tracks[track_number] = False

    def _selected_audio_tracks(self) -> list[int]:
        if self._disc_info is None:
            return sorted(track for track, enabled in self._selected_tracks.items() if enabled)
        self._sync_track_selection()
        return [
            track_number
            for track_number in range(1, self._disc_info.track_count + 1)
            if self._selected_tracks.get(track_number, False) and self._track_is_audio(track_number)
        ]

    def _discogs_source_label(self) -> str:
        return "Discogs"

    def _set_tracklist_message(self, message: str) -> None:
        container = self.query_one("#tracklist-section", Vertical)
        container.remove_children()
        container.mount(Static(message, markup=True, classes="track-placeholder"))

    def _current_meta(self) -> Metadata | None:
        if self._candidates and 0 <= self._selected_idx < len(self._candidates):
            return self._candidates[self._selected_idx]
        return self._manual_meta

    def _manual_meta_or_create(self) -> Metadata:
        from ..metadata.types import Metadata as MetaType

        if self._manual_meta is None:
            self._manual_meta = MetaType(
                source="Manual",
                album_artist=self._input_val("input-artist"),
                album=self._input_val("input-album"),
                year=self._input_val("input-year"),
            )
        self._ensure_meta_tracks(self._manual_meta)
        return self._manual_meta

    def _ensure_meta_tracks(self, meta: Metadata) -> list:
        from ..metadata.types import Track

        total_tracks = 0
        if self._disc_info is not None:
            total_tracks = self._disc_info.track_count
        if total_tracks <= 0 and meta.tracks:
            total_tracks = max(t.number for t in meta.tracks)

        if total_tracks <= 0:
            meta.tracks = sorted(meta.tracks, key=lambda track: track.number)
            return meta.tracks

        existing = {track.number: track for track in meta.tracks}
        meta.tracks = [
            existing.get(number)
            or Track(
                number=number,
                title="DATA" if self._disc_info and not self._disc_info.is_audio_track(number) else "",
                artist="",
            )
            for number in range(1, total_tracks + 1)
        ]
        for track in meta.tracks:
            if self._disc_info and not self._disc_info.is_audio_track(track.number) and not track.title:
                track.title = "DATA"
        return meta.tracks

    def _render_track_editor(self, meta: Metadata | None) -> None:
        container = self.query_one("#tracklist-section", Vertical)
        container.remove_children()

        if meta is None:
            self._set_tracklist_message("[dim](no track information)[/dim]")
            return

        tracks = self._ensure_meta_tracks(meta)
        if not tracks:
            self._set_tracklist_message("[dim](no track information)[/dim]")
            return

        self._sync_track_selection()
        track_lengths = self._disc_info.track_lengths if self._disc_info else {}
        rows = []
        for track in tracks:
            secs = track_lengths.get(track.number, 0)
            length = f"{secs // 60}:{secs % 60:02d}" if secs else ""
            is_audio = self._track_is_audio(track.number)
            kind = "" if is_audio else "DATA"
            rows.append(
                Horizontal(
                    Checkbox(
                        "",
                        value=self._selected_tracks.get(track.number, is_audio),
                        id=f"track-enabled-{track.number}",
                        classes="track-enable",
                        disabled=not is_audio,
                        compact=True,
                    ),
                    Label(f"{track.number:02d}.", classes="track-no"),
                    Input(
                        value=track.title,
                        placeholder="Title" if is_audio else "DATA",
                        id=f"track-title-{track.number}",
                        classes="track-title track-edit",
                        compact=True,
                        disabled=not is_audio,
                    ),
                    Input(
                        value=track.artist,
                        placeholder="Artist",
                        id=f"track-artist-{track.number}",
                        classes="track-artist track-edit",
                        compact=True,
                        disabled=not is_audio,
                    ),
                    Label(length, classes="track-len"),
                    Label(kind, classes="track-kind"),
                    classes="track-row",
                )
            )
        container.mount(*rows)

    def _resolve_device(self) -> str | None:
        from .. import device as dev_mod

        return self._args.device or (self._disc_info.device if self._disc_info else None) or dev_mod.detect()

    def _target_album_root(self) -> Path | None:
        from .. import library

        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        year = self._input_val("input-year")
        if not artist and not album:
            return None
        return library.album_root(self._cfg.base_dir, artist or "?", album or "?", year)

    def _openable_target_path(self) -> tuple[Path | None, bool]:
        target = self._target_album_root()
        if target is not None and target.exists():
            return target, True

        library_root = Path(self._cfg.base_dir).expanduser()
        if library_root.exists():
            return library_root, False
        return None, False

    def _refresh_eject_button(self) -> None:
        try:
            btn = self.query_one("#btn-eject", Button)
        except Exception:
            return

        btn.disabled = (
            self.phase not in {"ready", "done", "error"}
            or self._operation_busy
            or self._resolve_device() is None
        )
        self._refresh_target_button()

    def _refresh_target_button(self) -> None:
        try:
            btn = self.query_one("#btn-target", Button)
        except Exception:
            return

        path, _ = self._openable_target_path()
        btn.disabled = (
            self.phase not in {"ready", "done", "error"}
            or self._operation_busy
            or self._target_open_busy
            or path is None
            or _folder_open_command(path) is None
        )

    def _refresh_import_buttons(self) -> None:
        enabled = (
            self.phase in {"ready", "error"}
            and not self._operation_busy
            and self._disc_info is not None
        )
        try:
            file_btn = self.query_one("#btn-import-file", Button)
            file_btn.disabled = not enabled
        except Exception:
            pass
        try:
            url_btn = self.query_one("#btn-import-url", Button)
            url_btn.disabled = not enabled
        except Exception:
            pass

    def _sources_dict(self, *, from_ui: bool = False) -> dict[str, bool]:
        """Return current source flags.

        With ``from_ui=True`` this snapshots the checkbox values from the live UI
        and syncs the cached booleans. Without it, this stays thread-safe by only
        reading the cached values.
        """
        if from_ui:
            try:
                sources = {
                    "musicbrainz": self.query_one("#chk-src-mb", Checkbox).value,
                    "gnudb": self.query_one("#chk-src-gnudb", Checkbox).value,
                    "cdtext": self.query_one("#chk-src-cdtext", Checkbox).value,
                    "discogs": self.query_one("#chk-src-discogs", Checkbox).value,
                }
            except Exception:
                sources = {
                    "musicbrainz": self._src_mb,
                    "gnudb": self._src_gnudb,
                    "cdtext": self._src_cdtext,
                    "discogs": self._src_discogs,
                }
            self._src_mb = sources["musicbrainz"]
            self._src_gnudb = sources["gnudb"]
            self._src_cdtext = sources["cdtext"]
            self._src_discogs = sources["discogs"]
            return sources

        return {
            "musicbrainz": self._src_mb,
            "gnudb": self._src_gnudb,
            "cdtext": self._src_cdtext,
            "discogs": self._src_discogs,
        }

    @on(Checkbox.Changed, "#chk-src-mb")
    def _on_src_mb(self, event: Checkbox.Changed) -> None:
        self._src_mb = event.value

    @on(Checkbox.Changed, "#chk-src-gnudb")
    def _on_src_gnudb(self, event: Checkbox.Changed) -> None:
        self._src_gnudb = event.value

    @on(Checkbox.Changed, "#chk-src-cdtext")
    def _on_src_cdtext(self, event: Checkbox.Changed) -> None:
        self._src_cdtext = event.value

    @on(Checkbox.Changed, "#chk-src-discogs")
    def _on_src_discogs(self, event: Checkbox.Changed) -> None:
        self._src_discogs = event.value

    # ------------------------------------------------------------------
    # Phase 1 — detection + metadata fetch (background workers)
    # ------------------------------------------------------------------

    @work(thread=True, name="detect")
    def _start_detection(self, sources: dict[str, bool] | None = None) -> None:
        from .. import device as dev_mod, disc as disc_mod

        self._tlog("> Detecting CD device...")
        device = self._args.device or dev_mod.detect()
        if not device:
            self._tlog("[bold red]✗ No CD device found. Use --device.[/bold red]")
            self.call_from_thread(self._enter_error)
            return
        if not dev_mod.is_readable(device):
            self._tlog(f"[bold red]✗ {device}: no readable disc.[/bold red]")
            self.call_from_thread(self._enter_error)
            return
        self._tlog(f"[green]✓[/green] Device: [bold]{device}[/bold]")

        self._tlog("> Reading disc TOC...")
        try:
            disc_info = disc_mod.load_disc_info(device)
        except Exception as exc:
            self._tlog(f"[bold red]✗ Failed to read disc: {exc}[/bold red]")
            self.call_from_thread(self._enter_error)
            return
        disc_info.device = device
        self._disc_info = disc_info
        self._disc_signature = self._disc_sig(disc_info)
        self._watch_disc_present = True
        self._sync_track_selection()
        self._tlog(
            f"[green]✓[/green] [bold]{disc_info.track_count} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
        )
        if disc_info.data_track_numbers:
            self._tlog(
                "[yellow]![/yellow] Data track(s) detected and excluded by default: "
                f"{compact_track_list(disc_info.data_track_numbers)}"
            )

        try:
            self._run_meta_fetch(sources or self._sources_dict())
        except Exception as exc:
            self._tlog(f"[bold red]✗ Metadata error: {exc}[/bold red]")
            self.call_from_thread(self._enter_ready)

    def _run_meta_fetch(self, sources: dict, merge: bool = False) -> None:
        """Fetch metadata — runs in a worker thread (called from detect or meta worker).
        If merge=True, new results are added to existing candidates instead of replacing them.
        """
        from ..metadata import musicbrainz, gnudb, cdtext, local, discogs

        disc_info = self._disc_info
        if disc_info is None:
            self._tlog("[yellow]![/yellow] No disc info — insert a disc first.")
            self.call_from_thread(self._enter_ready)
            return

        cfg = self._cfg
        meta_debug = getattr(self._args, "metadata_debug", False) or self._args.debug
        timeout = cfg.metadata_timeout

        use_mb = sources.get("musicbrainz", True)
        use_gnudb = sources.get("gnudb", True)
        use_cdtext = sources.get("cdtext", True)
        use_discogs = sources.get("discogs", True)
        hint_artist, hint_album, hint_year = self._manual_search_hints()
        has_manual_terms = bool(hint_artist and hint_album)
        self._last_meta_fetch_all_sources = use_mb and use_gnudb and use_cdtext and use_discogs

        active = [k for k, v in sources.items() if v] or ["all"]
        self._tlog(f"> Fetching metadata ({', '.join(active)})...")

        candidates: list = list(self._candidates) if merge else []

        def _add(metas: list) -> None:
            for m in metas:
                if m not in candidates:
                    candidates.append(m)

        if cfg.use_local_cddb_cache and disc_info.freedb_disc_id:
            self._tlog("[dim]  → Local CDDB cache...[/dim]")
            try:
                r = local.lookup(disc_info, debug=meta_debug)
                _add(r)
                self._tlog(f"[dim]  ✓ Local CDDB cache: {len(r)} result(s)[/dim]")
            except Exception as exc:
                self._tlog(f"[dim]  ✗ Local CDDB cache: {exc}[/dim]")

        # MusicBrainz
        if use_mb:
            if disc_info.mb_disc_id or disc_info.mb_toc:
                self._tlog("[dim]  → MusicBrainz...[/dim]")
                try:
                    r = musicbrainz.lookup(disc_info, timeout=timeout, debug=meta_debug)
                    _add(r)
                    self._tlog(f"[dim]  ✓ MusicBrainz: {len(r)} result(s)[/dim]")
                except Exception as exc:
                    self._tlog(f"[dim]  ✗ MusicBrainz: {exc}[/dim]")
            elif not has_manual_terms:
                self._tlog("[dim]  · MusicBrainz: no disc ID[/dim]")
            if has_manual_terms:
                self._tlog("[dim]  → MusicBrainz search...[/dim]")
                try:
                    r = musicbrainz.search_releases(
                        hint_artist,
                        hint_album,
                        year=hint_year,
                        disc_info=disc_info,
                        timeout=timeout,
                        debug=meta_debug,
                    )
                    _add(r)
                    self._tlog(f"[dim]  ✓ MusicBrainz search: {len(r)} result(s)[/dim]")
                except Exception as exc:
                    self._tlog(f"[dim]  ✗ MusicBrainz search: {exc}[/dim]")

        # GnuDB HTTP
        if use_gnudb:
            if disc_info.freedb_disc_id:
                hello_values = gnudb.build_hello_values(
                    cfg.gnudb.hello_user, cfg.gnudb.hello_program, cfg.gnudb.hello_version
                )[:1]
                self._tlog("[dim]  → GnuDB HTTP...[/dim]")
                try:
                    r = gnudb.lookup_http(
                        disc_info,
                        hello_values,
                        timeout=timeout,
                        cache_enabled=cfg.use_local_cddb_cache,
                        debug=meta_debug,
                    )
                    _add(r)
                    self._tlog(f"[dim]  ✓ GnuDB HTTP: {len(r)} result(s)[/dim]")
                except Exception as exc:
                    self._tlog(f"[dim]  ✗ GnuDB HTTP: {exc}[/dim]")
                if cfg.gnudb.host:
                    self._tlog(f"[dim]  → GnuDB CDDBP ({cfg.gnudb.host})...[/dim]")
                    try:
                        r = gnudb.lookup_cddbp(
                            disc_info, hello_values,
                            host=cfg.gnudb.host, port=cfg.gnudb.port,
                            timeout=timeout,
                            cache_enabled=cfg.use_local_cddb_cache,
                            debug=meta_debug,
                        )
                        _add(r)
                        self._tlog(f"[dim]  ✓ GnuDB CDDBP: {len(r)} result(s)[/dim]")
                    except Exception as exc:
                        self._tlog(f"[dim]  ✗ GnuDB CDDBP: {exc}[/dim]")
            else:
                self._tlog("[dim]  · GnuDB: no FreeDB disc ID[/dim]")

        # CD-Text
        if use_cdtext:
            self._tlog("[dim]  → CD-Text...[/dim]")
            try:
                r = cdtext.lookup(
                    disc_info,
                    driver=cfg.cdrdao_driver,
                    timeout=timeout,
                    debug=meta_debug,
                )
                _add(r)
                self._tlog(f"[dim]  ✓ CD-Text: {len(r)} result(s)[/dim]")
            except Exception as exc:
                self._tlog(f"[dim]  ✗ CD-Text: {exc}[/dim]")

        if use_discogs:
            self._tlog("[dim]  → Discogs...[/dim]")
            if not cfg.discogs.token.strip():
                self._tlog(
                    "[dim]  · Discogs: using anonymous access; a token improves reliability and rate limits[/dim]"
                )
            if candidates or has_manual_terms:
                try:
                    r = discogs.lookup(
                        disc_info,
                        seed_candidates=candidates,
                        artist=hint_artist,
                        album=hint_album,
                        year=hint_year,
                        token=cfg.discogs.token,
                        timeout=timeout,
                        debug=meta_debug,
                    )
                    _add(r)
                    self._tlog(f"[dim]  ✓ Discogs: {len(r)} result(s)[/dim]")
                except Exception as exc:
                    self._tlog(f"[dim]  ✗ Discogs: {exc}[/dim]")
            else:
                self._tlog(
                    "[dim]  · Discogs: no search terms yet (fill Artist and Album to search manually)[/dim]"
                )

        self._candidates = candidates
        if candidates:
            self._tlog(
                f"[green]✓[/green] Found [bold]{len(candidates)}[/bold] metadata candidate(s)."
            )
        else:
            if self._last_meta_fetch_all_sources:
                if has_manual_terms:
                    self._tlog(
                        "[yellow]![/yellow] No metadata found — adjust Artist/Album and try again, or enter tags manually."
                    )
                else:
                    self._tlog(
                        "[yellow]![/yellow] No metadata found — enter Artist and Album above, then press Fetch Metadata to search MusicBrainz/Discogs, or enter tags manually."
                    )
            else:
                self._tlog(
                    "[yellow]![/yellow] No metadata found — try another source selection, or fill Artist and Album above and fetch again."
                )
        self.call_from_thread(self._enter_ready)

    @work(thread=True, name="meta")
    def _start_meta_fetch(self, sources: dict | None = None, merge: bool = False) -> None:
        """Re-fetch metadata (F5 / Fetch Metadata button). Runs in its own worker thread."""
        try:
            self._run_meta_fetch(sources or self._sources_dict(), merge=merge)
        except Exception as exc:
            self._tlog(f"[bold red]✗ Metadata error: {exc}[/bold red]")
            self.call_from_thread(self._enter_ready)

    @work(thread=True, name="meta-import")
    def _start_metadata_import(self, kind: str, value: str) -> None:
        from ..metadata import fileimport, urlimport

        disc_info = self._disc_info
        if disc_info is None:
            self._tlog("[yellow]![/yellow] No disc info — insert a disc first.")
            self.call_from_thread(self._enter_ready)
            return

        meta_debug = getattr(self._args, "metadata_debug", False) or self._args.debug
        timeout = self._cfg.metadata_timeout
        candidates = list(self._candidates)
        added_index: int | None = None

        try:
            if kind == "file":
                self._tlog(f"> Importing metadata file: [bold]{value}[/bold]")
                imported = fileimport.lookup(value, debug=meta_debug)
                source_label = "metadata file"
            elif kind == "url":
                self._tlog(f"> Importing metadata URL: [bold]{value}[/bold]")
                imported = urlimport.lookup_url(
                    value,
                    disc_info=disc_info,
                    timeout=timeout,
                    debug=meta_debug,
                )
                source_label = "metadata URL"
            else:
                raise ValueError(f"Unknown import kind: {kind}")
        except Exception as exc:
            self._tlog(f"[bold red]✗ Failed to import {kind}: {exc}[/bold red]")
            self.call_from_thread(self._enter_ready)
            return

        for meta in imported:
            if meta not in candidates:
                if added_index is None:
                    added_index = len(candidates)
                candidates.append(meta)

        self._candidates = candidates
        if added_index is not None:
            self._selected_idx = added_index

        if imported:
            self._tlog(
                f"[green]✓[/green] Imported [bold]{len(imported)}[/bold] candidate(s) from {source_label}."
            )
        else:
            self._tlog(f"[yellow]![/yellow] No metadata imported from {source_label}.")

        self.call_from_thread(self._enter_ready)

    # ------------------------------------------------------------------
    # Phase 2 — ready: show candidates + tags + outputs
    # ------------------------------------------------------------------

    def _enter_ready(self) -> None:
        self.phase = "ready"
        self._operation_busy = False
        self._sync_track_selection()
        table = self.query_one("#meta-table", DataTable)
        table.clear(columns=True)
        table.add_columns("#", "Source", "Artist", "Album", "Year", "Tracks")
        for i, m in enumerate(self._candidates, 1):
            self._ensure_meta_tracks(m)
            table.add_row(
                str(i), m.source,
                m.album_artist or "(unknown)", m.album or "(untitled)",
                m.year or "—", str(m.track_count),
            )
        if self._candidates:
            self._selected_idx = max(0, min(self._selected_idx, len(self._candidates) - 1))
            table.move_cursor(row=self._selected_idx)

        # Pre-fill CLI-supplied values
        if self._args.artist:
            self.query_one("#input-artist", Input).value = self._args.artist
        if self._args.album:
            self.query_one("#input-album", Input).value = self._args.album
        if self._args.year:
            self.query_one("#input-year", Input).value = self._args.year

        # Apply first candidate into inputs (won't overwrite CLI values)
        if self._candidates:
            self._manual_meta = None
            self._apply_candidate(self._selected_idx)
        else:
            self._render_track_editor(self._manual_meta_or_create())

        for section in (
            "candidates-section",
            "tracklist-scroll",
            "tags-row",
            "outputs-row",
            "target-label",
            "cover-art-label",
        ):
            self._show(section)
        self._show("metadata-box")

        self.query_one("#btn-start", Button).disabled = False
        self.query_one("#btn-more", Button).disabled = False
        self._refresh_eject_button()
        self._refresh_import_buttons()
        self._update_target_label()
        self._update_cover_art_label()
        if self._auto_import_file_pending:
            self._auto_import_file_pending = False
            self.set_timer(0, lambda: self._start_import_from_value("file", self._metadata_file_path))
            return
        if self._auto_import_url_pending:
            self._auto_import_url_pending = False
            self.set_timer(0, lambda: self._start_import_from_value("url", self._metadata_url))

    def _apply_candidate(self, idx: int) -> None:
        if not self._candidates or idx >= len(self._candidates):
            return
        m = self._candidates[idx]

        if not self._args.artist:
            self.query_one("#input-artist", Input).value = m.album_artist or ""
        if not self._args.album:
            self.query_one("#input-album", Input).value = m.album or ""
        if not self._args.year:
            self.query_one("#input-year", Input).value = m.year or ""

        self._render_track_editor(m)

        self._update_target_label()
        self._update_cover_art_label()

    def _update_target_label(self) -> None:
        from .. import library
        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        year = self._input_val("input-year")
        if artist or album:
            root = library.album_root(
                self._cfg.base_dir, artist or "?", album or "?", year
            )
            self.query_one("#target-label", Label).update(f"  Target: [dim]{root}[/dim]")
        self._refresh_target_button()

    def _update_cover_art_label(self) -> None:
        from .. import artwork as artwork_mod

        meta = self._current_meta()
        if meta is None:
            status = artwork_mod.describe_cover_art(
                self._manual_meta_or_create(),
                enabled=self._cfg.download_cover_art,
            )
        else:
            status = artwork_mod.describe_cover_art(meta, enabled=self._cfg.download_cover_art)
        self.query_one("#cover-art-label", Label).update(f"  Cover art: [dim]{status}[/dim]")

    # ------------------------------------------------------------------
    # Events in ready phase
    # ------------------------------------------------------------------

    @on(DataTable.RowHighlighted, "#meta-table")
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._selected_idx = event.cursor_row
        self._apply_candidate(self._selected_idx)

    @on(Input.Changed, "#input-artist, #input-album, #input-year")
    def _on_tag_changed(self, _event: Input.Changed) -> None:
        if self._manual_meta is not None and not self._candidates:
            artist, album, year = self._manual_search_hints()
            self._manual_meta.album_artist = artist
            self._manual_meta.album = album
            self._manual_meta.year = year
        self._update_target_label()
        self._update_cover_art_label()

    @on(Input.Changed, ".track-edit")
    def _on_track_edit(self, event: Input.Changed) -> None:
        input_id = event.input.id or ""
        parts = input_id.split("-")
        if len(parts) != 3 or parts[0] != "track":
            return

        meta = self._current_meta()
        if meta is None:
            return

        try:
            track_number = int(parts[2])
        except ValueError:
            return

        track = next(
            (item for item in self._ensure_meta_tracks(meta) if item.number == track_number),
            None,
        )
        if track is None:
            return

        if parts[1] == "title":
            track.title = event.value
        elif parts[1] == "artist":
            track.artist = event.value

    @on(Checkbox.Changed, ".track-enable")
    def _on_track_enabled(self, event: Checkbox.Changed) -> None:
        checkbox_id = event.checkbox.id or ""
        if not checkbox_id.startswith("track-enabled-"):
            return
        try:
            track_number = int(checkbox_id.rsplit("-", 1)[1])
        except ValueError:
            return
        if self._track_is_audio(track_number):
            self._selected_tracks[track_number] = event.value

    # ------------------------------------------------------------------
    # Phase 3 — running: rip + encode
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-config":
            self._open_settings()
        elif bid == "btn-more":
            self._do_fetch_metadata()
        elif bid == "btn-import-file":
            self._do_import_file()
        elif bid == "btn-import-url":
            self._do_import_url()
        elif bid == "btn-target":
            self._do_open_target()
        elif bid == "btn-eject":
            self._do_eject()
        elif bid == "btn-start":
            self._do_start()
        elif bid == "btn-cancel":
            self._force_exit()

    def action_open_settings(self) -> None:
        self._open_settings()

    def _open_settings(self) -> None:
        if self.phase == "running" or self._operation_busy:
            return
        self.push_screen(ConfigScreen(self._cfg), self._apply_settings)

    def _apply_settings(self, updated_cfg: "Config" | None) -> None:
        if updated_cfg is None:
            return
        self._cfg = updated_cfg
        try:
            self._cfg.save()
        except OSError as exc:
            self._log(f"[bold red]✗ Failed to save settings: {exc}[/bold red]")
            return

        preferred = self._cfg.preferred_metadata_source
        self._src_mb = preferred == "musicbrainz"
        self._src_gnudb = preferred == "gnudb"
        self._src_cdtext = preferred == "cdtext"
        self._src_discogs = preferred == "discogs"
        self.query_one("#chk-src-mb", Checkbox).value = self._src_mb
        self.query_one("#chk-src-gnudb", Checkbox).value = self._src_gnudb
        self.query_one("#chk-src-cdtext", Checkbox).value = self._src_cdtext
        self.query_one("#chk-src-discogs", Checkbox).value = self._src_discogs
        self.query_one("#chk-src-discogs", Checkbox).label = self._discogs_source_label()
        self.query_one("#chk-opus", Checkbox).label = f"Opus {self._cfg.opus_bitrate} kbps"
        self.query_one("#chk-aac", Checkbox).label = f"AAC {self._cfg.aac_bitrate} kbps"
        self._update_target_label()
        self._update_cover_art_label()
        self._log("[green]✓[/green] Settings saved.")

    def _do_fetch_metadata(self) -> None:
        sources = self._sources_dict(from_ui=True)
        active = [k for k, v in sources.items() if v]
        if not active:
            self.notify("No sources selected — check at least one source.", severity="warning")
            return
        if self._operation_busy:
            return
        self.phase = "detecting"
        self._operation_busy = True
        self.notify(f"Fetching from: {', '.join(active)}")
        self._log(f"> Fetching metadata from: {', '.join(active)}")
        self._candidates = []
        self._selected_idx = 0
        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](fetching metadata...)[/dim]")
        self.query_one("#btn-more", Button).disabled = True
        self.query_one("#btn-start", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()
        self._start_meta_fetch(sources)

    def _do_import_file(self) -> None:
        if self._operation_busy:
            return
        self.push_screen(
            ImportPromptScreen(
                title="Import Metadata File",
                label="Path to a .cue, .toc, .json, or .toml file",
                value=self._metadata_file_value(),
                placeholder="/path/to/album.cue",
                submit_label="Import",
            ),
            self._apply_import_file_prompt,
        )

    def _do_import_url(self) -> None:
        if self._operation_busy:
            return
        self.push_screen(
            ImportPromptScreen(
                title="Import Metadata URL",
                label="Supported metadata URL (currently Bandcamp album pages)",
                value=self._metadata_url_value(),
                placeholder="https://artist.bandcamp.com/album/album-name",
                submit_label="Import",
            ),
            self._apply_import_url_prompt,
        )

    def _apply_import_file_prompt(self, value: str | None) -> None:
        if value is None:
            return
        self._metadata_file_path = value
        if not value:
            self.notify("No metadata file path is set.", severity="warning")
            self._refresh_import_buttons()
            return
        self._start_import_from_value("file", value)

    def _apply_import_url_prompt(self, value: str | None) -> None:
        if value is None:
            return
        self._metadata_url = value
        if not value:
            self.notify("No metadata URL is set.", severity="warning")
            self._refresh_import_buttons()
            return
        self._start_import_from_value("url", value)

    def _start_import_from_value(self, kind: str, value: str) -> None:
        if self._operation_busy:
            return
        self.phase = "detecting"
        self._operation_busy = True
        self.query_one("#btn-more", Button).disabled = True
        self.query_one("#btn-start", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()
        self._start_metadata_import(kind, value)

    def _do_eject(self) -> None:
        if self._operation_busy or self.phase not in {"ready", "done", "error"}:
            return

        device = self._resolve_device()
        if not device:
            self._log("[yellow]![/yellow] No CD device found to eject.")
            self._refresh_eject_button()
            return

        self._operation_busy = True
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()
        self._log(f"> Ejecting disc from [bold]{device}[/bold]...")
        self._start_eject(device)

    def _do_open_target(self) -> None:
        if self._target_open_busy or self.phase not in {"ready", "done", "error"}:
            return

        path, exact_target = self._openable_target_path()
        if path is None:
            self._log("[yellow]![/yellow] No target folder is available to open.")
            self._refresh_target_button()
            return

        if _folder_open_command(path) is None:
            self._log("[yellow]![/yellow] No folder opener is available on this system.")
            self._refresh_target_button()
            return

        target = self._target_album_root()
        if exact_target:
            self._log(f"> Opening target folder [bold]{path}[/bold]...")
        elif target is not None:
            self._log(
                f"> Target folder does not exist yet. Opening [bold]{path}[/bold] instead."
            )
        else:
            self._log(f"> Opening [bold]{path}[/bold]...")

        self._target_open_busy = True
        self._refresh_target_button()
        self._start_open_target(path)

    def _do_start(self) -> None:
        if self._operation_busy:
            return
        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        do_image = self._checkbox_val("chk-image")
        do_iso = self._checkbox_val("chk-iso")
        do_flac = self._checkbox_val("chk-flac")
        do_mp3 = self._checkbox_val("chk-mp3")
        do_ogg = self._checkbox_val("chk-ogg")
        do_opus = self._checkbox_val("chk-opus")
        do_alac = self._checkbox_val("chk-alac")
        do_aac = self._checkbox_val("chk-aac")
        do_wav = self._checkbox_val("chk-wav")

        if not artist:
            self._log("[yellow]![/yellow] Artist is required.")
            return
        if not album:
            self._log("[yellow]![/yellow] Album is required.")
            return
        if do_iso and not do_image:
            self._log("[yellow]![/yellow] ISO export requires Disc image.")
            return
        if not any((do_image, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav)):
            self._log("[yellow]![/yellow] Enable at least one output.")
            return
        selected_tracks = self._selected_audio_tracks()
        if (do_flac or do_mp3 or do_ogg or do_opus or do_alac or do_aac or do_wav) and not selected_tracks:
            self._log("[yellow]![/yellow] Select at least one audio track.")
            return

        self.phase = "running"
        self._operation_busy = True
        self._last_accuraterip_status = ""
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()

        for section in (
            "candidates-section",
            "tracklist-scroll",
            "tags-row",
            "outputs-row",
            "target-label",
            "cover-art-label",
        ):
            self._hide(section)
        self._hide("metadata-box")
        self._pb_reset()
        self._show("progress-section")

        self.query_one("#btn-cancel", Button).label = "Cancel"

        self._start_rip(artist, album,
                        self._input_val("input-year"),
                        do_image, self._checkbox_val("chk-iso"), do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
                        selected_tracks)

    @work(thread=True, name="rip")
    def _start_rip(
        self,
        artist: str, album: str, year: str,
        do_image: bool, do_iso: bool, do_flac: bool, do_mp3: bool, do_ogg: bool,
        do_opus: bool, do_alac: bool, do_aac: bool, do_wav: bool,
        selected_tracks: list[int],
    ) -> None:
        from .. import rip as rip_mod, encode as enc_mod, library, verify as verify_mod, artwork as artwork_mod
        from ..metadata.types import Metadata as MetaType

        args = self._args
        cfg = self._cfg

        # Resolve metadata
        meta: MetaType
        if self._candidates and self._selected_idx < len(self._candidates):
            meta = self._candidates[self._selected_idx]
            meta.album_artist = artist
            meta.album = album
            meta.year = year
        elif self._manual_meta is not None:
            meta = self._manual_meta
            meta.album_artist = artist
            meta.album = album
            meta.year = year
        else:
            meta = MetaType(source="Manual", album_artist=artist, album=album, year=year)

        self._ensure_meta_tracks(meta)
        for track in meta.tracks:
            track.title = track.title.strip()
            track.artist = track.artist.strip()

        disc_info = self._disc_info
        device = disc_info.device if disc_info else args.device
        track_count = disc_info.track_count if disc_info else 0
        if do_image and disc_info is None:
            self._tlog("[bold red]✗ No disc layout available for image export.[/bold red]")
            self.call_from_thread(self._enter_error)
            return

        album_root = library.album_root(cfg.base_dir, artist, album, year)
        album_root_existed = album_root.exists()
        img_dir = library.image_dir(album_root)
        fl_dir = library.flac_dir(album_root)
        mp_dir = library.mp3_dir(album_root)
        og_dir = library.ogg_dir(album_root)
        op_dir = library.opus_dir(album_root)
        al_dir = library.alac_dir(album_root)
        aa_dir = library.aac_dir(album_root)
        wa_dir = library.wav_dir(album_root)

        work_dir = Path(cfg.work_dir)
        work_dir_existed = work_dir.exists()
        work_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup.track_dir(work_dir, created=not work_dir_existed)

        toc_path = cue_path = bin_path = iso_path = None
        wav_files: list[Path] = []
        audio_formats: list[tuple[str, str]] = []
        if do_flac:
            audio_formats.append(("flac", "FLAC"))
        if do_mp3:
            audio_formats.append(("mp3", "MP3"))
        if do_ogg:
            audio_formats.append(("ogg", "OGG Vorbis"))
        if do_opus:
            audio_formats.append(("opus", "Opus"))
        if do_alac:
            audio_formats.append(("alac", "ALAC"))
        if do_aac:
            audio_formats.append(("aac", "AAC/M4A"))
        if do_wav:
            audio_formats.append(("wav", "WAV"))

        # ── Disc image ──────────────────────────────────────────────
        if do_image:
            self._tlog("> Creating disc image...")
            self.call_from_thread(
                self._pb_set, "image", "Creating disc image (cdrdao)...", track_count or None
            )
            stem = library.image_stem(artist, album, year)
            self._cleanup.track_dir(album_root, created=not album_root_existed)
            img_dir_existed = img_dir.exists()
            img_dir.mkdir(parents=True, exist_ok=True)
            self._cleanup.track_dir(img_dir, created=not img_dir_existed)
            stem = library.unique_image_stem(img_dir, stem)
            toc_path = img_dir / f"{stem}.toc"
            bin_path = img_dir / f"{stem}.bin"

            def image_cb(current: int, total: int, label: str) -> None:
                self.call_from_thread(self._pb_update, "image", current, total, label)

            ok = rip_mod.rip_image(
                device, toc_path, bin_path, self._cleanup,
                driver=cfg.cdrdao_driver, debug=args.debug,
                process_callback=lambda p: setattr(self, "_current_proc", p),
                progress_callback=image_cb,
                track_count=track_count,
                track_offsets=disc_info.track_offsets if disc_info else None,
                leadout=disc_info.leadout if disc_info else 0,
            )
            self._current_proc = None
            if not ok:
                self._tlog("[bold red]✗ Disc image failed.[/bold red]")
                self._cleanup.remove_all()
                self.call_from_thread(self._enter_error)
                return
            self._tlog("[green]✓[/green] Disc image created.")
            self.call_from_thread(self._pb_done, "image", "✓ Disc image")
            cue_path = img_dir / f"{stem}.cue"
            try:
                rip_mod.write_cue_file(cue_path, bin_path, disc_info, toc_path=toc_path, cleanup=self._cleanup)
                self._tlog(f"[green]✓[/green] CUE sidecar saved: {cue_path.name}")
            except OSError as exc:
                self._tlog(f"[bold red]✗ Failed to write CUE sidecar: {exc}[/bold red]")
                self._cleanup.remove_all()
                self.call_from_thread(self._enter_error)
                return

            if do_iso:
                self._tlog("> Exporting ISO data image...")
                self.call_from_thread(
                    self._pb_set,
                    "iso",
                    "Exporting ISO data image...",
                    len(disc_info.data_track_numbers) or None,
                )
                iso_path = img_dir / f"{stem}.iso"

                def iso_cb(current: int, total: int, label: str) -> None:
                    self.call_from_thread(self._pb_update, "iso", current, total, label)

                exported_iso, detail = rip_mod.export_iso_from_bin(
                    iso_path,
                    bin_path,
                    disc_info,
                    toc_path=toc_path,
                    cleanup=self._cleanup,
                    progress_callback=iso_cb,
                )
                if exported_iso is not None:
                    iso_path = exported_iso
                    self._tlog(f"[green]✓[/green] ISO saved: {iso_path.name}")
                    self.call_from_thread(self._pb_done, "iso", "✓ ISO data image")
                else:
                    iso_path = None
                    self._tlog(f"[yellow]![/yellow] {detail}")
                    self.call_from_thread(self._pb_done, "iso", "✓ ISO skipped")

        # ── Audio outputs ───────────────────────────────────────────
        if audio_formats:
            selected_total = len(selected_tracks)
            self._tlog("> Ripping audio tracks...")
            self.call_from_thread(
                self._pb_set,
                "rip",
                "Ripping audio tracks...",
                selected_total or None,
            )

            def audio_cb(current: int, total: int, fname: str = "") -> None:
                label = f"Ripping audio tracks ({current}/{total})"
                if fname:
                    label = f"{label}: {fname}"
                self.call_from_thread(
                    self._pb_update, "rip", current, max(total, 1), label
                )

            wav_files = rip_mod.rip_audio(
                device, work_dir, track_count, self._cleanup,
                debug=args.debug,
                progress_callback=audio_cb,
                process_callback=lambda p: setattr(self, "_current_proc", p),
                selected_tracks=selected_tracks,
                sample_offset=cfg.cdparanoia_sample_offset,
            )
            self._current_proc = None
            if wav_files is None:
                self._tlog("[bold red]✗ Failed to rip audio tracks.[/bold red]")
                self._cleanup.remove_all()
                self.call_from_thread(self._enter_error)
                return
            self._tlog("[green]✓[/green] Audio tracks ripped.")
            self.call_from_thread(self._pb_done, "rip", "✓ Audio tracks")

            if cfg.accuraterip_enabled:
                self._tlog("> Running AccurateRip verification...")
                if cfg.cdparanoia_sample_offset == 0:
                    self._tlog(
                        "[yellow]![/yellow] AccurateRip is enabled with sample offset 0. "
                        "Set your drive offset in Settings for more reliable results."
                    )
                verified, detail = verify_mod.verify_accuraterip(wav_files, debug=args.debug)
                self._last_accuraterip_status = detail
                if verified is True:
                    self._tlog(f"[green]✓[/green] {detail}")
                elif verified is False:
                    self._tlog(f"[yellow]![/yellow] {detail}")
                else:
                    self._tlog(f"[yellow]![/yellow] {detail}")

            self._cleanup.track_dir(album_root, created=not album_root_existed)

            def _encode_one_format(fmt_key: str, fmt_name: str) -> bool:
                total_tracks = len(wav_files)
                stage_label = _output_stage_label(fmt_key, fmt_name)
                self.call_from_thread(
                    self._pb_set,
                    fmt_key,
                    f"{stage_label}...",
                    total_tracks or None,
                )

                self._tlog(f"> {stage_label}...")

                def encode_cb(done: int, total: int) -> None:
                    self.call_from_thread(
                        self._pb_update,
                        fmt_key,
                        done,
                        max(total, 1),
                        f"{stage_label} ({done}/{total})",
                    )

                ok = enc_mod.encode_tracks(
                    wav_files, meta,
                    flac_dir=fl_dir if fmt_key == "flac" else None,
                    mp3_dir=mp_dir if fmt_key == "mp3" else None,
                    ogg_dir=og_dir if fmt_key == "ogg" else None,
                    opus_dir=op_dir if fmt_key == "opus" else None,
                    alac_dir=al_dir if fmt_key == "alac" else None,
                    aac_dir=aa_dir if fmt_key == "aac" else None,
                    wav_dir=wa_dir if fmt_key == "wav" else None,
                    flac_compression=args.flac_compression,
                    flac_verify=not args.no_verify,
                    mp3_quality=args.mp3_quality,
                    mp3_bitrate=args.mp3_bitrate,
                    opus_bitrate=cfg.opus_bitrate,
                    aac_bitrate=cfg.aac_bitrate,
                    cleanup=self._cleanup,
                    debug=args.debug,
                    progress_callback=encode_cb,
                    track_total_hint=max(selected_tracks) if selected_tracks else None,
                )
                if ok:
                    self._tlog(f"[green]✓[/green] {fmt_name} format complete.")
                    self.call_from_thread(self._pb_done, fmt_key, f"✓ {fmt_name} format")
                return ok

            if do_flac:
                fl_dir_existed = fl_dir.exists()
                fl_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(fl_dir, created=not fl_dir_existed)
            if do_mp3:
                mp_dir_existed = mp_dir.exists()
                mp_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(mp_dir, created=not mp_dir_existed)
            if do_ogg:
                og_dir_existed = og_dir.exists()
                og_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(og_dir, created=not og_dir_existed)
            if do_opus:
                op_dir_existed = op_dir.exists()
                op_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(op_dir, created=not op_dir_existed)
            if do_alac:
                al_dir_existed = al_dir.exists()
                al_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(al_dir, created=not al_dir_existed)
            if do_aac:
                aa_dir_existed = aa_dir.exists()
                aa_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(aa_dir, created=not aa_dir_existed)
            if do_wav:
                wa_dir_existed = wa_dir.exists()
                wa_dir.mkdir(parents=True, exist_ok=True)
                self._cleanup.track_dir(wa_dir, created=not wa_dir_existed)

            for fmt_key, fmt_name in audio_formats:
                if not _encode_one_format(fmt_key, fmt_name):
                    self._tlog(f"[bold red]✗ Encoding to {fmt_name} format failed.[/bold red]")
                    self._cleanup.remove_all()
                    self.call_from_thread(self._enter_error)
                    return

        cover_art_path = None
        if cfg.download_cover_art:
            self._tlog(f"> Cover art: {artwork_mod.describe_cover_art(meta, enabled=True)}")
            cover_art_path = artwork_mod.download_cover_art(
                meta,
                album_root,
                cleanup=self._cleanup,
                timeout=cfg.metadata_timeout,
                debug=args.debug,
            )
            if cover_art_path is not None:
                self._tlog(f"[green]✓[/green] Cover art saved: {cover_art_path.name}")
            else:
                self._tlog("[yellow]![/yellow] Cover art not downloaded.")

        # ── backup-info.txt ─────────────────────────────────────────
        self._write_backup_info(
            album_root, device, artist, album, year, meta.source,
            wav_files, track_count, toc_path, cue_path, bin_path, iso_path,
            do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, args,
            selected_tracks,
            cover_art_path,
        )

        # ── Cleanup WAVs ────────────────────────────────────────────
        if not cfg.keep_wav:
            for w in wav_files:
                w.unlink(missing_ok=True)
            try:
                work_dir.rmdir()
            except OSError:
                pass

        if cfg.eject_after:
            subprocess.run(["eject", device], capture_output=True)

        self._cleanup.clear()
        completed_track_count = len(wav_files) or track_count
        self.call_from_thread(
            self._enter_done,
            album_root, artist, album, year, completed_track_count,
            meta.source, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav, args,
            selected_tracks, cover_art_path, cue_path, iso_path,
        )

    # ------------------------------------------------------------------
    # Progress bar helpers (must be called on main thread)
    # ------------------------------------------------------------------

    def _pb_set(self, which: str, label: str, total: int | None) -> None:
        self._show(f"prog-{which}-row")
        self.query_one(f"#prog-{which}-lbl", Label).update(label)
        pb = self.query_one(f"#prog-{which}", ProgressBar)
        pb.update(total=total, progress=0)

    def _pb_update(self, which: str, current: int, total: int, label: str) -> None:
        self._show(f"prog-{which}-row")
        self.query_one(f"#prog-{which}-lbl", Label).update(label)
        self.query_one(f"#prog-{which}", ProgressBar).update(
            total=total, progress=current
        )

    def _pb_done(self, which: str, label: str) -> None:
        self._show(f"prog-{which}-row")
        self.query_one(f"#prog-{which}-lbl", Label).update(f"[green]{label}[/green]")
        pb = self.query_one(f"#prog-{which}", ProgressBar)
        pb.update(progress=pb.total or 1)

    def _pb_reset(self) -> None:
        for which in _PROGRESS_KEYS:
            self._hide(f"prog-{which}-row")
            self.query_one(f"#prog-{which}-lbl", Label).update("")
            self.query_one(f"#prog-{which}", ProgressBar).update(total=None, progress=0)

    @work(thread=True, name="completion-alerts")
    def _start_completion_alerts(self, title: str, message: str) -> None:
        from .. import alerts

        sound_ok = alerts.play_completion_sound(self._cfg.completion_sound)
        notify_ok = alerts.send_desktop_notification(title, message)
        self.call_from_thread(self._finish_completion_alerts, sound_ok, notify_ok)

    def _finish_completion_alerts(self, sound_ok: bool, notify_ok: bool) -> None:
        if self._cfg.completion_sound != "off" and not sound_ok:
            self._log("[yellow]![/yellow] Completion sound unavailable.")
        if not notify_ok:
            self._log("[yellow]![/yellow] Desktop notifications unavailable.")

    # ------------------------------------------------------------------
    # Open target folder
    # ------------------------------------------------------------------

    @work(thread=True, name="open-target")
    def _start_open_target(self, path: Path) -> None:
        cmd = _folder_open_command(path)
        if cmd is None:
            self.call_from_thread(
                self._finish_open_target,
                False,
                path,
                "No supported folder opener command is installed.",
            )
            return

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            self.call_from_thread(
                self._finish_open_target,
                False,
                path,
                f"Failed to execute {cmd[0]}.",
            )
            return
        except subprocess.TimeoutExpired:
            self.call_from_thread(
                self._finish_open_target,
                False,
                path,
                "Timed out waiting for the folder opener.",
            )
            return

        detail = (result.stderr or result.stdout or "").strip()
        self.call_from_thread(self._finish_open_target, result.returncode == 0, path, detail)

    def _finish_open_target(self, ok: bool, path: Path, detail: str = "") -> None:
        self._target_open_busy = False
        if not ok:
            if detail:
                self._log(f"[bold red]✗ Failed to open {path}: {detail}[/bold red]")
            else:
                self._log(f"[bold red]✗ Failed to open {path}.[/bold red]")
        self._refresh_target_button()

    # ------------------------------------------------------------------
    # Disc eject
    # ------------------------------------------------------------------

    @work(thread=True, name="eject")
    def _start_eject(self, device: str) -> None:
        try:
            result = subprocess.run(
                ["eject", device],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except FileNotFoundError:
            self.call_from_thread(
                self._finish_eject,
                False,
                device,
                "The `eject` command is not installed.",
            )
            return
        except subprocess.TimeoutExpired:
            self.call_from_thread(
                self._finish_eject,
                False,
                device,
                "Timed out waiting for the drive to eject.",
            )
            return

        detail = (result.stderr or result.stdout or "").strip()
        self.call_from_thread(self._finish_eject, result.returncode == 0, device, detail)

    def _finish_eject(self, ok: bool, device: str, detail: str = "") -> None:
        self._operation_busy = False
        if ok:
            self._enter_waiting_for_disc(f"> Disc ejected from [bold]{device}[/bold]. Insert another disc to load metadata.")
            return

        if detail:
            self._log(f"[bold red]✗ Failed to eject {device}: {detail}[/bold red]")
        else:
            self._log(f"[bold red]✗ Failed to eject {device}.[/bold red]")

        if self.phase == "ready":
            self.query_one("#btn-start", Button).disabled = False
            self.query_one("#btn-more", Button).disabled = False
        self._refresh_eject_button()
        self._refresh_import_buttons()

    # ------------------------------------------------------------------
    # Disc watch
    # ------------------------------------------------------------------

    def _schedule_disc_watch(self) -> None:
        if (
            self._shutting_down
            or self.phase not in {"ready", "done", "error"}
            or self._operation_busy
            or self._disc_watch_busy
        ):
            return
        self._disc_watch_busy = True
        self._poll_disc_change()

    @work(thread=True, name="disc-watch")
    def _poll_disc_change(self) -> None:
        from .. import device as dev_mod, disc as disc_mod

        try:
            if self._shutting_down:
                return
            device = self._args.device or (self._disc_info.device if self._disc_info else None) or dev_mod.detect()
            if not device:
                if not self._shutting_down:
                    self.call_from_thread(self._mark_disc_absent)
                return

            status = dev_mod.drive_status(device)
            if status in {"no_disc", "tray_open"}:
                if not self._shutting_down:
                    self.call_from_thread(self._mark_disc_absent)
                return
            if status == "not_ready":
                return
            if status == "unknown" and not dev_mod.is_readable(device):
                if not self._shutting_down:
                    self.call_from_thread(self._mark_disc_absent)
                return

            changed = dev_mod.media_changed(device)
            should_probe = self._watch_disc_present is False or changed is True
            if not should_probe:
                if not self._shutting_down:
                    self.call_from_thread(self._mark_disc_present)
                return

            try:
                disc_info = disc_mod.load_disc_info(device)
            except Exception:
                return
            disc_info.device = device
            signature = self._disc_sig(disc_info)
            should_reload = (self._watch_disc_present is False) or (signature != self._disc_signature)
            if should_reload:
                if not self._shutting_down:
                    self.call_from_thread(self._reload_for_new_disc, disc_info, signature)
            else:
                if not self._shutting_down:
                    self.call_from_thread(self._mark_disc_present)
        finally:
            if not self._shutting_down:
                self.call_from_thread(self._finish_disc_watch)

    def _finish_disc_watch(self) -> None:
        self._disc_watch_busy = False

    def _mark_disc_absent(self) -> None:
        if self.phase not in {"ready", "done", "error"}:
            return
        if self._watch_disc_present is not False:
            self._watch_disc_present = False
            if self.phase in {"ready", "done"}:
                self._enter_waiting_for_disc(
                    "> Disc removed or tray opened. Insert a disc to load metadata."
                )

    def _mark_disc_present(self) -> None:
        self._watch_disc_present = True

    def _reload_for_new_disc(self, disc_info: "DiscInfo", signature: tuple) -> None:
        if self.phase not in {"ready", "done", "error"} or self._operation_busy:
            return

        previous_phase = self.phase
        self.phase = "detecting"
        self._operation_busy = True
        self._watch_disc_present = True
        self._disc_info = disc_info
        self._disc_signature = signature
        self._candidates = []
        self._manual_meta = None
        self._selected_idx = 0
        self._selected_tracks = {}
        self._last_accuraterip_status = ""
        self._last_accuraterip_status = ""
        self._sync_track_selection()

        self._hide("done-section")
        self._hide("progress-section")
        self._show("metadata-box")
        for section in (
            "candidates-section",
            "tracklist-scroll",
            "tags-row",
            "outputs-row",
            "target-label",
            "cover-art-label",
        ):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](loading new disc metadata...)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()

        if previous_phase == "done":
            self._log("> New disc detected.")
        else:
            self._log("> Disc detected.")
        self._log(
            f"[green]✓[/green] [bold]{disc_info.track_count} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
        )
        if disc_info.data_track_numbers:
            self._log(
                "[yellow]![/yellow] Data track(s) detected and excluded by default: "
                f"{compact_track_list(disc_info.data_track_numbers)}"
            )
        self._start_meta_fetch(self._sources_dict(from_ui=True))

    # ------------------------------------------------------------------
    # Phase 4 — done / error
    # ------------------------------------------------------------------

    def _enter_done(
        self,
        album_root: Path,
        artist: str,
        album: str,
        year: str,
        track_count: int,
        meta_source: str,
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
        selected_tracks: list[int],
        cover_art_path: Path | None,
        cue_path: Path | None,
        iso_path: Path | None,
    ) -> None:
        self.phase = "done"
        self._operation_busy = False
        self._watch_disc_present = True
        self._show("progress-section")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_import_buttons()

        formats = []
        if do_image:
            formats.append("Disc image")
        if cue_path is not None:
            formats.append("CUE sidecar")
        if do_iso and iso_path is not None:
            formats.append("ISO data")
        if do_flac:
            formats.append(f"FLAC (lvl {args.flac_compression})")
        if do_mp3:
            mp3_desc = f"{args.mp3_bitrate} kbps" if args.mp3_bitrate > 0 else "VBR"
            formats.append(f"MP3 ({mp3_desc})")
        if do_ogg:
            formats.append("OGG Vorbis")
        if do_opus:
            formats.append(f"Opus ({self._cfg.opus_bitrate} kbps)")
        if do_alac:
            formats.append("ALAC")
        if do_aac:
            formats.append(f"AAC/M4A ({self._cfg.aac_bitrate} kbps)")
        if do_wav:
            formats.append("WAV copy")

        year_str = f" ({year})" if year else ""
        details_lines = [
            f"  [bold]{artist}[/bold] — {album}{year_str}",
            f"  Tracks: {track_count}",
            f"  Selected tracks: {compact_track_list(selected_tracks)}",
            f"  Formats: {', '.join(formats) if formats else '(none)'}",
            f"  Source: {meta_source}",
            f"  Saved to: [dim]{album_root}[/dim]",
        ]
        if self._last_accuraterip_status:
            details_lines.append(f"  AccurateRip: {self._last_accuraterip_status}")
        if cover_art_path is not None:
            details_lines.append(f"  Cover art: [dim]{cover_art_path.name}[/dim]")
        elif self._cfg.download_cover_art:
            details_lines.append("  Cover art: [dim]not downloaded[/dim]")

        self.query_one("#done-title", Label).update("[bold green]✓ Done![/bold green]")
        self.query_one("#done-details", Static).update("\n".join(details_lines))
        self._show("done-section")
        self.notify(
            f"{artist} — {album}",
            title="DiscVault rip complete",
            severity="information",
            timeout=12,
        )
        self._start_completion_alerts(
            "DiscVault rip complete",
            f"{artist} — {album}",
        )

        self.query_one("#btn-cancel", Button).label = "Quit"
        self.query_one("#btn-cancel", Button).disabled = False
        self.query_one("#btn-cancel", Button).focus()

    def _enter_error(self) -> None:
        self.phase = "error"
        self._operation_busy = False
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        btn = self.query_one("#btn-cancel", Button)
        btn.label = "Quit"
        btn.disabled = False
        self._refresh_eject_button()
        self._refresh_import_buttons()

    def _enter_waiting_for_disc(self, message: str) -> None:
        self.phase = "error"
        self._operation_busy = False
        self._watch_disc_present = False
        self._candidates = []
        self._manual_meta = None
        self._selected_idx = 0
        self._selected_tracks = {}

        self._hide("done-section")
        self._hide("progress-section")
        self._show("metadata-box")
        for section in (
            "candidates-section",
            "tracklist-scroll",
            "tags-row",
            "outputs-row",
            "target-label",
            "cover-art-label",
        ):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](insert a disc to load metadata)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_import_buttons()

        btn = self.query_one("#btn-cancel", Button)
        btn.label = "Quit"
        btn.disabled = False
        self._refresh_eject_button()
        self._log(message)

    # ------------------------------------------------------------------
    # Cancel / Quit
    # ------------------------------------------------------------------

    def _on_cancel(self) -> None:
        self._force_exit()

    def action_quit_app(self) -> None:
        self._force_exit()

    def action_cancel_or_quit(self) -> None:
        self._force_exit()

    def _force_exit(self) -> None:
        """Kill subprocess, cancel workers, then exit (lets Textual restore terminal)."""
        self._shutting_down = True
        if self._disc_watch_timer is not None:
            self._disc_watch_timer.stop()
        self._kill_current()
        try:
            self._cleanup.remove_all()
        except Exception:
            pass
        self.workers.cancel_all()
        self.exit()

    def action_refresh_meta(self) -> None:
        """Re-fetch metadata (F5)."""
        self._do_fetch_metadata()

    def _kill_current(self) -> None:
        proc = self._current_proc
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass

    # ------------------------------------------------------------------
    # backup-info.txt
    # ------------------------------------------------------------------

    def _write_backup_info(
        self, album_root: Path, device: str, artist: str, album: str,
        year: str, meta_source: str, wav_files: list[Path], track_count: int,
        toc_path, cue_path, bin_path, iso_path, do_image: bool, do_iso: bool, do_flac: bool, do_mp3: bool,
        do_ogg: bool, do_opus: bool, do_alac: bool, do_aac: bool, do_wav: bool,
        args, selected_tracks: list[int], cover_art_path: Path | None,
    ) -> None:
        info_path = album_root / "backup-info.txt"
        self._cleanup.track_file(info_path)
        lines = [
            f"Backup timestamp: {datetime.datetime.now().astimezone().isoformat()}",
            f"Device: {device}",
            f"Artist: {artist}",
            f"Album: {album}",
        ]
        if year:
            lines.append(f"Year: {year}")
        lines += [
            f"Metadata source: {meta_source}",
            f"Track count: {len(wav_files) or track_count}",
            f"Selected tracks: {compact_track_list(selected_tracks)}",
            f"Disc image: {'yes' if do_image else 'no'}",
            f"FLAC: {'yes' if do_flac else 'no'}",
            f"MP3: {'yes' if do_mp3 else 'no'}",
            f"OGG: {'yes' if do_ogg else 'no'}",
            f"Opus: {'yes' if do_opus else 'no'}",
            f"ALAC: {'yes' if do_alac else 'no'}",
            f"AAC/M4A: {'yes' if do_aac else 'no'}",
            f"WAV copy: {'yes' if do_wav else 'no'}",
            f"AccurateRip: {'yes' if self._cfg.accuraterip_enabled else 'no'}",
            f"Sample offset: {self._cfg.cdparanoia_sample_offset}",
            f"Cover art enabled: {'yes' if self._cfg.download_cover_art else 'no'}",
        ]
        if do_image and toc_path:
            lines.append(f"Image TOC: {toc_path}")
            lines.append(f"Image CUE: {cue_path}")
            lines.append(f"Image BIN: {bin_path}")
        lines.append(f"ISO export: {'yes' if do_iso else 'no'}")
        if iso_path is not None:
            lines.append(f"Image ISO: {iso_path}")
        if self._last_accuraterip_status:
            lines.append(f"AccurateRip result: {self._last_accuraterip_status}")
        if cover_art_path is not None:
            lines.append(f"Cover art: {cover_art_path}")
        try:
            info_path.write_text("\n".join(lines) + "\n")
        except OSError:
            pass
