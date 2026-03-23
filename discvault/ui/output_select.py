"""Modal output selector for rip targets."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label


class OutputSelectScreen(ModalScreen[dict[str, bool] | None]):
    CSS = """
    OutputSelectScreen {
        align: center middle;
        background: $background 80%;
    }

    #output-dialog {
        width: 64;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #output-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #output-list {
        height: auto;
    }

    .output-check {
        margin-bottom: 1;
    }

    #output-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #output-save {
        margin-left: 1;
    }
    """

    def __init__(self, options: list[tuple[str, str, bool]]) -> None:
        super().__init__()
        self._options = list(options)

    def compose(self) -> ComposeResult:
        checks = [
            Checkbox(label, value=value, id=f"out-{key}", compact=True, classes="output-check")
            for key, label, value in self._options
        ]
        yield Vertical(
            Label("Select Outputs", id="output-title"),
            Vertical(*checks, id="output-list"),
            Horizontal(
                Button("Cancel", id="output-cancel"),
                Button("Save", id="output-save", variant="success"),
                id="output-buttons",
            ),
            id="output-dialog",
        )

    def on_mount(self) -> None:
        self.query_one("#out-image", Checkbox).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "output-cancel":
            self.dismiss(None)
            return
        if event.button.id == "output-save":
            self.dismiss(self._selected_outputs())

    def _selected_outputs(self) -> dict[str, bool]:
        return {
            key: self.query_one(f"#out-{key}", Checkbox).value
            for key, _label, _value in self._options
        }
