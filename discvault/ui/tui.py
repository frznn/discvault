"""Full Textual TUI for discvault."""
from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.content import Content
from textual.containers import Container, Horizontal, Vertical
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
    LoadingIndicator,
    ProgressBar,
    RichLog,
    Static,
)
from textual import events, on, work

if TYPE_CHECKING:
    from ..config import Config
    from ..extras import ExtraScanBundle
    from ..metadata.types import Metadata, DiscInfo

from ..metadata.search import combine_search_text, search_tokens
from .. import __version__
from ..pipeline import _output_stage_label
from ..tracks import (
    compact_track_list,
    display_track_count,
    effective_audio_track_numbers,
    parse_track_spec,
    possible_data_track_numbers,
    resolve_selected_tracks,
)
from .confirm import ConfirmScreen, _copy_to_clipboard
from .extras_select import ExtrasSelectScreen
from .folder_picker import FolderPickerScreen
from .import_prompt import MetadataImportPromptScreen, TextPromptScreen
from .output_select import OutputSelectScreen
from .settings import ConfigScreen
from .source_select import SourceSelectScreen


# CSS is in app.tcss (same directory). Loaded via CSS_PATH on the App class.


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


class StatusRichLog(RichLog):
    """RichLog with one-line mouse-wheel scrolling."""

    def _scroll_down_for_pointer(
        self,
        *,
        animate: bool = True,
        speed: float | None = None,
        duration: float | None = None,
        easing=None,
        force: bool = False,
        on_complete=None,
        level="basic",
    ) -> bool:
        return self._scroll_to(
            y=self.scroll_target_y + 1,
            animate=animate,
            speed=speed,
            duration=duration,
            easing=easing,
            force=force,
            on_complete=on_complete,
            level=level,
        )

    def _scroll_up_for_pointer(
        self,
        *,
        animate: bool = True,
        speed: float | None = None,
        duration: float | None = None,
        easing=None,
        force: bool = False,
        on_complete=None,
        level="basic",
    ) -> bool:
        return self._scroll_to(
            y=self.scroll_target_y - 1,
            animate=animate,
            speed=speed,
            duration=duration,
            easing=easing,
            force=force,
            on_complete=on_complete,
            level=level,
        )


class MetadataDataTable(DataTable):
    """DataTable with one-line mouse-wheel scrolling."""

    _pointer_scroll_coalesce_window = 0.03

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_pointer_scroll_time = 0.0
        self._last_pointer_scroll_direction = 0
        self._last_pointer_scroll_screen: tuple[int, int] | None = None

    def _is_duplicate_pointer_scroll(self, direction: int, event: events.MouseEvent) -> bool:
        screen_position = (event.screen_x, event.screen_y)
        duplicate = (
            direction == self._last_pointer_scroll_direction
            and screen_position == self._last_pointer_scroll_screen
            and (event.time - self._last_pointer_scroll_time) <= self._pointer_scroll_coalesce_window
        )
        self._last_pointer_scroll_time = event.time
        self._last_pointer_scroll_direction = direction
        self._last_pointer_scroll_screen = screen_position
        return duplicate

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.prevent_default()
        if self._is_duplicate_pointer_scroll(1, event):
            event.stop()
            return
        if event.ctrl or event.shift:
            if self.allow_horizontal_scroll and self._scroll_right_for_pointer(animate=False):
                event.stop()
        else:
            if self.allow_vertical_scroll and self._scroll_down_for_pointer(animate=False):
                event.stop()

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.prevent_default()
        if self._is_duplicate_pointer_scroll(-1, event):
            event.stop()
            return
        if event.ctrl or event.shift:
            if self.allow_horizontal_scroll and self._scroll_left_for_pointer(animate=False):
                event.stop()
        else:
            if self.allow_vertical_scroll and self._scroll_up_for_pointer(animate=False):
                event.stop()

    def _scroll_down_for_pointer(
        self,
        *,
        animate: bool = True,
        speed: float | None = None,
        duration: float | None = None,
        easing=None,
        force: bool = False,
        on_complete=None,
        level="basic",
    ) -> bool:
        return self._scroll_to(
            y=self.scroll_target_y + 1,
            animate=animate,
            speed=speed,
            duration=duration,
            easing=easing,
            force=force,
            on_complete=on_complete,
            level=level,
        )

    def _scroll_up_for_pointer(
        self,
        *,
        animate: bool = True,
        speed: float | None = None,
        duration: float | None = None,
        easing=None,
        force: bool = False,
        on_complete=None,
        level="basic",
    ) -> bool:
        return self._scroll_to(
            y=self.scroll_target_y - 1,
            animate=animate,
            speed=speed,
            duration=duration,
            easing=easing,
            force=force,
            on_complete=on_complete,
            level=level,
        )


def _folder_open_command(path: Path) -> list[str] | None:
    """Return the best available command to open a folder in the file manager."""
    if shutil.which("xdg-open"):
        return ["xdg-open", str(path)]
    if shutil.which("gio"):
        return ["gio", "open", str(path)]
    if shutil.which("open"):
        return ["open", str(path)]
    return None


def _target_button_destination(target: Path | None, base_dir: str) -> tuple[Path | None, str, bool]:
    """Return the folder, button label, and whether it is the exact album target."""
    if target is not None and target.exists():
        return target, "Open Target Dir", True

    library_root = Path(base_dir).expanduser()
    if library_root.exists():
        return library_root, "Open Library", False

    return None, "Open Library", False


def _target_label_text(base_dir: str, artist: str, album: str, year: str) -> str:
    if not artist and not album:
        return ""
    from .. import library

    target = library.album_root(base_dir, artist or "?", album or "?", year)
    return f"Target Dir: {target}"


def _extras_button_label(selected_count: int, available_count: int) -> str:
    if available_count > 0:
        if selected_count > 0:
            return f"Extras ({selected_count}/{available_count})"
        return f"Extras ({available_count})"
    if selected_count > 0:
        return f"Extras ({selected_count})"
    return "Extras"


def _extras_notice_text(selected_count: int, available_count: int, *, has_data_session: bool) -> str:
    if available_count > 0:
        noun = "file" if available_count == 1 else "files"
        if selected_count > 0:
            verb = "is" if selected_count == 1 else "are"
            return (
                f"[yellow]This disc includes [bold]{available_count}[/bold] extra {noun}.[/yellow] "
                f"[bold]{selected_count}[/bold] {verb} selected for copy."
            )
        return (
            f"[yellow]This disc includes [bold]{available_count}[/bold] extra {noun}.[/yellow] "
            "Open [bold]Extras[/bold] to review them."
        )
    if has_data_session:
        return (
            "[yellow]This disc may include extra files.[/yellow] "
            "Open [bold]Extras[/bold] to inspect them."
        )
    return ""


def _normalize_manual_search_text(value: str) -> str:
    stripped = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(search_tokens(stripped.casefold()))


def _manual_search_score(meta: "Metadata", search_text: str) -> tuple[int, int, int, int]:
    normalized_query = _normalize_manual_search_text(search_text)
    if not normalized_query:
        return (0, 0, 0, 0)

    tokens = normalized_query.split()
    haystack = _normalize_manual_search_text(" ".join(filter(None, [meta.album_artist, meta.album, meta.year])))
    matched_tokens = sum(1 for token in tokens if token in haystack)
    all_tokens_match = int(bool(tokens) and matched_tokens == len(tokens))
    phrase_match = int(normalized_query in haystack)
    detail_length = len(meta.album_artist) + len(meta.album)
    return (all_tokens_match, phrase_match, matched_tokens, detail_length)


def _sort_manual_search_candidates(candidates: list["Metadata"], search_text: str) -> list["Metadata"]:
    return sorted(
        candidates,
        key=lambda meta: _manual_search_score(meta, search_text),
        reverse=True,
    )


def _extras_announcement_text(available_count: int, *, has_data_session: bool) -> str:
    if available_count > 0:
        noun = "file" if available_count == 1 else "files"
        return f"This disc includes {available_count} extra {noun}. Open Extras to review them."
    if has_data_session:
        return "This disc may include extra files. Open Extras to inspect them."
    return ""


def _dir_has_files(d: Path) -> bool:
    try:
        return any(True for p in d.iterdir() if p.is_file())
    except OSError:
        return False


def _needs_overwrite_confirmation(album_root: Path, outputs: dict[str, bool] | None = None) -> bool:
    """Return True when the album root already contains files that may be overwritten."""
    if not album_root.exists():
        return False
    from .. import library
    if any(path.is_file() for path in album_root.iterdir()):
        return True
    outputs = outputs or {
        "image": True,
        "iso": True,
        "flac": True,
        "mp3": True,
        "ogg": True,
        "opus": True,
        "alac": True,
        "aac": True,
        "wav": True,
        "extras": True,
    }
    dirs = []
    if outputs.get("image") or outputs.get("iso"):
        dirs.append(library.image_dir(album_root))
    if outputs.get("flac"):
        dirs.append(library.flac_dir(album_root))
    if outputs.get("mp3"):
        dirs.append(library.mp3_dir(album_root))
    if outputs.get("ogg"):
        dirs.append(library.ogg_dir(album_root))
    if outputs.get("opus"):
        dirs.append(library.opus_dir(album_root))
    if outputs.get("alac"):
        dirs.append(library.alac_dir(album_root))
    if outputs.get("aac"):
        dirs.append(library.aac_dir(album_root))
    if outputs.get("wav"):
        dirs.append(library.wav_dir(album_root))
    if outputs.get("extras"):
        dirs.append(library.extras_dir(album_root))
    return any(_dir_has_files(d) for d in dirs)


