"""Modal extra-file selector for supported data tracks."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, Static

from ..extras import ExtraFileEntry, human_size


class ExtrasSelectScreen(ModalScreen[list[str] | None]):
    CSS = """
    ExtrasSelectScreen {
        align: center middle;
        background: $background 80%;
    }

    #extras-dialog {
        width: 92;
        max-width: 98%;
        height: 85%;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #extras-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #extras-summary {
        margin-bottom: 1;
        color: $text-muted;
        height: auto;
    }

    #extras-note {
        margin-bottom: 1;
        color: $text-muted;
        height: auto;
    }

    #extras-list {
        height: 1fr;
        border: round $surface-lighten-1;
        padding: 0 1;
    }

    .extras-check {
        margin: 0 0 1 0;
    }

    #extras-empty {
        margin: 1 0;
        color: $text-muted;
    }

    #extras-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #extras-select-all,
    #extras-save,
    #extras-cancel {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        entries: list[ExtraFileEntry],
        selected_paths: list[str],
        summary: str,
    ) -> None:
        super().__init__()
        self._entries = list(entries)
        self._selected = set(selected_paths)
        self._summary = summary

    def compose(self) -> ComposeResult:
        checks = [
            Checkbox(
                f"{entry.path}  ({human_size(entry.size)})",
                value=entry.path in self._selected,
                id=f"extra-{index}",
                compact=True,
                classes="extras-check",
            )
            for index, entry in enumerate(self._entries)
        ]
        list_content = checks if checks else [Static("(no extra files were found)", id="extras-empty")]
        yield Vertical(
            Label("Select Extra Files", id="extras-title"),
            Static(self._summary, id="extras-summary"),
            Static("Selected files will be copied into the album's extras/ folder during backup.", id="extras-note"),
            ScrollableContainer(*list_content, id="extras-list"),
            Horizontal(
                Button("Clear", id="extras-clear"),
                Button("Select All", id="extras-select-all"),
                Button("Cancel", id="extras-cancel"),
                Button("Save Selection", id="extras-save", variant="success"),
                id="extras-buttons",
            ),
            id="extras-dialog",
        )

    def on_mount(self) -> None:
        if self._entries:
            self.query_one("#extra-0", Checkbox).focus()
            return
        self.query_one("#extras-save", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "extras-cancel":
            self.dismiss(None)
            return
        if button_id == "extras-clear":
            self._set_all(False)
            return
        if button_id == "extras-select-all":
            self._set_all(True)
            return
        if button_id == "extras-save":
            self.dismiss(self._selected_paths())

    def _set_all(self, value: bool) -> None:
        for index, _entry in enumerate(self._entries):
            self.query_one(f"#extra-{index}", Checkbox).value = value

    def _selected_paths(self) -> list[str]:
        return [
            entry.path
            for index, entry in enumerate(self._entries)
            if self.query_one(f"#extra-{index}", Checkbox).value
        ]
