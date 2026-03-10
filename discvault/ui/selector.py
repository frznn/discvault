"""Interactive metadata candidate selector.

Phase 1: simple numbered list prompt in the terminal.
Phase 2: full Textual TUI (imported lazily; requires `pip install discvault[tui]`).
"""
from __future__ import annotations

from ..metadata.types import Metadata
from .console import console


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_candidate(
    candidates: list[Metadata],
    tui: bool = False,
) -> Metadata | None:
    """
    Present the metadata candidates and let the user choose one.

    Returns the selected Metadata, or None if the user skips.
    With tui=True, attempts to launch the Textual TUI; falls back to
    the terminal prompt if textual is not installed.
    """
    if not candidates:
        return None
    if len(candidates) == 1:
        _print_candidate(1, candidates[0])
        return candidates[0]

    if tui:
        try:
            return _tui_select(candidates)
        except ImportError:
            console.print("[warning]textual not installed — falling back to terminal prompt.[/warning]")

    return _terminal_select(candidates)


# ---------------------------------------------------------------------------
# Terminal (Phase 1)
# ---------------------------------------------------------------------------

def _terminal_select(candidates: list[Metadata]) -> Metadata | None:
    console.print("\n[bold]Found metadata candidates:[/bold]")
    for i, m in enumerate(candidates, 1):
        _print_candidate(i, m)
    console.print(f"  [dim]{len(candidates) + 1}. Skip (no metadata)[/dim]")

    while True:
        try:
            raw = console.input(
                f"\n[bold]Select [1–{len(candidates) + 1}][/bold] (default=1): "
            ).strip()
        except (EOFError, KeyboardInterrupt):
            return None

        if raw == "":
            return candidates[0]
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(candidates):
                return candidates[choice - 1]
            if choice == len(candidates) + 1:
                return None
        console.print(f"[warning]Please enter a number between 1 and {len(candidates) + 1}.[/warning]")


def _print_candidate(index: int, meta: Metadata) -> None:
    tracks_str = f"{meta.track_count} track(s)" if meta.tracks else "no tracks"
    year_str = f" ({meta.year})" if meta.year else ""
    console.print(
        f"  [bold cyan]{index}.[/bold cyan] "
        f"[bold]{meta.album_artist or '(unknown artist)'}[/bold] — "
        f"{meta.album or '(untitled)'}{year_str}  "
        f"[dim]{tracks_str} · {meta.source}[/dim]"
    )


# ---------------------------------------------------------------------------
# Textual TUI (Phase 2)
# ---------------------------------------------------------------------------

def _tui_select(candidates: list[Metadata]) -> Metadata | None:
    from textual.app import App, ComposeResult
    from textual.widgets import DataTable, Footer, Header, Label
    from textual.binding import Binding

    result: list[Metadata | None] = [None]

    class SelectorApp(App):
        BINDINGS = [
            Binding("enter", "confirm", "Select"),
            Binding("escape,q", "quit_no_select", "Skip"),
        ]
        CSS = """
        Screen { align: center middle; }
        DataTable { height: 1fr; }
        Label { margin: 1 0; }
        """

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            yield Label("Select metadata — Enter to confirm, Esc to skip")
            yield DataTable()
            yield Footer()

        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.add_columns("Source", "Artist", "Album", "Year", "Tracks")
            for m in candidates:
                table.add_row(
                    m.source,
                    m.album_artist or "(unknown)",
                    m.album or "(untitled)",
                    m.year or "—",
                    str(m.track_count),
                )
            table.focus()

        def action_confirm(self) -> None:
            table = self.query_one(DataTable)
            row_idx = table.cursor_row
            if 0 <= row_idx < len(candidates):
                result[0] = candidates[row_idx]
            self.exit()

        def action_quit_no_select(self) -> None:
            result[0] = None
            self.exit()

    SelectorApp().run()
    return result[0]
