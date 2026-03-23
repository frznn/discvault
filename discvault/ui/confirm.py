"""Simple yes/no confirmation modal."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static


class ConfirmScreen(ModalScreen[bool | None]):
    CSS = """
    ConfirmScreen {
        align: center middle;
        background: $background 80%;
    }

    #confirm-dialog {
        width: 84;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #confirm-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #confirm-message {
        margin-bottom: 1;
        color: $text-muted;
        height: auto;
    }

    #confirm-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #confirm-submit {
        margin-left: 1;
    }
    """

    def __init__(self, *, title: str, message: str, confirm_label: str) -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self._title, id="confirm-title"),
            Static(self._message, id="confirm-message"),
            Horizontal(
                Button("Cancel", id="confirm-cancel"),
                Button(self._confirm_label, id="confirm-submit", variant="error"),
                id="confirm-buttons",
            ),
            id="confirm-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm-cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-cancel":
            self.dismiss(None)
            return
        if event.button.id == "confirm-submit":
            self.dismiss(True)
