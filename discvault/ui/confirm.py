"""Confirmation and error modal dialogs."""
from __future__ import annotations

import shutil
import subprocess

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TextArea


def _copy_to_clipboard(text: str) -> bool:
    """Try to copy text to clipboard using available system tools. Returns True on success.

    stdout and stderr from the helper tool are suppressed; otherwise tools like
    `wl-copy` (when no Wayland session is reachable) print diagnostics that
    would leak into the TUI screen as "weird warning text".
    """

    def _run(cmd: list[str]) -> bool:
        try:
            subprocess.run(
                cmd,
                input=text,
                text=True,
                check=True,
                timeout=3,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            return False

    # Wayland
    if shutil.which("wl-copy") and _run(["wl-copy"]):
        return True
    # X11
    for tool in ("xclip", "xsel"):
        if shutil.which(tool):
            args = (
                [tool, "-selection", "clipboard", "-i"]
                if tool == "xclip"
                else [tool, "--clipboard", "--input"]
            )
            if _run(args):
                return True
    # macOS
    if shutil.which("pbcopy") and _run(["pbcopy"]):
        return True
    return False


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


class ErrorScreen(ModalScreen[str | None]):
    BINDINGS = [("ctrl+shift+c", "copy_message", "Copy")]

    CSS = """
    ErrorScreen {
        align: center middle;
        background: $background 80%;
    }

    #error-dialog {
        width: 84;
        max-width: 96%;
        height: auto;
        border: round $error;
        background: $panel;
        padding: 1;
    }

    #error-title {
        margin: 0 0 1 0;
        text-style: bold;
        color: $error;
    }

    #error-message {
        margin-bottom: 1;
        height: auto;
        max-height: 6;
        border: none;
        background: transparent;
        color: $text-muted;
    }

    #error-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #error-retry {
        margin-left: 1;
    }

    #error-dismiss {
        margin-left: 1;
    }

    #error-copy {
        margin-left: 1;
    }
    """

    def __init__(self, message: str, retry_label: str = "") -> None:
        super().__init__()
        self._message = message
        self._retry_label = retry_label

    def compose(self) -> ComposeResult:
        buttons: list = [
            Button("Copy", id="error-copy"),
            Button("Dismiss", id="error-dismiss"),
        ]
        if self._retry_label:
            buttons.append(Button(self._retry_label, id="error-retry", variant="warning"))
        yield Vertical(
            Label("Rip failed", id="error-title"),
            TextArea(self._message, id="error-message", read_only=True),
            Horizontal(*buttons, id="error-buttons"),
            id="error-dialog",
        )

    def on_mount(self) -> None:
        if self._retry_label:
            self.query_one("#error-retry", Button).focus()
        else:
            self.query_one("#error-dismiss", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "error-copy":
            if _copy_to_clipboard(self._message):
                self.notify("Copied to clipboard")
            else:
                self.notify("Clipboard unavailable (install wl-copy or xclip)", severity="warning")
            return
        if event.button.id == "error-dismiss":
            self.dismiss(None)
        elif event.button.id == "error-retry":
            self.dismiss("retry")

    def action_copy_message(self) -> None:
        if _copy_to_clipboard(self._message):
            self.notify("Copied to clipboard")
        else:
            self.notify("Clipboard unavailable (install wl-copy or xclip)", severity="warning")
