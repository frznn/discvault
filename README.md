# DiscVault

A Linux-first CD archiver with a Textual TUI and plain CLI.

DiscVault creates archival-quality disc backups with raw images, multiple audio formats, and automatic metadata lookup.

## What It Does

- Creates raw disc images (`.bin`, `.toc`, `.cue`) with optional `.iso` for data tracks
- Rips audio to FLAC, MP3, OGG, Opus, ALAC, AAC, or WAV
- Fetches metadata from CD-Text, MusicBrainz, GnuDB, Discogs, and local CDDB
- Imports metadata from cue sheets, TOC files, JSON/TOML, or Bandcamp URLs
- Downloads cover art automatically
- Supports AccurateRip verification

## Install

```bash
pipx install discvault
```

Then check your system has the required tools:

```bash
discvault --check-deps
```

See [docs/INSTALL.md](docs/INSTALL.md) for system dependencies and distro-specific install commands.

## Quick Start

Launch the TUI (default when interactive):

```bash
discvault
```

Use CLI mode:

```bash
discvault --cli
discvault --cli --device /dev/sr0 --tracks 1-8
discvault --cli --no-image --opus --ogg
discvault --cli --metadata-url https://artist.bandcamp.com/album/title
```

## TUI Workflow

The TUI lets you:

- Search metadata from multiple sources
- Import from files or URLs
- Edit album and track info before ripping
- Select which tracks to include
- Choose output formats
- Download cover art

### Keyboard

| Key | Action |
| --- | ------ |
| `Enter` | Start ripping |
| `Escape` | Cancel / quit |
| `F5` | Re-fetch metadata |
| `Ctrl+,` | Settings |
| `Ctrl+K` | Command palette |
| `?` | Help |

## Platform

DiscVault is built around Linux CD tooling (`/dev/cdrom`, `/dev/sr0`). Some helpers have cross-platform fallbacks, but the core ripping stack requires Linux.

## Limitations

- No audio fingerprinting; relies on disc structure and database coverage
- ISO export only works for supported data-track layouts
- TUI cover-art preview not yet implemented

## Documentation

- [Installation & Dependencies](docs/INSTALL.md)
- [CLI Reference](docs/CLI.md)
- [Configuration](docs/CONFIGURATION.md)
- [Metadata & Cover Art](docs/METADATA.md)
- [Testing & Development](tests/README.md)

## Version

Current version: `0.3.0`
