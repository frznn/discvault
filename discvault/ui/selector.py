"""Interactive metadata candidate selector."""
from __future__ import annotations

import sys

from ..metadata.types import Metadata
from .console import console, log


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_candidate(
    candidates: list[Metadata],
    disc_info=None,
    tui: bool = False,
) -> Metadata | None:
    """
    Present the metadata candidates and let the user choose one.

    Returns the selected Metadata, or None if the user wants manual entry.
    With tui=True, attempts to launch the Textual TUI; falls back to
    the terminal prompt if textual is not installed.
    """
    if not candidates:
        return None

    if tui:
        try:
            return _tui_select(candidates)
        except ImportError:
            console.print("[warning]textual not installed — falling back to terminal prompt.[/warning]")

    return _terminal_select(candidates, disc_info)


# ---------------------------------------------------------------------------
# Terminal — one-candidate-at-a-time with navigation
# ---------------------------------------------------------------------------

def _terminal_select(candidates: list[Metadata], disc_info=None) -> Metadata | None:
    count = len(candidates)
    idx = 0

    while True:
        _print_candidate_preview(idx, count, candidates[idx], disc_info)

        if count > 1:
            prompt = f"\nUse this? [Y=use, n=next, p=prev, l=list, m=manual, q=quit, 1-{count}=select]: "
        else:
            prompt = "\nUse this? [Y=use, m=manual, q=quit]: "

        try:
            answer = console.input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            return None

        if answer in ("", "y", "yes"):
            return candidates[idx]
        elif answer in ("n", "next"):
            if count > 1:
                idx = (idx + 1) % count
            else:
                log("Only one metadata option available.")
        elif answer in ("p", "prev"):
            if count > 1:
                idx = (idx - 1 + count) % count
            else:
                log("Only one metadata option available.")
        elif answer == "l":
            if count > 1:
                _print_candidate_list(candidates)
                try:
                    pick = console.input(
                        f"Choose [1-{count}] or Enter to keep current: "
                    ).strip()
                except (EOFError, KeyboardInterrupt):
                    pass
                else:
                    if pick.isdigit() and 1 <= int(pick) <= count:
                        idx = int(pick) - 1
            else:
                log("Only one metadata option available.")
        elif answer in ("m", "manual"):
            return None
        elif answer in ("q", "quit"):
            console.print("Aborted.")
            sys.exit(0)
        elif answer.isdigit() and 1 <= int(answer) <= count:
            idx = int(answer) - 1
        else:
            console.print(f"[warning]Invalid choice: {answer}[/warning]")


def _print_candidate_preview(
    idx: int, total: int, meta: Metadata, disc_info=None
) -> None:
    track_lengths: dict[int, int] = disc_info.track_lengths if disc_info else {}
    year_str = f" ({meta.year})" if meta.year else ""
    console.print(
        f"\n[bold]Metadata option {idx + 1}/{total}[/bold]  "
        f"[dim][{meta.source}][/dim]"
    )
    console.print(f"Artist: [bold]{meta.album_artist or '(unknown artist)'}[/bold]")
    console.print(f"Album:  [bold]{meta.album or '(untitled)'}[/bold]{year_str}")

    if meta.tracks:
        console.print("Tracklist:")
        for t in meta.tracks:
            secs = track_lengths.get(t.number, 0)
            length_str = f"{secs // 60}:{secs % 60:02d}" if secs else ""
            length_part = f" [{length_str}]" if length_str else ""
            if t.artist and t.artist != meta.album_artist:
                console.print(
                    f"  [dim]{t.number:02d}.[/dim] {t.title} "
                    f"[dim]({t.artist}){length_part}[/dim]"
                )
            else:
                console.print(
                    f"  [dim]{t.number:02d}.[/dim] {t.title}"
                    f"[dim]{length_part}[/dim]"
                )
    else:
        console.print("  [dim](track titles not available)[/dim]")


def _print_candidate_list(candidates: list[Metadata]) -> None:
    console.print("\n[bold]Available metadata options:[/bold]")
    for i, m in enumerate(candidates, 1):
        year_part = f" ({m.year})" if m.year else ""
        tracks_str = f"{m.track_count} tracks" if m.tracks else "no tracks"
        console.print(
            f"  [bold cyan]{i:2d}.[/bold cyan] "
            f"[dim][{m.source}][/dim] "
            f"[bold]{m.album_artist or '(unknown)'}[/bold] — "
            f"{m.album or '(untitled)'}{year_part}  "
            f"[dim]{tracks_str}[/dim]"
        )


# ---------------------------------------------------------------------------
# Textual TUI
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
