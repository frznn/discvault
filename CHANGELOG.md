# Changelog

All notable changes to this project will be documented in this file.

The project history starts at `v0.1`.

## [Unreleased]

### Added
- Shared backup pipeline used by both the CLI and the TUI.
- Metadata import from local files and URL-based imports, including Bandcamp URL import.
- Additional metadata sources and lookup improvements, including Discogs support and clearer source selection flows.
- Optional cover-art download with source detection and run-time selection in the TUI.
- Additional output formats: Opus, ALAC, AAC/M4A, WAV copies, ISO export, and automatic CUE sidecars for raw disc images.
- Optional AccurateRip verification.
- Dedicated settings, confirmation, source-selection, and output-selection dialogs in the TUI.
- Track editing and per-track selection in the TUI, including safer handling of mixed-mode discs and data tracks.
- Desktop notifications and configurable completion sounds.
- Project README.

### Changed
- Reworked the TUI layout and workflow around metadata search, imports, output selection, target handling, and progress reporting.
- Improved drive monitoring so the TUI reacts to disc insertion, removal, and eject events more cleanly and with less drive churn.
- Moved local CDDB cache behavior behind configuration instead of exposing it as a normal source toggle.
- Made the CLI and TUI follow the same rip/encode/cover-art/cleanup flow through the shared pipeline.
- Made configuration handling safer, including atomic saves and better normalization of invalid values.
- Improved disc image handling with stricter success validation and better progress reporting.

### Fixed
- Metadata re-fetch in the TUI now uses the current source selection instead of stale defaults.
- Fixed a TUI busy-state bug that made `Fetch Metadata` appear to do nothing.
- Fixed CD-Text probing to use valid tooling and more defensible fallbacks.
- Fixed CLI behavior for image-only runs so audio extraction is skipped when no audio outputs are selected.
- Fixed unsupported metadata URLs so they are warned about and ignored instead of crashing the CLI.
- Fixed stale target-label state when album/artist fields are cleared.
- Fixed overwrite-risk handling by adding TUI confirmation before writing into an existing populated target directory.
- Fixed completion alert handling so backend failures are detected instead of silently treated as success.

## [0.1] - 2026-03-16

### Added
- Initial DiscVault TUI ripping workflow.
- Disc detection, metadata lookup, candidate selection, and rip orchestration for the first release.
- Core image and audio backup flow with the initial Textual interface.
