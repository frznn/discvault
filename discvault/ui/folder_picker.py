"""Folder browser modal for picking a destination directory."""
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label, ListItem, ListView


class FolderPickerScreen(ModalScreen[tuple[Path, bool] | None]):
    """Browse the filesystem and select a folder.

    Dismisses with ``(path, is_base)`` where *is_base* is ``True`` when the user
    wants an album subfolder created inside the selected folder, or ``False`` when
    the selected folder should be used as the exact destination.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    CSS = """
    FolderPickerScreen {
        align: center middle;
        background: $background 80%;
    }

    #fp-dialog {
        width: 84;
        max-width: 96%;
        height: 30;
        max-height: 85%;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #fp-title {
        text-style: bold;
        margin-bottom: 1;
    }

    #fp-path {
        color: $text-muted;
        height: 1;
        margin-bottom: 1;
        overflow: hidden;
    }

    #fp-list {
        height: 1fr;
        border: round $surface;
    }

    #fp-is-base {
        height: auto;
        margin-top: 1;
    }

    #fp-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #fp-select {
        margin-left: 1;
    }
    """

    def __init__(self, start_path: Path | None = None) -> None:
        super().__init__()
        if start_path is None:
            start_path = Path.home()
        if start_path.is_dir():
            self._current = start_path
        elif start_path.parent.is_dir():
            self._current = start_path.parent
        else:
            self._current = Path.home()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Select destination folder", id="fp-title"),
            Label("", id="fp-path"),
            ListView(id="fp-list"),
            Checkbox(
                "Create album subfolder inside this folder  (Artist / Year. Album)",
                id="fp-is-base",
                value=True,
            ),
            Horizontal(
                Button("Cancel", id="fp-cancel"),
                Button("Select", id="fp-select", variant="primary"),
                id="fp-buttons",
            ),
            id="fp-dialog",
        )

    def on_mount(self) -> None:
        self._refresh_list()

    def _refresh_list(self) -> None:
        self.query_one("#fp-path", Label).update(str(self._current))
        lv = self.query_one("#fp-list", ListView)
        lv.clear()

        if self._current.parent != self._current:
            lv.append(ListItem(Label(".. (go up)"), name=".."))

        try:
            subdirs = sorted(
                [p for p in self._current.iterdir() if p.is_dir() and not p.name.startswith(".")],
                key=lambda p: p.name.lower(),
            )
        except PermissionError:
            subdirs = []

        for d in subdirs:
            lv.append(ListItem(Label(d.name), name=d.name))

        lv.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name == "..":
            self._current = self._current.parent
        else:
            self._current = self._current / name
        self._refresh_list()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "fp-cancel":
            self.dismiss(None)
        elif event.button.id == "fp-select":
            is_base = self.query_one("#fp-is-base", Checkbox).value
            self.dismiss((self._current, bool(is_base)))

    def action_cancel(self) -> None:
        self.dismiss(None)
