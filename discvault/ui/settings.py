"""Persistent settings screen for the TUI."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select

from ..config import Config


class ConfigScreen(ModalScreen[Config | None]):
    CSS = """
    ConfigScreen {
        align: center middle;
        background: $background 80%;
    }

    #config-dialog {
        width: 90;
        max-width: 96%;
        height: 90%;
        max-height: 36;
        border: round $surface;
        background: $panel;
        padding: 1;
    }

    #config-title {
        margin: 0 0 1 0;
        text-style: bold;
    }

    #config-scroll {
        height: 1fr;
        overflow-y: auto;
        padding-right: 1;
    }

    .cfg-row {
        height: auto;
        align: left middle;
        margin-bottom: 1;
    }

    .cfg-label {
        width: 20;
        padding-right: 1;
        color: $text-muted;
    }

    .cfg-input {
        width: 1fr;
    }

    .cfg-check {
        margin-right: 2;
    }

    #config-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #cfg-save {
        margin-left: 1;
    }
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg.clone()

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Settings", id="config-title"),
            ScrollableContainer(
                *self._rows(),
                id="config-scroll",
            ),
            Horizontal(
                Button("Cancel", id="cfg-cancel"),
                Button("Save", id="cfg-save", variant="success"),
                id="config-buttons",
            ),
            id="config-dialog",
        )

    def _rows(self) -> list:
        return [
            self._input_row("Library", "cfg-base-dir", self._cfg.base_dir),
            self._input_row("Work dir", "cfg-work-dir", self._cfg.work_dir),
            self._input_row("cdrdao driver", "cfg-cdrdao-driver", self._cfg.cdrdao_driver),
            self._input_row("Metadata timeout", "cfg-timeout", str(self._cfg.metadata_timeout)),
            self._input_row(
                "Sample offset",
                "cfg-sample-offset",
                str(self._cfg.cdparanoia_sample_offset),
            ),
            self._select_row(
                "Default source",
                "cfg-preferred-source",
                [
                    ("MusicBrainz", "musicbrainz"),
                    ("GnuDB", "gnudb"),
                    ("CD-Text", "cdtext"),
                    ("Discogs", "discogs"),
                ],
                self._cfg.preferred_metadata_source,
            ),
            self._check_row(
                ("Use local CDDB cache", "cfg-cache", self._cfg.use_local_cddb_cache),
                ("Enable AccurateRip", "cfg-accuraterip", self._cfg.accuraterip_enabled),
            ),
            self._check_row(
                ("Keep WAV files", "cfg-keep-wav", self._cfg.keep_wav),
                ("Eject when done", "cfg-eject", self._cfg.eject_after),
            ),
            self._check_row(
                ("Download cover art", "cfg-cover-art", self._cfg.download_cover_art),
            ),
            self._select_row(
                "Completion sound",
                "cfg-completion-sound",
                [
                    ("Bell", "bell"),
                    ("Chime", "chime"),
                    ("Bell + chime", "both"),
                    ("Off", "off"),
                ],
                self._cfg.completion_sound,
            ),
            self._input_row("Opus bitrate", "cfg-opus-bitrate", str(self._cfg.opus_bitrate)),
            self._input_row("AAC bitrate", "cfg-aac-bitrate", str(self._cfg.aac_bitrate)),
            self._input_row("GnuDB host", "cfg-gnudb-host", self._cfg.gnudb.host),
            self._input_row("GnuDB port", "cfg-gnudb-port", str(self._cfg.gnudb.port)),
            self._input_row("GnuDB user", "cfg-hello-user", self._cfg.gnudb.hello_user),
            self._input_row("GnuDB program", "cfg-hello-program", self._cfg.gnudb.hello_program),
            self._input_row("GnuDB version", "cfg-hello-version", self._cfg.gnudb.hello_version),
            self._input_row(
                "Discogs token (improves reliability/rate limits)",
                "cfg-discogs-token",
                self._cfg.discogs.token,
            ),
        ]

    def _input_row(self, label: str, widget_id: str, value: str) -> Horizontal:
        return Horizontal(
            Label(label, classes="cfg-label"),
            Input(value=value, id=widget_id, classes="cfg-input", compact=True),
            classes="cfg-row",
        )

    def _check_row(self, *checks: tuple[str, str, bool]) -> Horizontal:
        widgets = [Checkbox(label, value=value, id=widget_id, compact=True, classes="cfg-check")
                   for label, widget_id, value in checks]
        return Horizontal(*widgets, classes="cfg-row")

    def _select_row(
        self,
        label: str,
        widget_id: str,
        options: list[tuple[str, str]],
        value: str,
    ) -> Horizontal:
        return Horizontal(
            Label(label, classes="cfg-label"),
            Select(options, value=value, id=widget_id, compact=True),
            classes="cfg-row",
        )

    def on_mount(self) -> None:
        self.query_one("#cfg-base-dir", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cfg-cancel":
            self.dismiss(None)
            return
        if event.button.id != "cfg-save":
            return

        try:
            updated = self._build_config()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(updated)

    def _build_config(self) -> Config:
        cfg = self._cfg.clone()
        cfg.base_dir = self._input("cfg-base-dir")
        cfg.work_dir = self._input("cfg-work-dir")
        cfg.cdrdao_driver = self._input("cfg-cdrdao-driver")
        cfg.metadata_timeout = max(1, self._int_input("cfg-timeout", "Metadata timeout"))
        cfg.cdparanoia_sample_offset = self._int_input("cfg-sample-offset", "Sample offset")
        cfg.use_local_cddb_cache = self._check("cfg-cache")
        cfg.accuraterip_enabled = self._check("cfg-accuraterip")
        cfg.keep_wav = self._check("cfg-keep-wav")
        cfg.eject_after = self._check("cfg-eject")
        cfg.download_cover_art = self._check("cfg-cover-art")
        completion_sound = self.query_one("#cfg-completion-sound", Select).value
        if completion_sound in {"bell", "chime", "both", "off"}:
            cfg.completion_sound = completion_sound
        cfg.opus_bitrate = max(32, self._int_input("cfg-opus-bitrate", "Opus bitrate"))
        cfg.aac_bitrate = max(96, self._int_input("cfg-aac-bitrate", "AAC bitrate"))
        cfg.gnudb.host = self._input("cfg-gnudb-host")
        cfg.gnudb.port = max(1, self._int_input("cfg-gnudb-port", "GnuDB port"))
        cfg.gnudb.hello_user = self._input("cfg-hello-user")
        cfg.gnudb.hello_program = self._input("cfg-hello-program")
        cfg.gnudb.hello_version = self._input("cfg-hello-version")
        cfg.discogs.token = self._input("cfg-discogs-token")

        preferred = self.query_one("#cfg-preferred-source", Select).value
        if preferred in {"musicbrainz", "gnudb", "cdtext", "discogs"}:
            cfg.preferred_metadata_source = preferred
        return cfg

    def _input(self, widget_id: str) -> str:
        return self.query_one(f"#{widget_id}", Input).value.strip()

    def _int_input(self, widget_id: str, label: str) -> int:
        raw = self._input(widget_id)
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc

    def _check(self, widget_id: str) -> bool:
        return self.query_one(f"#{widget_id}", Checkbox).value
