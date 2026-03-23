# DiscVault

DiscVault is a Linux-first CD archiver with both a Textual TUI and a plain CLI.

It can:

- create a raw disc image with `.bin`, `.toc`, and `.cue`
- optionally derive an `.iso` when the disc contains a supported data track
- rip audio tracks to WAV and encode them to `FLAC`, `MP3`, `OGG`, `Opus`, `ALAC`, `AAC/M4A`, or final `WAV` copies
- fetch metadata from disc-based databases and imports
- download album cover art
- write a `backup-info.txt` manifest into the album folder

The package version in this repo is `0.1.0`.

## Features

- TUI by default when interactive and `textual` is installed
- Plain CLI mode with `--cli`
- Disc image plus per-format audio outputs
- Track selection, including mixed-mode discs with data tracks excluded by default
- Editable album and track metadata in the TUI
- Metadata lookup from:
  - local CDDB cache (`~/.cddb`)
  - MusicBrainz
  - GnuDB
  - CD-Text
  - Discogs
  - imported metadata files (`.cue`, `.toc`, `.json`, `.toml`)
  - imported metadata URLs (currently Bandcamp album URLs)
- Optional AccurateRip verification through external helpers
- Optional desktop notification and completion sound

## Platform

DiscVault is currently built around Linux CD device tooling and Linux-style device paths such as `/dev/cdrom` and `/dev/sr0`.

Some helper features have cross-platform fallbacks, but the ripping stack is Linux-oriented.

## Python Install

```bash
python -m pip install -e ".[tui]"
```

Without the TUI dependency:

```bash
python -m pip install -e .
```

## System Dependencies

Core ripping and disc detection:

- `cdrdao`
- `cdparanoia`
- one of `discid` or `cd-discid`

Useful metadata helpers:

- `cd-info` for track mode / CD-Text probing

Optional encoders:

- `flac`
- `lame`
- `oggenc`
- `opusenc`
- `ffmpeg` for `ALAC` and `AAC/M4A`

Optional extras:

- `eject`
- `notify-send` for desktop notifications
- `pw-play`, `paplay`, `aplay`, or `canberra-gtk-play` for completion sounds
- `arver` or `trackverify` for AccurateRip verification

## Quick Start

Interactive TUI:

```bash
discvault
```

Force CLI mode:

```bash
discvault --cli
```

Common examples:

```bash
discvault --cli --device /dev/cdrom
discvault --cli --tracks 1-8
discvault --cli --no-image --ogg --opus
discvault --cli --metadata-file album.cue
discvault --cli --metadata-url https://artist.bandcamp.com/album/example
discvault --cli --artist "Artist" --album "Album" --year 1997
discvault --cli --accuraterip
```

## How Metadata Lookup Works

DiscVault is primarily disc-structure based. It does not do audio fingerprinting.

The app reads disc information from the drive and uses:

- MusicBrainz disc ID / TOC
- FreeDB / GnuDB-style disc ID and offsets
- CD-Text when present
- manual `Artist` / `Album` / `Year` hints for text search and imports

Provider order:

1. Imported metadata file
2. Imported metadata URL
3. Local CDDB cache
4. MusicBrainz
5. GnuDB
6. CD-Text
7. Discogs

Notes:

- Discogs token is optional but recommended for reliability and rate limits.
- Local CDDB cache lookup is controlled by config and checks `~/.cddb` first when enabled.
- GnuDB CDDBP is disabled by default unless a host is configured.

## TUI Workflow

When `textual` is installed and the session is interactive, DiscVault launches the TUI by default.

Main behaviors:

- `Search Metadata` opens a source picker and then performs lookup
- `Import from File` imports `.cue`, `.toc`, `.json`, or `.toml`
- `Import from URL` imports from supported sites, currently Bandcamp album URLs
- `Select Outputs` controls which image and audio formats will be produced
- tracks are editable and selectable before starting
- `Download Cover Art` is only selectable when the chosen metadata has artwork available
- the app can detect disc removal/ejection and return to a waiting state

