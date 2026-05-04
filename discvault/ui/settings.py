"""Persistent settings screen for the TUI."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from textual import on

from ..config import Config, DEFAULT_CDRDAO_COMMAND, DriveProfile
from .. import device as dev_mod


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

    .cfg-section-label {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 0;
        text-style: italic;
    }

    .cfg-section-header {
        color: $accent;
        margin-top: 2;
        margin-bottom: 1;
        text-style: bold;
    }

#config-buttons {
        height: auto;
        align: right middle;
        margin-top: 1;
    }

    #cfg-save {
        margin-left: 1;
    }

    #cfg-cdrdao-reset {
        margin-left: 1;
        min-width: 9;
    }
    """

    _AUTO_DEVICE_VALUE = "<auto>"

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg.clone()
        # Tracks which drive the rip-config rows currently edit. "<auto>" means
        # the rows edit the global Config fallbacks; a /dev/... path means the rows
        # edit that drive's profile.
        self._active_drive_key: str = (
            self._cfg.device if self._cfg.device else self._AUTO_DEVICE_VALUE
        )

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
            Static("Paths", classes="cfg-section-header"),
            self._input_row("Library", "cfg-base-dir", self._cfg.base_dir),
            self._input_row("Work dir", "cfg-work-dir", self._cfg.work_dir),

            Static("Rip behavior", classes="cfg-section-header"),
            self._device_row(),
            Static(
                "Selecting a specific device edits that drive's profile;"
                " Auto-detect edits the global defaults used for unconfigured drives.",
                classes="cfg-section-label",
            ),
            self._select_row(
                "Image ripper",
                "cfg-image-ripper",
                [("cdrdao", "cdrdao"), ("readom", "readom")],
                self._initial_rip_image_ripper(),
            ),
            Static(
                "cdrdao command — only used when cdrdao is selected above. "
                "Try removing --read-raw if cdrdao crashes (exit -11), "
                "or change the driver (e.g. generic-mmc, audio).",
                classes="cfg-section-label",
            ),
            Horizontal(
                Label("cdrdao command", classes="cfg-label"),
                Input(
                    value=self._initial_rip_cdrdao_command(),
                    id="cfg-cdrdao-command",
                    classes="cfg-input",
                    compact=True,
                ),
                Button("Reset", id="cfg-cdrdao-reset", compact=True),
                classes="cfg-row",
            ),
            self._input_row(
                "Sample offset",
                "cfg-sample-offset",
                str(self._initial_rip_sample_offset()),
            ),
            self._check_row(
                ("Enable AccurateRip", "cfg-accuraterip", self._cfg.accuraterip_enabled),
                ("Eject when done", "cfg-eject", self._cfg.eject_after),
            ),

            Static("Output", classes="cfg-section-header"),
            self._check_row(
                ("Keep WAV files", "cfg-keep-wav", self._cfg.keep_wav),
                ("Download cover art", "cfg-cover-art", self._cfg.download_cover_art),
            ),
            self._input_row("Opus bitrate", "cfg-opus-bitrate", str(self._cfg.opus_bitrate)),
            self._input_row("AAC bitrate", "cfg-aac-bitrate", str(self._cfg.aac_bitrate)),

            Static("Metadata sources", classes="cfg-section-header"),
            Static("Enable by default:", classes="cfg-section-label"),
            self._check_row(
                ("CD-Text", "cfg-src-cdtext", self._cfg.default_src_cdtext),
                ("MusicBrainz", "cfg-src-mb", self._cfg.default_src_musicbrainz),
                ("GnuDB", "cfg-src-gnudb", self._cfg.default_src_gnudb),
            ),
            self._input_row("Metadata timeout", "cfg-timeout", str(self._cfg.metadata_timeout)),
            self._check_row(
                ("Use local CDDB cache", "cfg-cache", self._cfg.use_local_cddb_cache),
            ),
            self._input_row("GnuDB user", "cfg-hello-user", self._cfg.gnudb.hello_user),
            self._input_row("GnuDB program", "cfg-hello-program", self._cfg.gnudb.hello_program),
            self._input_row("GnuDB version", "cfg-hello-version", self._cfg.gnudb.hello_version),
            self._input_row(
                "Discogs token (manual search only)",
                "cfg-discogs-token",
                self._cfg.discogs.token,
            ),

            Static("Lookup behavior", classes="cfg-section-header"),
            self._check_row(
                (
                    "Stop at first match",
                    "cfg-stop-first-match",
                    self._cfg.lookup_stop_at_first_match,
                ),
                (
                    "Blank redundant track artists",
                    "cfg-blank-redundant-artists",
                    self._cfg.blank_redundant_track_artist,
                ),
            ),
            self._check_row(
                (
                    "Dedupe equivalent candidates",
                    "cfg-dedupe-equivalent",
                    self._cfg.dedupe_equivalent_candidates,
                ),
                (
                    "Prefer release year",
                    "cfg-prefer-release-year",
                    self._cfg.prefer_release_year,
                ),
            ),

            Static("Logging", classes="cfg-section-header"),
            self._check_row(
                (
                    "Log lookup durations",
                    "cfg-log-timings",
                    self._cfg.lookup_log_timings,
                ),
                (
                    "Write logs to file",
                    "cfg-log-to-file",
                    self._cfg.log_to_file,
                ),
            ),

            Static("Notifications & display", classes="cfg-section-header"),
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
            self._select_row(
                "Progress animation",
                "cfg-progress-style",
                [
                    ("Spinner  ⠋⠙⠹", "spinner"),
                    ("Loading indicator", "loading"),
                    ("Pulse", "pulse"),
                    ("Color accent", "color"),
                    ("None", "none"),
                ],
                self._cfg.progress_style,
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

    def _device_options(self) -> list[tuple[str, str]]:
        """Auto-detect + every present drive + saved cfg.device + every drive with a saved profile."""
        present = dev_mod.list_available()
        # Always include the saved device + every drive with a saved profile so
        # they remain editable even when the hardware isn't currently plugged in.
        if self._cfg.device and self._cfg.device not in present:
            present.append(self._cfg.device)
        for path in sorted(self._cfg.drives):
            if path not in present:
                present.append(path)
        options: list[tuple[str, str]] = [("Auto-detect", self._AUTO_DEVICE_VALUE)]
        options.extend((path, path) for path in present)
        return options

    def _device_row(self) -> Horizontal:
        return Horizontal(
            Label("Device", classes="cfg-label"),
            Select(
                self._device_options(),
                value=self._active_drive_key,
                id="cfg-device",
                compact=True,
                allow_blank=False,
            ),
            classes="cfg-row",
        )

    def _initial_rip_sample_offset(self) -> int:
        if self._active_drive_key == self._AUTO_DEVICE_VALUE:
            return self._cfg.cdparanoia_sample_offset
        profile = self._cfg.drives.get(self._active_drive_key)
        if profile is not None and profile.sample_offset is not None:
            return profile.sample_offset
        return self._cfg.cdparanoia_sample_offset

    def _initial_rip_image_ripper(self) -> str:
        if self._active_drive_key == self._AUTO_DEVICE_VALUE:
            return self._cfg.image_ripper
        profile = self._cfg.drives.get(self._active_drive_key)
        if profile is not None and profile.image_ripper:
            return profile.image_ripper
        return self._cfg.image_ripper

    def _initial_rip_cdrdao_command(self) -> str:
        if self._active_drive_key == self._AUTO_DEVICE_VALUE:
            return self._cfg.cdrdao_command
        profile = self._cfg.drives.get(self._active_drive_key)
        if profile is not None and profile.cdrdao_command:
            return profile.cdrdao_command
        return self._cfg.cdrdao_command

    def on_mount(self) -> None:
        self.query_one("#cfg-base-dir", Input).focus()

    @on(Select.Changed, "#cfg-device")
    def _on_device_select(self, event: Select.Changed) -> None:
        new_key = str(event.value)
        if not new_key or new_key == self._active_drive_key:
            return
        try:
            self._stash_active_rip_rows()
        except ValueError:
            # Defer offset validation to Save; let the user keep typing.
            pass
        self._active_drive_key = new_key
        self._load_active_rip_rows(new_key)

    def _stash_active_rip_rows(self) -> None:
        """Persist the rip-config rows to either global cfg or the active drive's profile.

        Auto-detect → writes to the global Config fields.
        Specific drive → writes a DriveProfile that only overrides fields differing
        from global; if everything matches global, drops any existing profile.
        """
        try:
            offset_input = self.query_one("#cfg-sample-offset", Input)
            ripper_select = self.query_one("#cfg-image-ripper", Select)
            command_input = self.query_one("#cfg-cdrdao-command", Input)
        except Exception:
            return

        raw_offset = offset_input.value.strip()
        try:
            sample_offset = int(raw_offset) if raw_offset else 0
        except ValueError as exc:
            raise ValueError("Sample offset must be an integer.") from exc

        ripper_val = ripper_select.value
        image_ripper = ripper_val if ripper_val in {"cdrdao", "readom"} else self._cfg.image_ripper
        cdrdao_command = command_input.value.strip()

        if self._active_drive_key == self._AUTO_DEVICE_VALUE:
            self._cfg.cdparanoia_sample_offset = sample_offset
            self._cfg.image_ripper = image_ripper
            self._cfg.cdrdao_command = cdrdao_command
            return

        profile = DriveProfile(
            sample_offset=sample_offset
            if sample_offset != self._cfg.cdparanoia_sample_offset
            else None,
            image_ripper=image_ripper if image_ripper != self._cfg.image_ripper else "",
            cdrdao_command=cdrdao_command if cdrdao_command != self._cfg.cdrdao_command else "",
        )
        if profile.sample_offset is None and not profile.image_ripper and not profile.cdrdao_command:
            self._cfg.drives.pop(self._active_drive_key, None)
        else:
            self._cfg.drives[self._active_drive_key] = profile

    def _load_active_rip_rows(self, key: str) -> None:
        """Load the rip-config rows from the effective values for ``key``."""
        if key == self._AUTO_DEVICE_VALUE:
            sample_offset = self._cfg.cdparanoia_sample_offset
            image_ripper = self._cfg.image_ripper
            cdrdao_command = self._cfg.cdrdao_command
        else:
            profile = self._cfg.drives.get(key, DriveProfile())
            sample_offset = (
                profile.sample_offset
                if profile.sample_offset is not None
                else self._cfg.cdparanoia_sample_offset
            )
            image_ripper = profile.image_ripper or self._cfg.image_ripper
            cdrdao_command = profile.cdrdao_command or self._cfg.cdrdao_command
        self.query_one("#cfg-sample-offset", Input).value = str(sample_offset)
        self.query_one("#cfg-image-ripper", Select).value = image_ripper
        self.query_one("#cfg-cdrdao-command", Input).value = cdrdao_command

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cfg-cdrdao-reset":
            self.query_one("#cfg-cdrdao-command", Input).value = DEFAULT_CDRDAO_COMMAND
            return
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
        # Stash the active rip-config rows into self._cfg (global or drive profile)
        # before cloning so the saved cfg reflects the latest UI state.
        self._stash_active_rip_rows()
        cfg = self._cfg.clone()
        # Strip empty profiles so the saved TOML stays clean.
        cfg.drives = {
            k: v for k, v in cfg.drives.items()
            if v.sample_offset is not None or v.image_ripper or v.cdrdao_command
        }
        cfg.base_dir = self._input("cfg-base-dir")
        cfg.work_dir = self._input("cfg-work-dir")
        device_val = self.query_one("#cfg-device", Select).value
        cfg.device = "" if device_val == self._AUTO_DEVICE_VALUE else str(device_val)
        cfg.metadata_timeout = max(1, self._int_input("cfg-timeout", "Metadata timeout"))
        cfg.use_local_cddb_cache = self._check("cfg-cache")
        cfg.accuraterip_enabled = self._check("cfg-accuraterip")
        cfg.keep_wav = self._check("cfg-keep-wav")
        cfg.eject_after = self._check("cfg-eject")
        cfg.download_cover_art = self._check("cfg-cover-art")
        cfg.default_src_cdtext = self._check("cfg-src-cdtext")
        cfg.default_src_musicbrainz = self._check("cfg-src-mb")
        cfg.default_src_gnudb = self._check("cfg-src-gnudb")
        cfg.lookup_stop_at_first_match = self._check("cfg-stop-first-match")
        cfg.lookup_log_timings = self._check("cfg-log-timings")
        cfg.log_to_file = self._check("cfg-log-to-file")
        cfg.blank_redundant_track_artist = self._check("cfg-blank-redundant-artists")
        cfg.dedupe_equivalent_candidates = self._check("cfg-dedupe-equivalent")
        cfg.prefer_release_year = self._check("cfg-prefer-release-year")
        completion_sound = self.query_one("#cfg-completion-sound", Select).value
        if completion_sound in {"bell", "chime", "both", "off"}:
            cfg.completion_sound = completion_sound
        progress_style_val = self.query_one("#cfg-progress-style", Select).value
        if progress_style_val in {"none", "spinner", "loading", "pulse", "color"}:
            cfg.progress_style = progress_style_val
        cfg.opus_bitrate = max(32, self._int_input("cfg-opus-bitrate", "Opus bitrate"))
        cfg.aac_bitrate = max(96, self._int_input("cfg-aac-bitrate", "AAC bitrate"))
        cfg.gnudb.hello_user = self._input("cfg-hello-user")
        cfg.gnudb.hello_program = self._input("cfg-hello-program")
        cfg.gnudb.hello_version = self._input("cfg-hello-version")
        cfg.discogs.token = self._input("cfg-discogs-token")
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
