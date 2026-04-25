"""Modal source selector for metadata providers with editable priority."""
from __future__ import annotations

from collections.abc import Callable

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Label

from ..config import DEFAULT_METADATA_SOURCE_ORDER, METADATA_SOURCE_KEYS


SOURCE_LABELS: dict[str, str] = {
    "cdtext": "CD-Text (from disc)",
    "musicbrainz": "MusicBrainz",
    "gnudb": "GnuDB",
}

SaveCallback = Callable[[dict[str, bool], list[str]], bool]


class SourceSelectScreen(ModalScreen[dict | None]):
    CSS = """
    SourceSelectScreen {
        align: center middle;
        background: $background 80%;
    }

    #source-dialog {
        width: 64;
        max-width: 96%;
        height: auto;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #source-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #source-hint {
        color: $text-muted;
        margin-bottom: 1;
    }

    #source-list {
        height: auto;
    }

    .source-row {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    .source-check {
        width: 1fr;
    }

    .source-move {
        min-width: 5;
        margin-left: 1;
    }

    #source-status {
        height: 1;
        margin-top: 1;
    }

    #source-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #source-save, #source-fetch {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        sources: dict[str, bool],
        order: list[str] | None = None,
        on_save: SaveCallback | None = None,
    ) -> None:
        super().__init__()
        self._sources = {key: bool(sources.get(key, False)) for key in METADATA_SOURCE_KEYS}
        self._order = _normalize_order(order)
        self._on_save = on_save
        self._baseline_sources = dict(self._sources)
        self._baseline_order = list(self._order)
        self._status_timer = None

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Automatic Metadata Sources", id="source-title"),
            Label(
                "Toggle sources and reorder them with ↑ / ↓. Priority runs top to bottom. "
                "Save persists changes; Fetch uses them once without saving.",
                id="source-hint",
            ),
            Vertical(id="source-list"),
            Label("", id="source-status"),
            Horizontal(
                Button("Cancel", id="source-cancel"),
                Button("Save", id="source-save", disabled=True),
                Button("Fetch", id="source-fetch", variant="success"),
                id="source-buttons",
            ),
            id="source-dialog",
        )

    def on_mount(self) -> None:
        self._render_rows()
        self._refresh_save_button()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "source-cancel":
            self.dismiss(None)
            return
        if bid == "source-save":
            self._commit_checkbox_state()
            self._handle_save()
            return
        if bid == "source-fetch":
            self._commit_checkbox_state()
            self.dismiss(
                {
                    "action": "fetch",
                    "sources": dict(self._sources),
                    "order": list(self._order),
                }
            )
            return
        if bid.startswith("src-up-"):
            self._move(bid.removeprefix("src-up-"), -1)
            return
        if bid.startswith("src-down-"):
            self._move(bid.removeprefix("src-down-"), 1)
            return

    @on(Checkbox.Changed, ".source-check")
    def _on_source_checkbox_changed(self, event: Checkbox.Changed) -> None:
        key = (event.checkbox.id or "").removeprefix("src-")
        if key in METADATA_SOURCE_KEYS:
            self._sources[key] = bool(event.value)
            self._refresh_save_button()

    def _handle_save(self) -> None:
        if self._on_save is None:
            self._set_status("Save is unavailable", error=True)
            return
        try:
            saved = bool(self._on_save(dict(self._sources), list(self._order)))
        except Exception as exc:
            self._set_status(f"Save failed: {exc}", error=True)
            return
        if saved:
            self._baseline_sources = dict(self._sources)
            self._baseline_order = list(self._order)
            self._set_status("Saved.", error=False)
        else:
            self._set_status("Save failed.", error=True)
        self._refresh_save_button()

    def _move(self, key: str, delta: int) -> None:
        if key not in self._order:
            return
        self._commit_checkbox_state()
        index = self._order.index(key)
        new_index = index + delta
        if not 0 <= new_index < len(self._order):
            return
        self._order[index], self._order[new_index] = (
            self._order[new_index],
            self._order[index],
        )
        self._render_rows(focus_key=key)
        self._refresh_save_button()

    def _commit_checkbox_state(self) -> None:
        for key in METADATA_SOURCE_KEYS:
            try:
                checkbox = self.query_one(f"#src-{key}", Checkbox)
            except Exception:
                continue
            self._sources[key] = bool(checkbox.value)

    def _render_rows(self, focus_key: str | None = None) -> None:
        container = self.query_one("#source-list", Vertical)
        container.remove_children()
        for position, key in enumerate(self._order):
            label = SOURCE_LABELS.get(key, key)
            checkbox = Checkbox(
                f"{position + 1}. {label}",
                value=self._sources.get(key, False),
                id=f"src-{key}",
                compact=True,
                classes="source-check",
            )
            up_btn = Button(
                "↑",
                id=f"src-up-{key}",
                compact=True,
                classes="source-move",
            )
            down_btn = Button(
                "↓",
                id=f"src-down-{key}",
                compact=True,
                classes="source-move",
            )
            up_btn.disabled = position == 0
            down_btn.disabled = position == len(self._order) - 1
            container.mount(
                Horizontal(
                    checkbox,
                    up_btn,
                    down_btn,
                    classes="source-row",
                )
            )
        target_key = focus_key if focus_key in self._order else self._order[0]
        try:
            self.query_one(f"#src-{target_key}", Checkbox).focus()
        except Exception:
            pass

    def _is_dirty(self) -> bool:
        return (
            self._sources != self._baseline_sources
            or self._order != self._baseline_order
        )

    def _refresh_save_button(self) -> None:
        try:
            btn = self.query_one("#source-save", Button)
        except Exception:
            return
        btn.disabled = not self._is_dirty()

    def _set_status(self, text: str, *, error: bool) -> None:
        try:
            status = self.query_one("#source-status", Label)
        except Exception:
            return
        if text:
            color = "red" if error else "green"
            status.update(f"[{color}]{text}[/{color}]")
        else:
            status.update("")
        if self._status_timer is not None:
            try:
                self._status_timer.stop()
            except Exception:
                pass
            self._status_timer = None
        if text:
            self._status_timer = self.set_timer(
                3.0, lambda: self._set_status("", error=False)
            )


def _normalize_order(order: list[str] | None) -> list[str]:
    if not order:
        return list(DEFAULT_METADATA_SOURCE_ORDER)
    seen: set[str] = set()
    result: list[str] = []
    for item in order:
        key = item.strip().lower() if isinstance(item, str) else ""
        if key in METADATA_SOURCE_KEYS and key not in seen:
            result.append(key)
            seen.add(key)
    for key in DEFAULT_METADATA_SOURCE_ORDER:
        if key not in seen:
            result.append(key)
    return result