## CLI Options

Main options:

- `--device DEV`
- `--base-dir DIR`
- `--work-dir DIR`
- `--tracks SPEC`
- `--metadata-file FILE`
- `--metadata-url URL`
- `--artist NAME`
- `--album NAME`
- `--year YYYY`
- `--skip-metadata`
- `--strict-manual-fallback`
- `--metadata-timeout SEC`
- `--metadata-debug`
- `--cli`

Audio outputs:

- `--no-flac`
- `--no-mp3`
- `--ogg`
- `--opus`
- `--alac`
- `--aac`
- `--wav`
- `--no-verify`
- `--flac-compression N`
- `--mp3-quality N`
- `--mp3-bitrate KBPS`
- `--opus-bitrate KBPS`
- `--aac-bitrate KBPS`

Disc image and verification:

- `--no-image`
- `--iso`
- `--cdrdao-driver DRV`
- `--sample-offset SAMPLES`
- `--accuraterip`
- `--no-accuraterip`
- `--no-cover-art`

Misc:

- `--keep-wav`
- `--eject`
- `--dry-run`
- `--debug`

## Outputs and Library Layout

Album folders are written under:

- default library root: `~/Music/Library`
- configurable via `~/.config/discvault/config.toml`

Typical output layout:

```text
Artist/
  1997. Album/
    backup-info.txt
    cover.jpg
    image/
      Artist-Album-1997.bin
      Artist-Album-1997.toc
      Artist-Album-1997.cue
      Artist-Album-1997.iso
    flac/
      01 - Track.flac
    mp3/
      01 - Track.mp3
    ogg/
      01 - Track.ogg
    opus/
      01 - Track.opus
    alac/
      01 - Track.m4a
    m4a/
      01 - Track.m4a
    wav/
      01 - Track.wav
```

Notes:

- `.iso` is only produced when the disc contains a supported data track layout
- raw disc image output is the archival format; `.cue` is written alongside `.toc` for wider compatibility

## Configuration

Config file:

- `~/.config/discvault/config.toml`

On first interactive run, DiscVault offers to create the config file and ask for the library directory.

Example:

```toml
[discvault]
base_dir = "/home/user/Music/Library"
work_dir = "/tmp/discvault"
cdrdao_driver = "generic-mmc-raw"
keep_wav = false
eject_after = false
metadata_timeout = 8
cdparanoia_sample_offset = 0
preferred_metadata_source = "musicbrainz"
use_local_cddb_cache = true
accuraterip_enabled = false
download_cover_art = true
completion_sound = "bell"
opus_bitrate = 160
aac_bitrate = 256

[gnudb]
host = ""
port = 8880
hello_user = ""
hello_program = "discvault"
hello_version = "1.0"

[discogs]
token = ""
```

## Metadata Import Formats

Supported file imports:

- `.cue`
- `.toc`
- `.json`
- `.toml`

Minimal JSON example:

```json
{
  "metadata": {
    "album_artist": "Artist",
    "album": "Album",
    "year": "1997",
    "cover_art_url": "https://example.com/cover.jpg",
    "tracks": [
      {"number": 1, "title": "Track One", "artist": "Artist"}
    ]
  }
}
```

Supported URL imports:

- Bandcamp album URLs

## Verification and Cover Art

AccurateRip:

- optional
- disabled by default
- requires `arver` or `trackverify`
- skipped cleanly when no helper is installed

Cover art:

- downloaded from provider URLs or the Cover Art Archive when metadata includes the needed IDs
- saved as `cover.jpg`, `cover.png`, or similar under the album root

## Testing

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

## Current Limitations

- No audio fingerprinting; identification depends on disc structure, database coverage, imports, and manual hints.
- The ripping stack is Linux-first.
- ISO export is conservative and only works for supported data-track layouts.
- TUI cover-art preview is not implemented yet.

## Development Notes

- Entry point: [discvault/cli.py](discvault/cli.py)
- TUI app: [discvault/ui/tui.py](discvault/ui/tui.py)
- Tests: `tests/`
