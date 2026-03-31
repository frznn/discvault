# Changelog

All notable changes to this project will be documented in this file.

The project history starts at `v0.1`.

## [Unreleased]

### Added
- `--check-deps` CLI checklist with distro-aware install hints for DiscVault helper tools.
- MIT licensing, generated man page, and generated shell completions for `bash`, `zsh`, and `fish`.
- GitHub Actions CI and tag-driven publish workflows for package builds and PyPI releases.
- Manual Search and Import popups in the TUI for free-form metadata lookup and unified file/URL imports.

### Changed
- The default Python package install now includes the Textual TUI instead of requiring a separate extra.
- Packaging metadata now targets PyPI and `pipx` as the primary release path for Linux installs.
- TUI metadata actions now use a popup-driven flow for manual searching and importing instead of separate inline/file/url controls.

### Fixed
- Manual metadata searches now use looser MusicBrainz and Discogs queries so partial titles, punctuation differences, and missing years return candidates more reliably.

## [0.2] - 2026-03-26

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
- Manual real-disc smoke test script for future hardware verification.

### Changed
- Reworked the TUI layout and workflow around metadata search, imports, output selection, target handling, and progress reporting.
- Improved drive monitoring so the TUI reacts to disc insertion, removal, and eject events more cleanly and with less drive churn.
- Moved local CDDB cache behavior behind configuration instead of exposing it as a normal source toggle.
- Made the CLI and TUI follow the same rip/encode/cover-art/cleanup flow through the shared pipeline.
- Made configuration handling safer, including atomic saves and better normalization of invalid values.
- Improved disc image handling with stricter success validation and better progress reporting.
- Standardized the `0.2` release path around a green automated test suite plus real-drive smoke coverage.

### Fixed
- Metadata re-fetch in the TUI now uses the current source selection instead of stale defaults.
- Fixed a TUI busy-state bug that made `Fetch Metadata` appear to do nothing.
- Fixed CD-Text probing to use valid tooling and more defensible fallbacks.
- Fixed CLI behavior for image-only runs so audio extraction is skipped when no audio outputs are selected.
- Fixed unsupported metadata URLs so they are warned about and ignored instead of crashing the CLI.
- Fixed stale target-label state when album/artist fields are cleared.
- Fixed overwrite-risk handling by adding TUI confirmation before writing into an existing populated target directory.
- Fixed completion alert handling so backend failures are detected instead of silently treated as success.
- Fixed selected-track audio tagging so ripped subsets keep correct track totals.
- Fixed `backup-info.txt` generation so it reflects the files actually created, including image-only runs.
- Fixed rip and encode validation so empty or missing outputs are treated as failures instead of succeeding silently.
- Fixed `readom` and `cdrdao` error handling so failures surface with clearer diagnostics and safer cleanup.

## [0.1] - 2026-03-16

### Added
- Initial DiscVault TUI ripping workflow.
- Disc detection, metadata lookup, candidate selection, and rip orchestration for the first release.
- Core image and audio backup flow with the initial Textual interface.