_PROGRESS_KEYS = ("image", "iso", "rip", "flac", "mp3", "ogg", "opus", "alac", "aac", "wav", "extras")
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _output_option_label(key: str, args, cfg: "Config") -> str:
    if key == "image":
        return "Disc image"
    if key == "iso":
        return "ISO data"
    if key == "flac":
        return f"FLAC lvl {args.flac_compression}"
    if key == "mp3":
        return f"MP3 {args.mp3_bitrate} kbps" if args.mp3_bitrate > 0 else "MP3 VBR"
    if key == "ogg":
        return "OGG Vorbis"
    if key == "opus":
        return f"Opus {cfg.opus_bitrate} kbps"
    if key == "alac":
        return "ALAC"
    if key == "aac":
        return f"AAC {cfg.aac_bitrate} kbps"
    if key == "wav":
        return "WAV copy"
    return key

class DiscvaultApp(App[None]):
    """Full discvault TUI."""

    CSS_PATH = "app.tcss"
    TITLE = "DiscVault"
    SUB_TITLE = f"v{__version__}"
    COMMAND_PALETTE_BINDING = "ctrl+k"
    CTRL_C_HIT = False  # prevent Textual's built-in Ctrl+C exit; handled by our binding

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit"),
        Binding("ctrl+shift+c", "copy_selection", "Copy", show=False),
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
        Binding("question_mark", "show_help", "Help", show=True),
    ]

    # Current phase: init | detecting | ready | running | done | error
    phase: reactive[str] = reactive("init")

    def format_title(self, title: str, sub_title: str) -> Content:
        if sub_title:
            return Content.assemble(Content(title), (" ", "dim"), Content(sub_title).stylize("dim"))
        return Content(title)

    def __init__(self, args, cfg: "Config") -> None:
        super().__init__()
        self.scroll_sensitivity_y = 1.0
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
        self._target_is_base = False  # True when the target input holds a base dir (album subfolder created inside)
        self._shutting_down = False
        self._cancel_requested = False
        self._last_rip_params: dict | None = None
        self._active_stages: set[str] = set()
        self._stage_labels: dict[str, str] = {}
        self._spinner_frame: int = 0
        self._anim_tick: int = 0
        self._anim_timer = None
        self._last_meta_fetch_all_sources = True
        self._last_accuraterip_status = ""
        # Initialize source selection from config defaults.
        self._src_cdtext = cfg.default_src_cdtext
        self._src_mb = cfg.default_src_musicbrainz
        self._src_gnudb = cfg.default_src_gnudb
        self._src_discogs = cfg.default_src_discogs
        self._out_image = not args.no_image
        self._out_iso = bool(getattr(args, "iso", False))
        self._out_flac = not args.no_flac
        self._out_mp3 = not args.no_mp3
        self._out_ogg = bool(getattr(args, "ogg", False))
        self._out_opus = bool(getattr(args, "opus", False))
        self._out_alac = bool(getattr(args, "alac", False))
        self._out_aac = bool(getattr(args, "aac", False))
        self._out_wav = bool(getattr(args, "wav", False))
        self._cover_art_selected = bool(cfg.download_cover_art)
        self._cover_art_available = False
        self._extra_scan_bundle: ExtraScanBundle | None = None
        self._selected_extra_paths: list[str] = []
        self._extras_announced_signature: tuple | None = None
        self._status_toast_timer = None
        self._metadata_search_query = ""
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
                with Vertical(id="metadata-box"):
                    yield Label("Metadata", id="metadata-title")
                    with Vertical(id="metadata-left"):
                        with Vertical(id="candidates-section"):
                            yield MetadataDataTable(id="meta-table", cursor_type="row", zebra_stripes=True)

                        with Horizontal(id="metadata-actions-row"):
                            yield Button("Sources…", id="btn-sources", disabled=True)
                            yield Button("Import", id="btn-import", disabled=True)
                            yield Button("Manual Search", id="btn-more", disabled=True)
                            yield Button("Manual Entry", id="btn-manual", disabled=True)
                            with Horizontal(id="metadata-actions-right"):
                                yield Checkbox("Download Cover Art", id="chk-cover-art", compact=True, disabled=True)
                                yield Label("", id="cover-art-source", classes="cover-art-source-lbl")

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

                yield Static("", id="extras-notice", markup=True)

                with Horizontal(id="target-row"):
                    yield Label("Destination", classes="tag-lbl")
                    yield Input(placeholder="", id="target-dir-input", compact=True)
                    yield Button("Browse…", id="btn-browse", compact=True)

                # Running phase: progress bars
                with Vertical(id="progress-section"):
                    with Vertical(id="prog-image-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-image-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-image-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-image", show_eta=False)
                    with Vertical(id="prog-iso-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-iso-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-iso-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-iso", show_eta=False)
                    with Vertical(id="prog-rip-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-rip-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-rip-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-rip", show_eta=False)
                    with Vertical(id="prog-flac-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-flac-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-flac-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-flac", show_eta=False)
                    with Vertical(id="prog-mp3-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-mp3-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-mp3-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-mp3", show_eta=False)
                    with Vertical(id="prog-ogg-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-ogg-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-ogg-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-ogg", show_eta=False)
                    with Vertical(id="prog-opus-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-opus-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-opus-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-opus", show_eta=False)
                    with Vertical(id="prog-alac-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-alac-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-alac-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-alac", show_eta=False)
                    with Vertical(id="prog-aac-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-aac-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-aac-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-aac", show_eta=False)
                    with Vertical(id="prog-wav-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-wav-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-wav-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-wav", show_eta=False)
                    with Vertical(id="prog-extras-row", classes="prog-row"):
                        with Horizontal(classes="prog-lbl-row"):
                            yield Label("", id="prog-extras-lbl", classes="prog-lbl")
                            yield LoadingIndicator(id="prog-extras-spin", classes="prog-spin")
                        yield ProgressBar(id="prog-extras", show_eta=False)

                # Done phase: summary
                with Vertical(id="done-section"):
                    yield Label("", id="done-title", markup=True)
                    yield Static("", id="done-details", markup=True)

            # Always-visible status log
            with Container(id="status-log-shell"):
                yield StatusRichLog(id="status-log", highlight=True, markup=True, max_lines=200)
                yield Static("", id="status-toast", markup=False)

            # Action bar — inside #outer, always visible below the scroll area
            with Horizontal(id="action-bar"):
                yield Button("Settings", id="btn-config")
                yield Button("Select Outputs", id="btn-outputs")
                yield Button("Extras", id="btn-extras", disabled=True)
                with Horizontal(id="action-right"):
                    yield Button("Open Library", id="btn-target", disabled=True)
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
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()
        self._start_detection(self._sources_dict())

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        if event.state == WorkerState.ERROR:
            error_msg = str(event.worker.error) if event.worker.error else "Unknown error"
            self._log(f"[bold red]✗ Worker '{event.worker.name}' error: {error_msg}[/bold red]")
            if event.worker.name == "rip":
                try:
                    self._cleanup.remove_all()
                except Exception:
                    pass
                self._enter_error(error_msg)

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

    def _hide_status_toast(self) -> None:
        try:
            toast = self.query_one("#status-toast", Static)
        except Exception:
            return
        toast.update("")
        toast.remove_class("-information", "-warning", "-error")
        toast.styles.display = "none"
        self._status_toast_timer = None

    def _show_status_toast(
        self,
        message: str,
        *,
        severity: str = "information",
        duration: float = 4.0,
    ) -> None:
        try:
            shell = self.query_one("#status-log-shell", Container)
            toast = self.query_one("#status-toast", Static)
        except Exception:
            return
        if self._status_toast_timer is not None:
            self._status_toast_timer.stop()
            self._status_toast_timer = None
        toast.update(message)
        toast.remove_class("-information", "-warning", "-error", update=False)
        toast.add_class(f"-{severity}")
        shell_width = max(shell.size.width, 20)
        shell_height = max(shell.size.height, 1)
        right_padding = 4
        max_width = max(20, shell_width - (right_padding + 4))
        toast_width = min(max_width, max(20, len(message) + 4))
        toast_height = 3
        toast.styles.width = toast_width
        toast.styles.offset = (
            max(0, shell_width - toast_width - right_padding),
            max(0, (shell_height - toast_height) // 2),
        )
        toast.styles.display = "block"
        self._status_toast_timer = self.set_timer(duration, self._hide_status_toast)

    def _announce(self, message: str, *, severity: str = "info") -> None:
        severity_name = "information"
        if severity == "warning":
            severity_name = "warning"
        elif severity == "error":
            severity_name = "error"
        self._show_status_toast(message, severity=severity_name)

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

    def _manual_search_request(self) -> tuple[str, tuple[str, str, str]]:
        search_text = self._metadata_search_query.strip()
        if search_text:
            return search_text, ("", "", "")

        hints = self._manual_search_hints()
        return combine_search_text(
            "",
            artist=hints[0],
            album=hints[1],
            year=hints[2],
        ), hints

    def _has_manual_search_terms(self) -> bool:
        query, hints = self._manual_search_request()
        return bool(query or hints[0] or hints[1])

    def _track_is_audio(self, track_number: int) -> bool:
        if self._disc_info is None:
            return True
        return track_number in self._effective_audio_tracks()

    def _track_hint_kwargs(self) -> dict[str, object]:
        bundle = self._extra_scan_bundle
        return {
            "extra_track_number": bundle.track_number if bundle is not None else None,
            "has_data_session": bundle is not None,
        }

    def _display_track_count(self, meta: Metadata | None = None) -> int:
        if self._disc_info is None:
            return len(meta.tracks) if meta is not None else 0
        return display_track_count(
            self._disc_info,
            meta or self._current_meta(),
            **self._track_hint_kwargs(),
        )

    def _effective_audio_tracks(self, meta: Metadata | None = None) -> list[int]:
        if self._disc_info is None:
            if meta is None:
                return []
            return sorted(
                {
                    track.number
                    for track in meta.tracks
                    if track.number > 0
                }
            )
        return effective_audio_track_numbers(
            self._disc_info,
            meta or self._current_meta(),
            **self._track_hint_kwargs(),
        )

    def _possible_extra_tracks(self, meta: Metadata | None = None) -> list[int]:
        if self._disc_info is None:
            return []
        return possible_data_track_numbers(
            self._disc_info,
            meta or self._current_meta(),
            **self._track_hint_kwargs(),
        )

    def _manual_search_disc_info(self, meta: Metadata | None = None) -> "DiscInfo | None":
        disc_info = self._disc_info
        if disc_info is None:
            return None

        audio_tracks = self._effective_audio_tracks(meta)
        if not audio_tracks or len(audio_tracks) >= disc_info.track_count:
            return disc_info

        normalized_count = len(audio_tracks)
        return replace(
            disc_info,
            track_count=normalized_count,
            track_modes={
                track_number: mode
                for track_number, mode in disc_info.track_modes.items()
                if 1 <= track_number <= normalized_count
            },
        )

    def _sync_track_selection(self) -> None:
        if self._disc_info is None:
            self._selected_tracks = {}
            return

        audio_tracks = set(self._effective_audio_tracks())
        if self._requested_tracks is None:
            defaults = set(audio_tracks)
        else:
            defaults = set(
                resolve_selected_tracks(
                    self._disc_info,
                    self._requested_tracks,
                    self._current_meta(),
                    **self._track_hint_kwargs(),
                )
            )
        self._selected_tracks = {
            track_number: self._selected_tracks.get(track_number, track_number in defaults)
            for track_number in range(1, self._disc_info.track_count + 1)
        }
        for track_number in list(self._selected_tracks):
            if track_number not in audio_tracks:
                self._selected_tracks[track_number] = False

    def _selected_audio_tracks(self) -> list[int]:
        if self._disc_info is None:
            return sorted(track for track, enabled in self._selected_tracks.items() if enabled)
        self._sync_track_selection()
        audio_tracks = set(self._effective_audio_tracks())
        return [
            track_number
            for track_number in range(1, self._disc_info.track_count + 1)
            if self._selected_tracks.get(track_number, False) and track_number in audio_tracks
        ]

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

    def _clear_album_fields(self) -> None:
        self.query_one("#input-artist", Input).value = ""
        self.query_one("#input-album", Input).value = ""
        self.query_one("#input-year", Input).value = ""
        try:
            self.query_one("#target-dir-input", Input).value = ""
        except Exception:
            pass
        self._target_is_base = False
        self._update_target_input()
        checkbox = self.query_one("#chk-cover-art", Checkbox)
        checkbox.value = False
        checkbox.disabled = True
        self._cover_art_available = False

    def _ensure_meta_tracks(self, meta: Metadata) -> list:
        from ..metadata.types import Track

        track_numbers = self._effective_audio_tracks(meta)
        if not track_numbers:
            if self._disc_info is not None and self._disc_info.track_count > 0:
                track_numbers = list(range(1, self._display_track_count(meta) + 1))
            elif meta.tracks:
                track_numbers = sorted({track.number for track in meta.tracks if track.number > 0})

        if not track_numbers:
            meta.tracks = sorted(meta.tracks, key=lambda track: track.number)
            return meta.tracks

        existing = {track.number: track for track in meta.tracks}
        meta.tracks = [
            existing.get(number)
            or Track(
                number=number,
                title="",
                artist="",
            )
            for number in track_numbers
        ]
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
            rows.append(
                Horizontal(
                    Checkbox(
                        "",
                        value=self._selected_tracks.get(track.number, True),
                        id=f"track-enabled-{track.number}",
                        classes="track-enable",
                        compact=True,
                    ),
                    Label(f"{track.number:02d}.", classes="track-no"),
                    Input(
                        value=track.title,
                        placeholder="Title",
                        id=f"track-title-{track.number}",
                        classes="track-title track-edit",
                        compact=True,
                    ),
                    Input(
                        value=track.artist,
                        placeholder="Artist",
                        id=f"track-artist-{track.number}",
                        classes="track-artist track-edit",
                        compact=True,
                    ),
                    Label(length, classes="track-len"),
                    Label("", classes="track-kind"),
                    classes="track-row",
                )
            )
        container.mount(*rows)

    def _resolve_device(self) -> str | None:
        from .. import device as dev_mod

        return self._args.device or (self._disc_info.device if self._disc_info else None) or dev_mod.detect()

    def _target_dir_value(self) -> str:
        """Return the raw value typed in the target directory input."""
        return self._input_val("target-dir-input")

    def _target_album_root(self) -> Path | None:
        from .. import library

        raw = self._target_dir_value()
        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        year = self._input_val("input-year")
        if raw:
            if self._target_is_base:
                if not artist and not album:
                    return Path(raw).expanduser()
                return library.album_root(raw, artist or "?", album or "?", year)
            return Path(raw).expanduser()
        if not artist and not album:
            return None
        return library.album_root(self._cfg.base_dir, artist or "?", album or "?", year)

    def _target_button_destination(self) -> tuple[Path | None, str, bool]:
        return _target_button_destination(self._target_album_root(), self._cfg.base_dir)

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

        path, label, _ = self._target_button_destination()
        btn.label = label
        btn.disabled = (
            self.phase not in {"ready", "done", "error"}
            or self._operation_busy
            or self._target_open_busy
            or path is None
            or _folder_open_command(path) is None
        )

    def _refresh_output_button(self) -> None:
        try:
            btn = self.query_one("#btn-outputs", Button)
        except Exception:
            return
        btn.disabled = self.phase == "running" or self._operation_busy

    def _has_detected_extras(self) -> bool:
        if self._extra_scan_bundle is not None:
            return bool(self._extra_scan_bundle.entries)
        if self._disc_info is None:
            return False
        if self._disc_info.data_track_numbers:
            return True
        return bool(self._possible_extra_tracks())

    def _refresh_extras_button(self) -> None:
        try:
            btn = self.query_one("#btn-extras", Button)
        except Exception:
            return

        selected_count = len(self._selected_extra_paths)
        available_count = len(self._extra_scan_bundle.entries) if self._extra_scan_bundle is not None else 0
        btn.label = _extras_button_label(selected_count, available_count).replace("  ", " ")
        btn.disabled = (
            self.phase != "ready"
            or self._operation_busy
            or self._disc_info is None
            or not self._has_detected_extras()
        )

    def _refresh_extras_notice(self) -> None:
        try:
            notice = self.query_one("#extras-notice", Static)
        except Exception:
            return

        available_count = len(self._extra_scan_bundle.entries) if self._extra_scan_bundle is not None else 0
        text = _extras_notice_text(
            len(self._selected_extra_paths),
            available_count,
            has_data_session=bool(self._disc_info and self._disc_info.data_track_numbers),
        )
        if text and self.phase == "ready":
            notice.update(text)
            self._show("extras-notice")
            return

        notice.update("")
        self._hide("extras-notice")

    def _maybe_notify_extras(self) -> None:
        if (
            self.phase != "ready"
            or self._disc_signature is None
            or self._extras_announced_signature == self._disc_signature
        ):
            return

        available_count = len(self._extra_scan_bundle.entries) if self._extra_scan_bundle is not None else 0
        message = _extras_announcement_text(
            available_count,
            has_data_session=bool(self._disc_info and self._disc_info.data_track_numbers),
        )
        if not message:
            return

        self._announce(message)
        self._extras_announced_signature = self._disc_signature

    def _set_metadata_search_controls_disabled(self, disabled: bool) -> None:
        for button_id in ("btn-more", "btn-sources"):
            try:
                self.query_one(f"#{button_id}", Button).disabled = disabled
            except Exception:
                pass

    def _refresh_import_buttons(self) -> None:
        enabled = (
            self.phase in {"ready", "error"}
            and not self._operation_busy
            and self._disc_info is not None
        )
        try:
            import_btn = self.query_one("#btn-import", Button)
            import_btn.disabled = not enabled
        except Exception:
            pass
        try:
            manual_btn = self.query_one("#btn-manual", Button)
            manual_btn.disabled = not enabled
        except Exception:
            pass

    def _sources_dict(self) -> dict[str, bool]:
        return {
            "cdtext": self._src_cdtext,
            "musicbrainz": self._src_mb,
            "gnudb": self._src_gnudb,
            "discogs": self._src_discogs,
        }

    def _outputs_dict(self) -> dict[str, bool]:
        return {
            "image": self._out_image,
            "iso": self._out_iso,
            "flac": self._out_flac,
            "mp3": self._out_mp3,
            "ogg": self._out_ogg,
            "opus": self._out_opus,
            "alac": self._out_alac,
            "aac": self._out_aac,
            "wav": self._out_wav,
        }

    def _extras_summary(self) -> str:
        from ..extras import human_size

        if self._extra_scan_bundle is None:
            return "No extra files have been scanned yet."
        total_size = sum(entry.size for entry in self._extra_scan_bundle.entries)
        if self._extra_scan_bundle.mount_root is not None:
            track_label = "Mounted data session"
        elif (
            self._disc_info is not None
            and self._extra_scan_bundle.track_number in self._disc_info.data_track_numbers
        ):
            track_label = "Data track"
        else:
            track_label = "Track"
        return (
            f"{track_label}"
            f"{f' {self._extra_scan_bundle.track_number}' if self._extra_scan_bundle.track_number is not None else ''} • "
            f"{len(self._extra_scan_bundle.entries)} file(s) • "
            f"{human_size(total_size)}"
        )

    def _clear_extras_state(self) -> None:
        if self._extra_scan_bundle is not None:
            self._extra_scan_bundle.close()
        self._extra_scan_bundle = None
        self._selected_extra_paths = []
        self._refresh_extras_button()
        self._refresh_extras_notice()

    def _output_options(self) -> list[tuple[str, str, bool]]:
        outputs = self._outputs_dict()
        return [
            (key, _output_option_label(key, self._args, self._cfg), outputs[key])
            for key in ("image", "iso", "flac", "mp3", "ogg", "opus", "alac", "aac", "wav")
        ]

    # ------------------------------------------------------------------
    # Phase 1 — detection + metadata fetch (background workers)
    # ------------------------------------------------------------------

    @work(thread=True, name="detect")
    def _start_detection(self, sources: dict[str, bool] | None = None) -> None:
        from .. import device as dev_mod, disc as disc_mod

        self._tlog("> Detecting CD device...")
        device = self._args.device or dev_mod.detect()
        if not device:
            self._tlog("[bold red]✗ No CD device found. Use --device to specify one.[/bold red]")
            self._tlog("[dim]Insert a disc and restart, or pass --device /dev/srN.[/dim]")
            self.call_from_thread(self._enter_error)
            return
        if not dev_mod.is_readable(device):
            self._tlog(f"[bold red]✗ {device}: no readable disc.[/bold red]")
            self._tlog("[dim]Insert a disc and wait — the drive will be polled automatically.[/dim]")
            self.call_from_thread(self._enter_error)
            return
        self._tlog(f"[green]✓[/green] Device: [bold]{device}[/bold]")

        self._tlog("> Reading disc TOC...")
        try:
            disc_info = disc_mod.load_disc_info(device, debug=bool(getattr(self._args, "debug", False)))
        except Exception as exc:
            self._tlog(f"[bold red]✗ Failed to read disc: {exc}[/bold red]")
            self.call_from_thread(self._enter_error)
            return
        disc_info.device = device
        self._disc_info = disc_info
        self._disc_signature = self._disc_sig(disc_info)
        self._watch_disc_present = True
        self._sync_track_selection()
        from .. import extras as extras_mod
        extra_scan_bundle, extra_probe_detail = extras_mod.probe_disc_extras(device)
        if extra_scan_bundle is not None:
            self.call_from_thread(self._finish_extras_probe, self._disc_signature, extra_scan_bundle, extra_probe_detail)
        self._tlog(
            f"[green]✓[/green] [bold]{display_track_count(disc_info, extra_track_number=extra_scan_bundle.track_number if extra_scan_bundle is not None else None, has_data_session=extra_scan_bundle is not None)} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
        )
        mb_notice = disc_mod.musicbrainz_lookup_notice(disc_info)
        if mb_notice:
            self._tlog(f"[yellow]![/yellow] {mb_notice}")
        if disc_info.data_track_numbers:
            self._tlog(
                "[yellow]![/yellow] This disc may include extra files."
            )
            self._tlog("> Use [bold]Extras[/bold] to inspect and choose files to copy.")

        try:
            self._run_meta_fetch(sources or self._sources_dict())
        except Exception as exc:
            self._tlog(f"[bold red]✗ Metadata error: {exc}[/bold red]")
            self.call_from_thread(self._enter_ready)

    def _run_meta_fetch(
        self,
        sources: dict,
        merge: bool = False,
        *,
        manual_query: str = "",
        manual_hints: tuple[str, str, str] | None = None,
        manual_only: bool = False,
    ) -> None:
        """Fetch metadata — runs in a worker thread (called from detect or meta worker).
        If merge=True, new results are added to existing candidates instead of replacing them.
        """
        from ..metadata import cdtext, musicbrainz, gnudb, local, discogs

        disc_info = self._disc_info
        if disc_info is None:
            self._tlog("[yellow]![/yellow] No disc info — insert a disc first.")
            self.call_from_thread(self._enter_ready)
            return

        cfg = self._cfg
        meta_debug = getattr(self._args, "metadata_debug", False) or self._args.debug
        timeout = cfg.metadata_timeout

        use_cdtext = sources.get("cdtext", True)
        use_mb = sources.get("musicbrainz", True)
        use_gnudb = sources.get("gnudb", True)
        use_discogs = sources.get("discogs", True)
        manual_search_disc_info = self._manual_search_disc_info()
        hint_artist = hint_album = hint_year = ""
        if manual_hints:
            hint_artist, hint_album, hint_year = manual_hints
        manual_query = manual_query.strip()
        has_manual_terms = bool(manual_query or hint_artist or hint_album)
        manual_only = manual_only and has_manual_terms
        self._last_meta_fetch_all_sources = use_cdtext and use_mb and use_gnudb and use_discogs

        active = [k for k, v in sources.items() if v] or ["all"]
        self._tlog(f"> Fetching metadata ({', '.join(active)})...")

        candidates: list = list(self._candidates) if merge else []

        def _add(metas: list) -> None:
            for m in metas:
                if m not in candidates:
                    candidates.append(m)

        if use_cdtext and disc_info.device:
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

        if not manual_only and cfg.use_local_cddb_cache and disc_info.freedb_disc_id:
            self._tlog("[dim]  → Local CDDB cache...[/dim]")
            try:
                r = local.lookup(disc_info, debug=meta_debug)
                _add(r)
                self._tlog(f"[dim]  ✓ Local CDDB cache: {len(r)} result(s)[/dim]")
            except Exception as exc:
                self._tlog(f"[dim]  ✗ Local CDDB cache: {exc}[/dim]")

        # MusicBrainz
        if use_mb:
            if not manual_only and (disc_info.mb_disc_id or disc_info.mb_toc):
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
                        query=manual_query,
                        disc_info=manual_search_disc_info,
                        timeout=timeout,
                        debug=meta_debug,
                    )
                    _add(r)
                    self._tlog(f"[dim]  ✓ MusicBrainz search: {len(r)} result(s)[/dim]")
                except Exception as exc:
                    self._tlog(f"[dim]  ✗ MusicBrainz search: {exc}[/dim]")

        # GnuDB HTTP
        if use_gnudb and not manual_only:
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

        if use_discogs:
            self._tlog("[dim]  → Discogs...[/dim]")
            if not cfg.discogs.token.strip():
                self._tlog(
                    "[dim]  · Discogs: using anonymous access; a token improves reliability and rate limits[/dim]"
                )
            if candidates or has_manual_terms:
                try:
                    r = discogs.lookup(
                        manual_search_disc_info or disc_info,
                        seed_candidates=[] if manual_only else candidates,
                        artist=hint_artist,
                        album=hint_album,
                        year=hint_year,
                        query=manual_query,
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
                    "[dim]  · Discogs: no search terms yet (use Manual Search, or fill tags and search again)[/dim]"
                )

        if manual_only:
            search_text = combine_search_text(
                manual_query,
                artist=hint_artist,
                album=hint_album,
                year=hint_year,
            )
            candidates = _sort_manual_search_candidates(candidates, search_text)

        self._candidates = candidates
        if candidates:
            self._tlog(
                f"[green]✓[/green] Found [bold]{len(candidates)}[/bold] metadata candidate(s)."
            )
        else:
            if not use_gnudb and cfg.gnudb.host.strip():
                self._tlog(
                    "[yellow]![/yellow] No metadata found from the selected sources. "
                    "GnuDB is configured but disabled in [bold]Sources[/bold]; enable it and search again."
                )
            if self._last_meta_fetch_all_sources:
                if has_manual_terms:
                    self._tlog(
                        "[yellow]![/yellow] No metadata found — adjust your search terms and try again, or enter tags manually."
                    )
                else:
                    self._tlog(
                        "[yellow]![/yellow] No metadata found — use Manual Search to query MusicBrainz/Discogs, or enter tags manually."
                    )
            else:
                self._tlog(
                    "[yellow]![/yellow] No metadata found — try another source selection, or search again with different terms."
                )
        self.call_from_thread(self._enter_ready)

    @work(thread=True, name="meta")
    def _start_meta_fetch(
        self,
        sources: dict | None = None,
        merge: bool = False,
        *,
        manual_query: str = "",
        manual_hints: tuple[str, str, str] | None = None,
        manual_only: bool = False,
    ) -> None:
        """Re-fetch metadata (F5 / Manual Search button). Runs in its own worker thread."""
        try:
            self._run_meta_fetch(
                sources or self._sources_dict(),
                merge=merge,
                manual_query=manual_query,
                manual_hints=manual_hints,
                manual_only=manual_only,
            )
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
            "extras-notice",
            "tags-row",
            "target-row",
        ):
            self._show(section)
        self._show("metadata-box")

        self.query_one("#btn-start", Button).disabled = False
        self._set_metadata_search_controls_disabled(False)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_extras_notice()
        self._refresh_import_buttons()
        hinted_extra_tracks = self._possible_extra_tracks()
        if (
            self._disc_info is not None
            and hinted_extra_tracks
            and not self._disc_info.data_track_numbers
        ):
            self._log(
                "[yellow]![/yellow] Metadata suggests this disc may include extra files."
            )
            self._log("> Use [bold]Extras[/bold] to inspect and choose files to copy.")
        self._maybe_notify_extras()
        self._update_target_input()
        self._update_cover_art_checkbox()
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

        self._update_target_input()
        self._update_cover_art_checkbox()

    def _update_target_input(self) -> None:
        """Update the placeholder to show the computed auto path. Does not modify the value."""
        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        year = self._input_val("input-year")
        from .. import library
        if artist or album:
            auto = library.album_root(self._cfg.base_dir, artist or "?", album or "?", year)
            placeholder = str(auto)
        else:
            placeholder = self._cfg.base_dir
        try:
            self.query_one("#target-dir-input", Input).placeholder = placeholder
        except Exception:
            pass
        self._refresh_target_button()

    def _update_cover_art_checkbox(self) -> None:
        from .. import artwork as artwork_mod

        meta = self._current_meta()
        if meta is None:
            meta = self._manual_meta_or_create()
        available = artwork_mod.has_cover_art(meta)
        self._cover_art_available = available
        checkbox = self.query_one("#chk-cover-art", Checkbox)
        checkbox.disabled = not available
        checkbox.value = self._cover_art_selected if available else False
        if not available:
            source_text = "unavailable"
        elif meta.cover_art_url:
            source_text = meta.source or "source"
        else:
            source_text = "Cover Art Archive"
        self.query_one("#cover-art-source", Label).update(f"[dim]({source_text})[/dim]")

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
        self._update_target_input()
        self._update_cover_art_checkbox()

    @on(Checkbox.Changed, "#chk-cover-art")
    def _on_cover_art_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.disabled:
            return
        self._cover_art_selected = event.value

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
            self._open_manual_search()
        elif bid == "btn-sources":
            self._open_metadata_search()
        elif bid == "btn-import":
            self._do_import()
        elif bid == "btn-manual":
            self._do_manual_entry()
        elif bid == "btn-browse":
            self._do_browse_dest()
        elif bid == "btn-target":
            self._do_open_target()
        elif bid == "btn-outputs":
            self._open_output_selector()
        elif bid == "btn-extras":
            self._open_extras_selector()
        elif bid == "btn-eject":
            self._do_eject()
        elif bid == "btn-start":
            self._do_start()
        elif bid == "btn-cancel":
            if self.phase == "running":
                self._confirm_cancel()
            else:
                self._force_exit()

    def action_open_settings(self) -> None:
        self._open_settings()

    def _do_browse_dest(self) -> None:
        raw = self._target_dir_value()
        if raw:
            start = Path(raw).expanduser()
        else:
            start = self._target_album_root() or Path(self._cfg.base_dir)
        self.push_screen(FolderPickerScreen(start_path=start), self._apply_browse_dest)

    def _apply_browse_dest(self, result: "tuple[Path, bool] | None") -> None:
        if result is None:
            return
        path, is_base = result
        if is_base:
            from .. import library
            artist = self._input_val("input-artist")
            album = self._input_val("input-album")
            year = self._input_val("input-year")
            if artist or album:
                # Metadata already known — resolve the full album path now
                full = library.album_root(str(path), artist or "?", album or "?", year)
                self._target_is_base = False
                self.query_one("#target-dir-input", Input).value = str(full)
                return
        # No metadata yet (or exact mode) — store as-is; _target_album_root resolves lazily
        self._target_is_base = is_base
        self.query_one("#target-dir-input", Input).value = str(path)

    def _open_settings(self) -> None:
        if self.phase == "running" or self._operation_busy:
            return
        self.push_screen(ConfigScreen(self._cfg), self._apply_settings)

    def _open_metadata_search(self) -> None:
        if self.phase == "running" or self._operation_busy:
            return
        self.push_screen(SourceSelectScreen(self._sources_dict()), self._apply_search_sources)

    def _open_manual_search(self) -> None:
        if self.phase == "running" or self._operation_busy:
            return
        search_text = self._metadata_search_query
        self.push_screen(
            TextPromptScreen(
                title="Manual Search",
                label="Search by artist, album, year, or any words.",
                value=search_text,
                placeholder="",
                submit_label="Search",
            ),
            self._apply_manual_search_prompt,
        )

    def _open_output_selector(self) -> None:
        if self.phase == "running" or self._operation_busy:
            return
        self.push_screen(OutputSelectScreen(self._output_options()), self._apply_outputs)

    def _open_extras_selector(self) -> None:
        if self.phase != "ready" or self._operation_busy:
            return
        if self._disc_info is None:
            self._log("[yellow]![/yellow] No disc is available for extra files.")
            return
        if self._extra_scan_bundle is not None:
            self._show_extras_selector()
            return

        self._operation_busy = True
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_import_buttons()
        self._refresh_extras_button()
        self._log("> Scanning extra files from the disc...")
        self._start_extras_scan(self._current_meta())

    @work(thread=True, name="extras-probe")
    def _start_extras_probe(self, device: str, signature: tuple | None) -> None:
        from .. import extras as extras_mod

        try:
            bundle, detail = extras_mod.probe_disc_extras(device)
        except Exception:
            bundle, detail = None, ""
        self.call_from_thread(self._finish_extras_probe, signature, bundle, detail)

    def _finish_extras_probe(
        self,
        signature: tuple | None,
        bundle: "ExtraScanBundle | None",
        detail: str,
    ) -> None:
        if signature != self._disc_signature:
            if bundle is not None:
                bundle.close()
            return

        if bundle is None:
            self._refresh_extras_button()
            self._refresh_extras_notice()
            return

        if self._extra_scan_bundle is not None:
            bundle.close()
            self._refresh_extras_button()
            self._refresh_extras_notice()
            return

        self._extra_scan_bundle = bundle
        self._selected_extra_paths = []
        self._sync_track_selection()
        if self.phase == "ready":
            self._render_track_editor(self._current_meta())
        self._log(f"[green]✓[/green] {detail}")
        self._log("> Use [bold]Extras[/bold] to inspect and choose files to copy.")
        self._refresh_extras_button()
        self._refresh_extras_notice()
        self._maybe_notify_extras()

    def _show_extras_selector(self) -> None:
        if self._extra_scan_bundle is None:
            return
        self.push_screen(
            ExtrasSelectScreen(
                list(self._extra_scan_bundle.entries),
                self._selected_extra_paths,
                self._extras_summary(),
            ),
            self._apply_extras_selection,
        )

    def _apply_extras_selection(self, selected_paths: list[str] | None) -> None:
        if selected_paths is None:
            return
        self._selected_extra_paths = list(selected_paths)
        count = len(self._selected_extra_paths)
        if count:
            self._log(f"[green]✓[/green] Selected {count} extra file(s) for copy.")
        else:
            self._log("> Cleared extra-file selection.")
        self._refresh_extras_button()
        self._refresh_extras_notice()

    def _apply_settings(self, updated_cfg: "Config" | None) -> None:
        if updated_cfg is None:
            return
        self._cfg = updated_cfg
        try:
            self._cfg.save()
        except OSError as exc:
            self._log(f"[bold red]✗ Failed to save settings: {exc}[/bold red]")
            return

        self._src_cdtext = self._cfg.default_src_cdtext
        self._src_mb = self._cfg.default_src_musicbrainz
        self._src_gnudb = self._cfg.default_src_gnudb
        self._src_discogs = self._cfg.default_src_discogs
        self._cover_art_selected = self._cfg.download_cover_art
        self._update_target_input()
        self._update_cover_art_checkbox()
        self._log("[green]✓[/green] Settings saved. Use [bold]Manual Search[/bold] to re-run metadata lookup with the current sources.")

    def _apply_search_sources(self, sources: dict[str, bool] | None) -> None:
        if sources is None:
            return
        self._src_cdtext = sources.get("cdtext", False)
        self._src_mb = sources.get("musicbrainz", False)
        self._src_gnudb = sources.get("gnudb", False)
        self._src_discogs = sources.get("discogs", False)
        self._do_fetch_metadata(sources)

    def _apply_outputs(self, outputs: dict[str, bool] | None) -> None:
        if outputs is None:
            return
        self._out_image = outputs.get("image", False)
        self._out_iso = outputs.get("iso", False)
        self._out_flac = outputs.get("flac", False)
        self._out_mp3 = outputs.get("mp3", False)
        self._out_ogg = outputs.get("ogg", False)
        self._out_opus = outputs.get("opus", False)
        self._out_alac = outputs.get("alac", False)
        self._out_aac = outputs.get("aac", False)
        self._out_wav = outputs.get("wav", False)

    @work(thread=True, name="extras-scan")
    def _start_extras_scan(self, meta: Metadata | None = None) -> None:
        from .. import extras as extras_mod

        disc_info = self._disc_info
        if disc_info is None:
            self.call_from_thread(self._finish_extras_scan, None, "No disc info is available for extras.")
            return

        try:
            bundle, detail = extras_mod.scan_disc_extras(
                disc_info.device,
                disc_info,
                self._cfg,
                meta=meta,
                work_dir=Path(self._cfg.work_dir),
                debug=bool(getattr(self._args, "debug", False)),
                process_callback=lambda proc: setattr(self, "_current_proc", proc),
            )
        except Exception as exc:
            self._current_proc = None
            self.call_from_thread(self._finish_extras_scan, None, f"Extras scan failed: {exc}")
            return
        self._current_proc = None
        self.call_from_thread(self._finish_extras_scan, bundle, detail)

    def _finish_extras_scan(self, bundle: "ExtraScanBundle | None", detail: str) -> None:
        previous_selection = set(self._selected_extra_paths)
        self._operation_busy = False
        self._current_proc = None

        if bundle is None:
            self.query_one("#btn-start", Button).disabled = False
            self._set_metadata_search_controls_disabled(False)
            self._refresh_eject_button()
            self._refresh_output_button()
            self._refresh_import_buttons()
            self._refresh_extras_button()
            self._refresh_extras_notice()
            self._log(f"[yellow]![/yellow] {detail}")
            return

        self._clear_extras_state()
        self._extra_scan_bundle = bundle
        self._selected_extra_paths = [
            entry.path for entry in bundle.entries if entry.path in previous_selection
        ]
        self.query_one("#btn-start", Button).disabled = False
        self._set_metadata_search_controls_disabled(False)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_import_buttons()
        self._refresh_extras_button()
        self._refresh_extras_notice()
        self._log(f"[green]✓[/green] {detail}")
        self._show_extras_selector()

    def _do_fetch_metadata(self, sources: dict[str, bool] | None = None) -> None:
        sources = sources or self._sources_dict()
        active = [k for k, v in sources.items() if v]
        if not active:
            self._log("[yellow]![/yellow] No sources selected — check at least one source.")
            return
        if self._operation_busy:
            return
        manual_query, manual_hints = self._manual_search_request()
        manual_only = bool(self._metadata_search_query.strip())
        self.phase = "detecting"
        self._operation_busy = True
        self._log(f"> Fetching metadata from: {', '.join(active)}")
        if manual_query:
            self._log(f"> Search terms: [bold]{manual_query}[/bold]")
        self._candidates = []
        self._selected_idx = 0
        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](fetching metadata...)[/dim]")
        self._set_metadata_search_controls_disabled(True)
        self.query_one("#btn-start", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()
        self._start_meta_fetch(
            sources,
            manual_query=manual_query,
            manual_hints=manual_hints,
            manual_only=manual_only,
        )

    def _apply_manual_search_prompt(self, value: str | None) -> None:
        if value is None:
            return
        self._metadata_search_query = value.strip()
        self._do_fetch_metadata()

    def _do_import(self) -> None:
        if self._operation_busy:
            return
        self.push_screen(
            MetadataImportPromptScreen(
                file_value=self._metadata_file_value(),
                url_value=self._metadata_url_value(),
            ),
            self._apply_import_prompt,
        )

    def _apply_import_prompt(self, result: tuple[str, str] | None) -> None:
        if result is None:
            return
        kind, value = result
        if kind == "file":
            self._metadata_file_path = value
        else:
            self._metadata_url = value
        if not value:
            self._log("[yellow]![/yellow] No import path is set.")
            self._refresh_output_button()
            self._refresh_extras_button()
            self._refresh_import_buttons()
            return
        self._start_import_from_value(kind, value)

    def _start_import_from_value(self, kind: str, value: str) -> None:
        if self._operation_busy:
            return
        self.phase = "detecting"
        self._operation_busy = True
        self._set_metadata_search_controls_disabled(True)
        self.query_one("#btn-start", Button).disabled = True
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()
        self._start_metadata_import(kind, value)

    def _do_manual_entry(self) -> None:
        """Switch to manual metadata entry mode, clearing any loaded candidates."""
        if self._operation_busy or self._disc_info is None:
            return
        from ..metadata.types import Metadata as MetaType

        self._candidates = []
        self._selected_idx = 0
        table = self.query_one("#meta-table", DataTable)
        table.clear(columns=True)

        # Create a fresh manual entry
        self._manual_meta = MetaType(
            source="Manual",
            album_artist="",
            album="",
            year="",
            match_quality="manual",
        )
        self._clear_album_fields()
        self._render_track_editor(self._manual_meta)
        self._update_target_input()
        self._update_cover_art_checkbox()
        self._log("> Switched to manual metadata entry.")

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
        self._set_metadata_search_controls_disabled(True)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()
        self._log(f"> Ejecting disc from [bold]{device}[/bold]...")
        self._start_eject(device)

    def _do_open_target(self) -> None:
        if self._target_open_busy or self.phase not in {"ready", "done", "error"}:
            return

        path, _label, exact_target = self._target_button_destination()
        if path is None:
            self._log("[yellow]![/yellow] No library folder is available to open.")
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
        year = self._input_val("input-year")
        outputs = self._outputs_dict()
        do_image = outputs["image"]
        do_iso = outputs["iso"]
        do_flac = outputs["flac"]
        do_mp3 = outputs["mp3"]
        do_ogg = outputs["ogg"]
        do_opus = outputs["opus"]
        do_alac = outputs["alac"]
        do_aac = outputs["aac"]
        do_wav = outputs["wav"]
        selected_extra_paths = list(self._selected_extra_paths)

        if not artist:
            self._log("[yellow]![/yellow] Artist is required.")
            return
        if not album:
            self._log("[yellow]![/yellow] Album is required.")
            return
        if do_iso and not do_image:
            self._log("[yellow]![/yellow] ISO export requires Disc image.")
            return
        if not any((do_image, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav)) and not selected_extra_paths:
            self._log("[yellow]![/yellow] Enable at least one output or select extra files.")
            return
        selected_tracks = self._selected_audio_tracks()
        if (do_flac or do_mp3 or do_ogg or do_opus or do_alac or do_aac or do_wav) and not selected_tracks:
            self._log("[yellow]![/yellow] Select at least one audio track.")
            return

        from .. import library

        album_root = self._target_album_root() or library.album_root(self._cfg.base_dir, artist, album, year)
        overwrite_outputs = dict(outputs)
        overwrite_outputs["extras"] = bool(selected_extra_paths)
        if _needs_overwrite_confirmation(album_root, overwrite_outputs):
            message = (
                "The target album directory already exists and may contain files.\n\n"
                f"{album_root}\n\n"
                "Starting may overwrite existing outputs."
            )
            self.push_screen(
                ConfirmScreen(
                    title="Existing Target Directory",
                    message=message,
                    confirm_label="Start Anyway",
                ),
                lambda confirmed: self._apply_start_confirmation(
                    confirmed,
                    artist,
                    album,
                    year,
                    do_image,
                    do_iso,
                    do_flac,
                    do_mp3,
                    do_ogg,
                    do_opus,
                    do_alac,
                    do_aac,
                    do_wav,
                    selected_tracks,
                    selected_extra_paths,
                ),
            )
            return

        self._begin_start(
            artist,
            album,
            year,
            do_image,
            do_iso,
            do_flac,
            do_mp3,
            do_ogg,
            do_opus,
            do_alac,
            do_aac,
            do_wav,
            selected_tracks,
            selected_extra_paths,
        )

    def _apply_start_confirmation(
        self,
        confirmed: bool | None,
        artist: str,
        album: str,
        year: str,
        do_image: bool,
        do_iso: bool,
        do_flac: bool,
        do_mp3: bool,
        do_ogg: bool,
        do_opus: bool,
        do_alac: bool,
        do_aac: bool,
        do_wav: bool,
        selected_tracks: list[int],
        selected_extra_paths: list[str],
    ) -> None:
        if not confirmed:
            self._log("[yellow]![/yellow] Start cancelled.")
            return

        self._begin_start(
            artist,
            album,
            year,
            do_image,
            do_iso,
            do_flac,
            do_mp3,
            do_ogg,
            do_opus,
            do_alac,
            do_aac,
            do_wav,
            selected_tracks,
            selected_extra_paths,
        )

    def _begin_start(
        self,
        artist: str,
        album: str,
        year: str,
        do_image: bool,
        do_iso: bool,
        do_flac: bool,
        do_mp3: bool,
        do_ogg: bool,
        do_opus: bool,
        do_alac: bool,
        do_aac: bool,
        do_wav: bool,
        selected_tracks: list[int],
        selected_extra_paths: list[str],
    ) -> None:
        self._last_rip_params = dict(
            artist=artist, album=album, year=year,
            do_image=do_image, do_iso=do_iso, do_flac=do_flac,
            do_mp3=do_mp3, do_ogg=do_ogg, do_opus=do_opus,
            do_alac=do_alac, do_aac=do_aac, do_wav=do_wav,
            selected_tracks=selected_tracks,
            selected_extra_paths=selected_extra_paths,
        )
        self.phase = "running"
        self._operation_busy = True
        self._last_accuraterip_status = ""
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()

        for section in (
            "candidates-section",
            "tracklist-scroll",
            "extras-notice",
            "tags-row",
            "target-row",
        ):
            self._hide(section)
        self._hide("metadata-box")
        self._pb_reset()
        self._show("progress-section")

        self.query_one("#btn-cancel", Button).label = "Cancel"

        self._start_rip(
            artist,
            album,
            year,
            do_image,
            do_iso,
            do_flac,
            do_mp3,
            do_ogg,
            do_opus,
            do_alac,
            do_aac,
            do_wav,
            selected_tracks,
            selected_extra_paths,
        )

    @work(thread=True, name="rip")
    def _start_rip(
        self,
        artist: str, album: str, year: str,
        do_image: bool, do_iso: bool, do_flac: bool, do_mp3: bool, do_ogg: bool,
        do_opus: bool, do_alac: bool, do_aac: bool, do_wav: bool,
        selected_tracks: list[int],
        selected_extra_paths: list[str],
    ) -> None:
        from ..metadata.types import Metadata as MetaType
        from ..pipeline import (
            BackupCallbacks,
            BackupRunError,
            BackupRunRequest,
            EncodeOptions,
            OutputSelection,
            run_backup,
        )

        args = self._args
        cfg = self._cfg
        enc = EncodeOptions(
            flac_compression=getattr(args, "flac_compression", 8),
            flac_verify=not getattr(args, "no_verify", False),
            mp3_quality=getattr(args, "mp3_quality", 2),
            mp3_bitrate=getattr(args, "mp3_bitrate", 320),
            debug=getattr(args, "debug", False),
        )

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
        if disc_info is None:
            self._cleanup.remove_all()
            self.call_from_thread(self._enter_error, "No disc info is available for ripping.")
            return

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
        cover_art_enabled = self._cover_art_selected and self._cover_art_available

        callbacks = BackupCallbacks(
            info=lambda msg: self._tlog(f"> {msg}"),
            warn=lambda msg: self._tlog(f"[yellow]![/yellow] {msg}"),
            success=lambda msg: self._tlog(f"[green]✓[/green] {msg}"),
            stage_start=lambda which, label, total: self.call_from_thread(self._pb_set, which, label, total),
            stage_progress=lambda which, current, total, label: self.call_from_thread(
                self._pb_update, which, current, total, label
            ),
            stage_done=lambda which, label: self.call_from_thread(self._pb_done, which, label),
            set_process=lambda proc: setattr(self, "_current_proc", proc),
        )

        try:
            result = run_backup(
                BackupRunRequest(
                    device=disc_info.device,
                    disc_info=disc_info,
                    meta=meta,
                    artist=artist,
                    album=album,
                    year=year,
                    outputs=outputs,
                    selected_tracks=selected_tracks,
                    cfg=cfg,
                    encode_opts=enc,
                    cleanup=self._cleanup,
                    cover_art_enabled=cover_art_enabled,
                    selected_extra_paths=selected_extra_paths,
                    extras_iso_path=self._extra_scan_bundle.iso_path if self._extra_scan_bundle is not None else None,
                    extras_mount_root=self._extra_scan_bundle.mount_root if self._extra_scan_bundle is not None else None,
                    album_root_override=self._target_album_root() if self._target_dir_value() else None,
                ),
                callbacks,
            )
        except BackupRunError as exc:
            self._current_proc = None
            self._cleanup.remove_all()
            self.call_from_thread(self._enter_error, str(exc))
            return

        self._current_proc = None
        self._last_accuraterip_status = result.accuraterip_detail
        self.call_from_thread(
            self._enter_done,
            result.album_root, artist, album, year, result.completed_track_count,
            meta.source, do_image, do_iso, do_flac, do_mp3, do_ogg, do_opus, do_alac, do_aac, do_wav,
            enc.flac_compression, enc.mp3_bitrate,
            selected_tracks, result.cover_art_path, cover_art_enabled, result.cue_path, result.iso_path,
            result.copied_extra_count,
        )

    # ------------------------------------------------------------------
    # Progress bar helpers (must be called on main thread)
    # ------------------------------------------------------------------

    def _pb_set(self, which: str, label: str, total: int | None) -> None:
        self._show(f"prog-{which}-row")
        self._stage_labels[which] = label
        self._active_stages.add(which)
        style = self._cfg.progress_style
        lbl = self.query_one(f"#prog-{which}-lbl", Label)
        lbl.remove_class("prog-lbl-active", "prog-lbl-bright")
        if style == "loading":
            lbl.update(label)
            self.query_one(f"#prog-{which}-spin", LoadingIndicator).display = True
        elif style == "color":
            lbl.update(label)
            lbl.add_class("prog-lbl-active")
        else:
            lbl.update(label)
        if style in ("spinner", "pulse") and self._anim_timer is None:
            self._anim_timer = self.set_interval(0.1, self._tick_animation)
        self.query_one(f"#prog-{which}", ProgressBar).update(total=total, progress=0)

    def _pb_update(self, which: str, current: int, total: int, label: str) -> None:
        self._show(f"prog-{which}-row")
        self._stage_labels[which] = label
        if self._cfg.progress_style != "spinner":
            self.query_one(f"#prog-{which}-lbl", Label).update(label)
        self.query_one(f"#prog-{which}", ProgressBar).update(total=total, progress=current)

    def _pb_done(self, which: str, label: str) -> None:
        self._show(f"prog-{which}-row")
        self._active_stages.discard(which)
        self._stage_labels.pop(which, None)
        style = self._cfg.progress_style
        lbl = self.query_one(f"#prog-{which}-lbl", Label)
        lbl.update(f"[green]{label}[/green]")
        lbl.remove_class("prog-lbl-active", "prog-lbl-bright")
        if style == "loading":
            self.query_one(f"#prog-{which}-spin", LoadingIndicator).display = False
        if not self._active_stages and self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None
        pb = self.query_one(f"#prog-{which}", ProgressBar)
        pb.update(progress=pb.total or 1)

    def _pb_reset(self) -> None:
        if self._anim_timer is not None:
            self._anim_timer.stop()
            self._anim_timer = None
        self._active_stages.clear()
        self._stage_labels.clear()
        self._spinner_frame = 0
        self._anim_tick = 0
        for which in _PROGRESS_KEYS:
            self._hide(f"prog-{which}-row")
            lbl = self.query_one(f"#prog-{which}-lbl", Label)
            lbl.update("")
            lbl.remove_class("prog-lbl-active", "prog-lbl-bright")
            self.query_one(f"#prog-{which}-spin", LoadingIndicator).display = False
            self.query_one(f"#prog-{which}", ProgressBar).update(total=None, progress=0)

    def _tick_animation(self) -> None:
        """Timer callback — advances spinner/pulse animation for all active stages."""
        style = self._cfg.progress_style
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        self._anim_tick += 1
        for which in list(self._active_stages):
            base = self._stage_labels.get(which, "")
            lbl = self.query_one(f"#prog-{which}-lbl", Label)
            if style == "spinner":
                frame = _SPINNER_FRAMES[self._spinner_frame]
                lbl.update(f"{frame} {base}")
            elif style == "pulse":
                if self._anim_tick % 10 < 5:
                    lbl.add_class("prog-lbl-bright")
                    lbl.remove_class("prog-lbl")
                else:
                    lbl.remove_class("prog-lbl-bright")
                    lbl.add_class("prog-lbl")

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
            self._set_metadata_search_controls_disabled(False)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
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
                disc_info = disc_mod.load_disc_info(device, debug=bool(getattr(self._args, "debug", False)))
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
        self._metadata_search_query = ""
        self._selected_idx = 0
        self._selected_tracks = {}
        self._clear_extras_state()
        self._last_accuraterip_status = ""
        self._target_is_base = False
        try:
            self.query_one("#target-dir-input", Input).value = ""
        except Exception:
            pass
        self._sync_track_selection()

        self._hide("done-section")
        self._hide("progress-section")
        self._show("metadata-box")
        for section in (
            "candidates-section",
            "tracklist-scroll",
            "extras-notice",
            "tags-row",
            "target-row",
        ):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](loading new disc metadata...)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()

        if previous_phase == "done":
            self._log("> New disc detected.")
        else:
            self._log("> Disc detected.")
        self._log(
            f"[green]✓[/green] [bold]{display_track_count(disc_info)} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
        )
        if disc_info.data_track_numbers:
            self._log(
                "[yellow]![/yellow] This disc may include extra files."
            )
            self._log("> Use [bold]Extras[/bold] to inspect and choose files to copy.")
        self._start_extras_probe(disc_info.device, signature)
        self._start_meta_fetch(self._sources_dict())

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
        flac_compression: int,
        mp3_bitrate: int,
        selected_tracks: list[int],
        cover_art_path: Path | None,
        cover_art_enabled: bool,
        cue_path: Path | None,
        iso_path: Path | None,
        copied_extra_count: int,
    ) -> None:
        self.phase = "done"
        self._operation_busy = False
        self._watch_disc_present = True
        self._show("progress-section")
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()

        formats = []
        if do_image:
            formats.append("Disc image")
        if cue_path is not None:
            formats.append("CUE sidecar")
        if do_iso and iso_path is not None:
            formats.append("ISO data")
        if do_flac:
            formats.append(f"FLAC (lvl {flac_compression})")
        if do_mp3:
            mp3_desc = f"{mp3_bitrate} kbps" if mp3_bitrate > 0 else "VBR"
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
        if copied_extra_count:
            formats.append(f"Extra files ({copied_extra_count})")

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
        elif cover_art_enabled:
            details_lines.append("  Cover art: [dim]not downloaded[/dim]")
        if copied_extra_count:
            details_lines.append(f"  Extra files: {copied_extra_count}")

        self.query_one("#done-title", Label).update("[bold green]✓ Done![/bold green]")
        self.query_one("#done-details", Static).update("\n".join(details_lines))
        self._show("done-section")
        self._log(f"[green]✓[/green] Rip complete: [bold]{artist}[/bold] — {album}")
        self._start_completion_alerts(
            "DiscVault rip complete",
            f"{artist} — {album}",
        )

        self.query_one("#btn-cancel", Button).label = "Quit"
        self.query_one("#btn-cancel", Button).disabled = False
        self.query_one("#btn-cancel", Button).focus()

    def _enter_error(self, message: str = "") -> None:
        from .confirm import ErrorScreen
        from ..pipeline import IMAGE_RIP_ERROR_PREFIX
        self._pb_reset()
        if self._cancel_requested:
            self._cancel_requested = False
            self._enter_waiting_for_disc("Rip cancelled.")
            return
        if message:
            is_image_error = message.startswith(IMAGE_RIP_ERROR_PREFIX)
            display_msg = message.removeprefix(IMAGE_RIP_ERROR_PREFIX)
            retry_label = ""
            if is_image_error and self._last_rip_params is not None:
                current_tool = self._cfg.image_ripper
                alt_tool = "readom" if current_tool == "cdrdao" else "cdrdao"
                retry_label = f"Retry with {alt_tool}"
            self.push_screen(
                ErrorScreen(message=display_msg, retry_label=retry_label),
                lambda result: self._apply_error_dismissed(result, display_msg),
            )
            return
        # Detection / init error — no progress was running, just set error state
        self.phase = "error"
        self._operation_busy = False
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        btn = self.query_one("#btn-cancel", Button)
        btn.label = "Quit"
        btn.disabled = False
        self._refresh_eject_button()
        self._refresh_output_button()
        self._refresh_extras_button()
        self._refresh_import_buttons()

    def _apply_error_dismissed(self, result: str | None, display_msg: str) -> None:
        if result == "retry" and self._last_rip_params is not None:
            current_tool = self._cfg.image_ripper
            alt_tool = "readom" if current_tool == "cdrdao" else "cdrdao"
            self._cfg.image_ripper = alt_tool
            self._log(f"> Retrying with {alt_tool}...")
            p = self._last_rip_params
            self._begin_start(
                p["artist"], p["album"], p["year"],
                p["do_image"], p["do_iso"], p["do_flac"],
                p["do_mp3"], p["do_ogg"], p["do_opus"],
                p["do_alac"], p["do_aac"], p["do_wav"],
                p["selected_tracks"], p["selected_extra_paths"],
            )
        else:
            self._enter_waiting_for_disc(f"[bold red]✗ Rip failed:[/bold red] {display_msg}")

    def _enter_waiting_for_disc(self, message: str) -> None:
        self.phase = "error"
        self._operation_busy = False
        self._watch_disc_present = False
        self._candidates = []
        self._manual_meta = None
        self._metadata_search_query = ""
        self._selected_idx = 0
        self._selected_tracks = {}
        self._clear_extras_state()
        self._clear_album_fields()

        self._hide("done-section")
        self._hide("progress-section")
        self._show("metadata-box")
        for section in (
            "candidates-section",
            "tracklist-scroll",
            "tags-row",
            "target-row",
        ):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](insert a disc to load metadata)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self._set_metadata_search_controls_disabled(True)
        self._refresh_target_button()
        self._refresh_output_button()
        self._refresh_extras_button()
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

    def action_copy_selection(self) -> None:
        """Copy selected text from focused widget to clipboard."""
        from textual.widgets import TextArea, Input

        focused = self.focused
        text = ""

        if isinstance(focused, TextArea):
            text = focused.selected_text
        elif isinstance(focused, Input):
            # Input widget: copy entire value if no selection API
            text = focused.value

        if text:
            if _copy_to_clipboard(text):
                self._announce("Copied to clipboard", severity="success")
            else:
                self._announce("Clipboard unavailable", severity="warning")

    def action_cancel_or_quit(self) -> None:
        if self.phase == "running":
            self._confirm_cancel()
        else:
            self._force_exit()

    def _confirm_cancel(self) -> None:
        album_root = self._target_album_root()
        if album_root:
            message = (
                f"Stop the current rip?\n\n"
                f"Partial output will be deleted:\n  {album_root}"
            )
        else:
            message = "Stop the current rip? Any partial output will be deleted."
        self.push_screen(
            ConfirmScreen(title="Cancel rip", message=message, confirm_label="Cancel rip"),
            self._apply_cancel_confirmed,
        )

    def _apply_cancel_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self._cancel_requested = True
        self._kill_current()

    def _force_exit(self) -> None:
        """Kill subprocess, cancel workers, then exit (lets Textual restore terminal)."""
        self._shutting_down = True
        if self._disc_watch_timer is not None:
            self._disc_watch_timer.stop()
        self._clear_extras_state()
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

    def action_show_help(self) -> None:
        from textual.screen import ModalScreen
        from textual.widgets import Markdown
        from textual.containers import Center

        help_text = """\
# DiscVault — Keyboard Reference

| Key | Action |
|-----|--------|
| **Enter / Start** | Begin ripping when ready |
| **Escape** | Cancel running rip (with confirm) / quit from idle |
| **Ctrl+C** | Force quit |
| **F5** | Re-fetch metadata |
| **Ctrl+,** | Open settings |
| **Ctrl+K** | Command palette |
| **?** | This help screen |

## Workflow
1. Insert a disc — metadata is fetched automatically.
2. Select a metadata candidate from the table (or edit tags manually).
3. Edit track titles/artists inline if needed.
4. Choose output formats via **Select Outputs**.
5. Use **Extras** when the disc includes extra files to choose what to copy.
6. Optionally edit the target directory path directly in the path field.
7. Press **Start** to rip.

## Tips
- Use **Import** to choose either a metadata file or a supported URL, then enter it in a single path field.
- Use **Manual Search** to open a popup for free-form metadata lookup.
- **Sources…** lets you choose which metadata providers to query.
- **Extras** appears when DiscVault detects extra files and lets you pick what goes into the `extras/` folder.
- The disc is polled every 4 s; swap discs anytime from the done screen.
"""

        class HelpScreen(ModalScreen):
            BINDINGS = [("escape,question_mark,q", "dismiss", "Close")]

            def compose(self):
                with Center():
                    yield Markdown(help_text, id="help-content")

        self.push_screen(HelpScreen())

    def _kill_current(self) -> None:
        proc = self._current_proc
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
                proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
