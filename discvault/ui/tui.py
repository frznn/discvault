"""Full Textual TUI for discvault."""
from __future__ import annotations

import datetime
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


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """
Screen {
    background: $background;
}

#lib-row {
    height: auto;
    min-height: 1;
    margin: 0 1 1 1;
    align: left middle;
}

#lib-lbl {
    width: auto;
    padding: 0 1 0 0;
}

#input-library {
    width: 1fr;
}

#sources-row {
    height: auto;
    min-height: 1;
    margin: 1 1 1 1;
    padding: 0 1;
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

#outputs-row {
    height: auto;
    min-height: 1;
    margin: 0 1;
    padding: 0 1;
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

#btn-more   { min-width: 16; }
#btn-eject  { min-width: 12; margin-left: 2; }
#btn-start  { min-width: 12; margin-left: 2; }
#btn-cancel { min-width: 12; margin-left: 2; }
"""


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

class DiscvaultApp(App[None]):
    """Full discvault TUI."""

    CSS = _CSS
    TITLE = "DiscVault"
    COMMAND_PALETTE_BINDING = "ctrl+k"

    BINDINGS = [
        Binding("ctrl+c", "quit_app", "Quit", priority=True),
        Binding("escape", "cancel_or_quit", "Cancel / Quit"),
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
        self._candidates: list[Metadata] = []
        self._manual_meta: Metadata | None = None
        self._selected_idx: int = 0
        self._current_proc: subprocess.Popen | None = None
        self._operation_busy = False  # guard against overlapping fetch/rip actions
        # Source enable/disable — initialized from preferred_metadata_source config
        preferred = cfg.preferred_metadata_source or "musicbrainz"
        self._src_mb = (preferred == "musicbrainz")
        self._src_gnudb = (preferred == "gnudb")
        self._src_cdtext = (preferred == "cdtext")
        from ..cleanup import Cleanup
        self._cleanup = Cleanup()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)

        with Vertical(id="outer"):
            with ScrollableContainer(id="main-scroll"):
                # Library dir (always visible, editable)
                with Horizontal(id="lib-row"):
                    yield Label("Library:", id="lib-lbl")
                    yield Input(value=self._cfg.base_dir, id="input-library",
                                compact=True,
                                placeholder="Library base directory")

                # Always-visible status log
                yield RichLog(id="status-log", highlight=True, markup=True, max_lines=200)

                # Metadata source toggles
                with Horizontal(id="sources-row"):
                    yield Label("Sources:", id="sources-lbl")
                    yield Checkbox("MusicBrainz", value=self._src_mb, id="chk-src-mb", compact=True)
                    yield Checkbox("GnuDB", value=self._src_gnudb, id="chk-src-gnudb", compact=True)
                    yield Checkbox("CD-Text", value=self._src_cdtext, id="chk-src-cdtext", compact=True)

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

                yield Label("", id="target-label", markup=True)

                # Ready phase: output checkboxes
                mp3_label = f"MP3 {self._args.mp3_bitrate} kbps" if self._args.mp3_bitrate > 0 else "MP3 VBR"
                with Horizontal(id="outputs-row"):
                    yield Checkbox("Disc image", value=not self._args.no_image, id="chk-image", compact=True)
                    yield Checkbox(f"FLAC lvl {self._args.flac_compression}", value=not self._args.no_flac, id="chk-flac", compact=True)
                    yield Checkbox(mp3_label, value=not self._args.no_mp3, id="chk-mp3", compact=True)
                    yield Checkbox("OGG Vorbis", value=getattr(self._args, "ogg", False), id="chk-ogg", compact=True)

                # Running phase: progress bars
                with Vertical(id="progress-section"):
                    with Vertical(id="prog-image-row", classes="prog-row"):
                        yield Label("", id="prog-image-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-image", show_eta=False)
                    with Vertical(id="prog-flac-row", classes="prog-row"):
                        yield Label("", id="prog-flac-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-flac", show_eta=False)
                    with Vertical(id="prog-mp3-row", classes="prog-row"):
                        yield Label("", id="prog-mp3-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-mp3", show_eta=False)
                    with Vertical(id="prog-ogg-row", classes="prog-row"):
                        yield Label("", id="prog-ogg-lbl", classes="prog-lbl")
                        yield ProgressBar(id="prog-ogg", show_eta=False)

                # Done phase: summary
                with Vertical(id="done-section"):
                    yield Label("", id="done-title", markup=True)
                    yield Static("", id="done-details", markup=True)

            # Action bar — inside #outer, always visible below the scroll area
            with Horizontal(id="action-bar"):
                yield Button("Fetch Metadata", id="btn-more", disabled=True)
                with Horizontal(id="action-right"):
                    yield Button("Eject CD", id="btn-eject", disabled=True)
                    yield Button("Start", id="btn-start", variant="success", disabled=True)
                    yield Button("Quit", id="btn-cancel", variant="error")

        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.phase = "detecting"
        self._log(f"[bold]discvault[/bold] starting up...")
        self.set_interval(4.0, self._schedule_disc_watch)
        self._refresh_eject_button()
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
            existing.get(number) or Track(number=number, title="", artist="")
            for number in range(1, total_tracks + 1)
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

        track_lengths = self._disc_info.track_lengths if self._disc_info else {}
        rows = []
        for track in tracks:
            secs = track_lengths.get(track.number, 0)
            length = f"{secs // 60}:{secs % 60:02d}" if secs else ""
            rows.append(
                Horizontal(
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
                    classes="track-row",
                )
            )
        container.mount(*rows)

    def _resolve_device(self) -> str | None:
        from .. import device as dev_mod

        return self._args.device or (self._disc_info.device if self._disc_info else None) or dev_mod.detect()

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
                }
            except Exception:
                sources = {
                    "musicbrainz": self._src_mb,
                    "gnudb": self._src_gnudb,
                    "cdtext": self._src_cdtext,
                }
            self._src_mb = sources["musicbrainz"]
            self._src_gnudb = sources["gnudb"]
            self._src_cdtext = sources["cdtext"]
            return sources

        return {
            "musicbrainz": self._src_mb,
            "gnudb": self._src_gnudb,
            "cdtext": self._src_cdtext,
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
        self._tlog(
            f"[green]✓[/green] [bold]{disc_info.track_count} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
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
        from ..metadata import musicbrainz, gnudb, cdtext, local

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
            else:
                self._tlog("[dim]  · MusicBrainz: no disc ID[/dim]")

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

        self._candidates = candidates
        if candidates:
            self._tlog(
                f"[green]✓[/green] Found [bold]{len(candidates)}[/bold] metadata candidate(s)."
            )
        else:
            self._tlog("[yellow]![/yellow] No metadata found — enter tags manually.")
        self.call_from_thread(self._enter_ready)

    @work(thread=True, name="meta")
    def _start_meta_fetch(self, sources: dict | None = None, merge: bool = False) -> None:
        """Re-fetch metadata (F5 / Fetch Metadata button). Runs in its own worker thread."""
        try:
            self._run_meta_fetch(sources or self._sources_dict(), merge=merge)
        except Exception as exc:
            self._tlog(f"[bold red]✗ Metadata error: {exc}[/bold red]")
            self.call_from_thread(self._enter_ready)

    # ------------------------------------------------------------------
    # Phase 2 — ready: show candidates + tags + outputs
    # ------------------------------------------------------------------

    def _enter_ready(self) -> None:
        self.phase = "ready"
        self._operation_busy = False
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
            table.move_cursor(row=0)

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
            self._apply_candidate(0)
        else:
            self._render_track_editor(self._manual_meta_or_create())

        for section in ("candidates-section", "tracklist-scroll",
                        "tags-row", "target-label", "outputs-row"):
            self._show(section)

        self.query_one("#btn-start", Button).disabled = False
        self.query_one("#btn-more", Button).disabled = False
        self._refresh_eject_button()
        self._update_target_label()

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

    # ------------------------------------------------------------------
    # Events in ready phase
    # ------------------------------------------------------------------

    @on(DataTable.RowHighlighted, "#meta-table")
    def _on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._selected_idx = event.cursor_row
        self._apply_candidate(self._selected_idx)

    @on(Input.Changed, "#input-artist, #input-album, #input-year")
    def _on_tag_changed(self, _event: Input.Changed) -> None:
        self._update_target_label()

    @on(Input.Changed, "#input-library")
    def _on_library_changed(self, event: Input.Changed) -> None:
        self._cfg.base_dir = event.value.strip() or self._cfg.base_dir
        self._update_target_label()

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

    # ------------------------------------------------------------------
    # Phase 3 — running: rip + encode
    # ------------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-more":
            self._do_fetch_metadata()
        elif bid == "btn-eject":
            self._do_eject()
        elif bid == "btn-start":
            self._do_start()
        elif bid == "btn-cancel":
            self._force_exit()

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
        self._start_meta_fetch(sources)

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
        self._log(f"> Ejecting disc from [bold]{device}[/bold]...")
        self._start_eject(device)

    def _do_start(self) -> None:
        if self._operation_busy:
            return
        artist = self._input_val("input-artist")
        album = self._input_val("input-album")
        do_image = self._checkbox_val("chk-image")
        do_flac = self._checkbox_val("chk-flac")
        do_mp3 = self._checkbox_val("chk-mp3")
        do_ogg = self._checkbox_val("chk-ogg")

        if not artist:
            self._log("[yellow]![/yellow] Artist is required.")
            return
        if not album:
            self._log("[yellow]![/yellow] Album is required.")
            return
        if not do_image and not do_flac and not do_mp3 and not do_ogg:
            self._log("[yellow]![/yellow] Enable at least one output.")
            return

        self.phase = "running"
        self._operation_busy = True
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()

        for section in ("candidates-section", "tracklist-scroll",
                        "tags-row", "target-label", "outputs-row"):
            self._hide(section)
        self._hide("sources-row")
        self._pb_reset()
        self._show("progress-section")

        self.query_one("#btn-cancel", Button).label = "Cancel"

        self._start_rip(artist, album,
                        self._input_val("input-year"),
                        do_image, do_flac, do_mp3, do_ogg)

    @work(thread=True, name="rip")
    def _start_rip(
        self,
        artist: str, album: str, year: str,
        do_image: bool, do_flac: bool, do_mp3: bool, do_ogg: bool,
    ) -> None:
        from .. import rip as rip_mod, encode as enc_mod, library
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

        album_root = library.album_root(cfg.base_dir, artist, album, year)
        img_dir = library.image_dir(album_root)
        fl_dir = library.flac_dir(album_root)
        mp_dir = library.mp3_dir(album_root)
        og_dir = library.ogg_dir(album_root)

        work_dir = Path(cfg.work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup.track_dir(work_dir)

        toc_path = bin_path = None
        wav_files: list[Path] = []
        audio_formats: list[tuple[str, str]] = []
        if do_flac:
            audio_formats.append(("flac", "FLAC"))
        if do_mp3:
            audio_formats.append(("mp3", "MP3"))
        if do_ogg:
            audio_formats.append(("ogg", "OGG Vorbis"))

        # ── Disc image ──────────────────────────────────────────────
        if do_image:
            self._tlog("> Creating disc image...")
            self.call_from_thread(
                self._pb_set, "image", "Creating disc image (cdrdao)...", track_count or None
            )
            stem = library.image_stem(artist, album, year)
            img_dir.mkdir(parents=True, exist_ok=True)
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

        # ── Audio outputs ───────────────────────────────────────────
        if audio_formats:
            primary_key, primary_name = audio_formats[0]
            self._tlog(f"> Ripping tracks to {primary_name} format...")
            self.call_from_thread(
                self._pb_set,
                primary_key,
                f"Ripping tracks to {primary_name} format...",
                (track_count * 2) or None,
            )

            def audio_cb(current: int, total: int, fname: str = "") -> None:
                combined_total = max(total * 2, 1)
                label = f"Ripping tracks to {primary_name} format ({current}/{total})"
                if fname:
                    label = f"{label}: {fname}"
                self.call_from_thread(
                    self._pb_update, primary_key, current, combined_total, label
                )

            wav_files = rip_mod.rip_audio(
                device, work_dir, track_count, self._cleanup,
                debug=args.debug,
                progress_callback=audio_cb,
                process_callback=lambda p: setattr(self, "_current_proc", p),
            )
            self._current_proc = None
            if wav_files is None:
                self._tlog(f"[bold red]✗ Failed to rip tracks for {primary_name} format.[/bold red]")
                self._cleanup.remove_all()
                self.call_from_thread(self._enter_error)
                return
            self._tlog(f"[green]✓[/green] Source tracks ready for {primary_name} format.")

            self._cleanup.track_dir(album_root)

            def _encode_one_format(fmt_key: str, fmt_name: str, *, include_rip_phase: bool) -> bool:
                total_tracks = len(wav_files)
                if not include_rip_phase:
                    self.call_from_thread(
                        self._pb_set,
                        fmt_key,
                        f"Encoding tracks to {fmt_name} format...",
                        total_tracks or None,
                    )

                self._tlog(f"> Encoding tracks to {fmt_name} format...")

                def encode_cb(done: int, total: int) -> None:
                    if include_rip_phase:
                        combined_total = max(total * 2, 1)
                        current = min(total + done, combined_total)
                        bar_total = combined_total
                    else:
                        current = done
                        bar_total = max(total, 1)
                    self.call_from_thread(
                        self._pb_update,
                        fmt_key,
                        current,
                        bar_total,
                        f"Encoding tracks to {fmt_name} format ({done}/{total})",
                    )

                ok = enc_mod.encode_tracks(
                    wav_files, meta,
                    flac_dir=fl_dir if fmt_key == "flac" else None,
                    mp3_dir=mp_dir if fmt_key == "mp3" else None,
                    ogg_dir=og_dir if fmt_key == "ogg" else None,
                    flac_compression=args.flac_compression,
                    flac_verify=not args.no_verify,
                    mp3_quality=args.mp3_quality,
                    mp3_bitrate=args.mp3_bitrate,
                    cleanup=self._cleanup,
                    debug=args.debug,
                    progress_callback=encode_cb,
                )
                if ok:
                    self._tlog(f"[green]✓[/green] {fmt_name} format complete.")
                    self.call_from_thread(self._pb_done, fmt_key, f"✓ {fmt_name} format")
                return ok

            if not _encode_one_format(primary_key, primary_name, include_rip_phase=True):
                self._tlog(f"[bold red]✗ Encoding to {primary_name} format failed.[/bold red]")
                self._cleanup.remove_all()
                self.call_from_thread(self._enter_error)
                return

            for fmt_key, fmt_name in audio_formats[1:]:
                if not _encode_one_format(fmt_key, fmt_name, include_rip_phase=False):
                    self._tlog(f"[bold red]✗ Encoding to {fmt_name} format failed.[/bold red]")
                    self._cleanup.remove_all()
                    self.call_from_thread(self._enter_error)
                    return

        # ── backup-info.txt ─────────────────────────────────────────
        self._write_backup_info(
            album_root, device, artist, album, year, meta.source,
            wav_files, track_count, toc_path, bin_path, do_image, do_flac, do_mp3, do_ogg, args,
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
            meta.source, do_image, do_flac, do_mp3, do_ogg, args,
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
        for which in ("image", "flac", "mp3", "ogg"):
            self._hide(f"prog-{which}-row")
            self.query_one(f"#prog-{which}-lbl", Label).update("")
            self.query_one(f"#prog-{which}", ProgressBar).update(total=None, progress=0)

    def _play_done_sound(self) -> None:
        self.bell()
        self.set_timer(0.15, self.bell)

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

    # ------------------------------------------------------------------
    # Disc watch
    # ------------------------------------------------------------------

    def _schedule_disc_watch(self) -> None:
        if self.phase not in {"ready", "done", "error"} or self._operation_busy or self._disc_watch_busy:
            return
        self._disc_watch_busy = True
        self._poll_disc_change()

    @work(thread=True, name="disc-watch")
    def _poll_disc_change(self) -> None:
        from .. import device as dev_mod, disc as disc_mod

        try:
            device = self._args.device or (self._disc_info.device if self._disc_info else None) or dev_mod.detect()
            if not device or not dev_mod.is_readable(device):
                self.call_from_thread(self._mark_disc_absent)
                return

            try:
                disc_info = disc_mod.load_disc_info(device)
            except Exception:
                return
            disc_info.device = device
            signature = self._disc_sig(disc_info)
            should_reload = (self._watch_disc_present is False) or (signature != self._disc_signature)
            if should_reload:
                self.call_from_thread(self._reload_for_new_disc, disc_info, signature)
            else:
                self.call_from_thread(self._mark_disc_present)
        finally:
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

        self._hide("done-section")
        self._hide("progress-section")
        self._show("sources-row")
        for section in ("candidates-section", "tracklist-scroll", "tags-row", "target-label", "outputs-row"):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](loading new disc metadata...)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()

        if previous_phase == "done":
            self._log("> New disc detected.")
        else:
            self._log("> Disc detected.")
        self._log(
            f"[green]✓[/green] [bold]{disc_info.track_count} tracks[/bold]  "
            f"FreeDB: {disc_info.freedb_disc_id or '(none)'}  "
            f"MB: {disc_info.mb_disc_id or '(none)'}"
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
        do_flac: bool,
        do_mp3: bool,
        do_ogg: bool,
        args,
    ) -> None:
        self.phase = "done"
        self._operation_busy = False
        self._watch_disc_present = True
        self._show("progress-section")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True
        self._refresh_eject_button()

        formats = []
        if do_image:
            formats.append("Disc image")
        if do_flac:
            formats.append(f"FLAC (lvl {args.flac_compression})")
        if do_mp3:
            mp3_desc = f"{args.mp3_bitrate} kbps" if args.mp3_bitrate > 0 else "VBR"
            formats.append(f"MP3 ({mp3_desc})")
        if do_ogg:
            formats.append("OGG Vorbis")

        year_str = f" ({year})" if year else ""
        details_lines = [
            f"  [bold]{artist}[/bold] — {album}{year_str}",
            f"  Tracks: {track_count}",
            f"  Formats: {', '.join(formats) if formats else '(none)'}",
            f"  Source: {meta_source}",
            f"  Saved to: [dim]{album_root}[/dim]",
        ]

        self.query_one("#done-title", Label).update("[bold green]✓ Done![/bold green]")
        self.query_one("#done-details", Static).update("\n".join(details_lines))
        self._show("done-section")
        self._play_done_sound()

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

    def _enter_waiting_for_disc(self, message: str) -> None:
        self.phase = "error"
        self._operation_busy = False
        self._watch_disc_present = False
        self._candidates = []
        self._manual_meta = None
        self._selected_idx = 0

        self._hide("done-section")
        self._hide("progress-section")
        self._show("sources-row")
        for section in ("candidates-section", "tracklist-scroll", "tags-row", "target-label", "outputs-row"):
            self._hide(section)

        self.query_one("#meta-table", DataTable).clear(columns=True)
        self._set_tracklist_message("[dim](insert a disc to load metadata)[/dim]")
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-more", Button).disabled = True

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
        toc_path, bin_path, do_image: bool, do_flac: bool, do_mp3: bool,
        do_ogg: bool, args,
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
            f"Disc image: {'yes' if do_image else 'no'}",
            f"FLAC: {'yes' if do_flac else 'no'}",
            f"MP3: {'yes' if do_mp3 else 'no'}",
            f"OGG: {'yes' if do_ogg else 'no'}",
        ]
        if do_image and toc_path:
            lines.append(f"Image TOC: {toc_path}")
            lines.append(f"Image BIN: {bin_path}")
        try:
            info_path.write_text("\n".join(lines) + "\n")
        except OSError:
            pass
