# DiscVault

DiscVault is a Linux-first CD archiver with both a Textual TUI and a plain CLI.

It can:

- create a raw disc image with `.bin`, `.toc`, and `.cue`
- optionally derive an `.iso` when the disc contains a supported data track
- rip audio tracks to WAV and encode them to `FLAC`, `MP3`, `OGG`, `Opus`, `ALAC`, `AAC/M4A`, or final `WAV` copies
- fetch metadata from disc-based databases and imports
- download album cover art
- write a `backup-info.txt` manifest into the album folder

The package version in this repo is `0.2.0`.

## Features

- TUI by default when interactive
- Plain CLI mode with `--cli`
- Disc image plus per-format audio outputs
- Track selection, including mixed-mode discs with data tracks excluded by default
- Editable album and track metadata in the TUI
- Metadata lookup from:
  - CD-Text read directly from the disc
  - local CDDB cache (`~/.cddb`)
  - MusicBrainz
  - GnuDB
  - Discogs
  - imported metadata files (`.cue`, `.toc`, `.json`, `.toml`)
  - imported metadata URLs (currently Bandcamp album URLs)
- Optional AccurateRip verification through external helpers
- Optional desktop notification and completion sound

## Platform

DiscVault is currently built around Linux CD device tooling and Linux-style device paths such as `/dev/cdrom` and `/dev/sr0`.

Some helper features have cross-platform fallbacks, but the ripping stack is Linux-oriented.

## Install

Recommended for end users:

```bash
pipx install discvault
```

Standard Python install:

```bash
python -m pip install discvault
```

From a local checkout:

```bash
python -m pip install -e .
```

## Before First Rip

Run the built-in checklist before relying on the app:

```bash
discvault --check-deps
```

That command:

- checks the helper tools required for your current output selection
- reports optional enhancements separately
- prints distro-aware install hints on Debian/Ubuntu, Arch-based, and Fedora/RHEL systems
- exits with `0` when required dependencies are available and `1` when they are not

## System Dependencies

Core ripping and disc detection:

- `cdrdao`
- `readom` from `wodim` / `cdrtools` when you prefer the alternate image ripper
- `cdparanoia`
- one of `discid` or `cd-discid`

Useful metadata helpers:

- `cd-info` for track mode probing

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

### Installing system dependencies

**Debian/Ubuntu:**

```bash
sudo apt install cdrdao wodim cdparanoia discid cd-discid libcdio-utils flac lame vorbis-tools opus-tools ffmpeg eject libnotify-bin
```

**Arch Linux:**

```bash
sudo pacman -S cdrdao cdrtools cdparanoia libdiscid libcdio flac lame vorbis-tools opus-tools ffmpeg eject libnotify
```

**Fedora/RHEL:**

```bash
sudo dnf install cdrdao cdrtools cdparanoia libdiscid cd-discid libcdio flac lame vorbis-tools opus-tools ffmpeg eject libnotify
```

For `discid` / `cd-discid` fallback, install whichever is available for your distribution.

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
discvault --check-deps --no-image --ogg --opus
```

## How Metadata Lookup Works

DiscVault is primarily disc-structure based. It does not do audio fingerprinting.

The app reads disc information from the drive and uses:

- MusicBrainz disc ID / TOC
- FreeDB / GnuDB-style disc ID and offsets
- manual `Artist` / `Album` / `Year` hints for text search and imports

Provider order:

1. Imported metadata file
2. Imported metadata URL
3. CD-Text
4. Local CDDB cache
5. MusicBrainz
6. GnuDB
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
- the target directory path is editable directly in the path field
- tracks are editable and selectable before starting
- `Download Cover Art` is only selectable when the chosen metadata has artwork available
- the app can detect disc removal/ejection and return to a waiting state

### TUI Keyboard Reference

| Key | Action |
| --- | ------ |
| `Enter` / `Start` | Begin ripping when ready |
| `Escape` | Cancel running rip (with confirm) / quit from idle |
| `Ctrl+C` | Force quit |
| `F5` | Re-fetch metadata |
| `Ctrl+,` | Open settings |
| `Ctrl+K` | Command palette |
| `?` | Help screen |

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
- `--check-deps`

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
- `--version`

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
- when `readom` is selected as the image ripper, DiscVault still writes a `.bin` image and synthesizes a `.cue` sidecar

### backup-info.txt

Every successful rip writes a `backup-info.txt` manifest into the album root. Fields:

| Field | Description |
| --- | --- |
| `Backup timestamp` | Rip timestamp (ISO 8601) |
| `DiscVault version` | DiscVault version that produced this rip |
| `Device` | CD device used |
| `Artist` / `Album` / `Year` | Final metadata written for the rip |
| `Metadata source` | Metadata provider name |
| `Disc track count` | Total tracks detected on the disc |
| `Selected tracks` | Audio tracks chosen for extraction |
| `Audio tracks written` | Number of WAV tracks actually ripped |
| `Image BIN` / `Image CUE` / `Image TOC` / `Image ISO` | Paths for the image artifacts actually created |
| `FLAC` / `MP3` / `OGG` / `Opus` / `ALAC` / `AAC/M4A` / `WAV copy` | Enabled output formats |
| `AccurateRip result` | AccurateRip result summary (if enabled) |
| `Cover art` | Saved cover-art path (if downloaded) |

## Configuration

Config file:

- `~/.config/discvault/config.toml`

On first interactive run, DiscVault offers to create the config file and ask for the library directory.

Example:

```toml
[discvault]
base_dir = "/home/user/Music/Library"
work_dir = "~/.cache/discvault/work"
cdrdao_command = "cdrdao read-cd --device {device} --driver generic-mmc-raw -v 1 --read-raw --datafile {datafile} {toc}"
image_ripper = "cdrdao"
keep_wav = false
eject_after = false
metadata_timeout = 8
cdparanoia_sample_offset = 0
default_src_cdtext = true
default_src_musicbrainz = true
default_src_gnudb = false
default_src_discogs = false
use_local_cddb_cache = true
accuraterip_enabled = false
download_cover_art = true
completion_sound = "bell"
progress_style = "spinner"
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

## Real-Drive Smoke Test

For repeatable hardware validation, the repo now includes:

```bash
python tests/manual/real_disc_smoke.py
```

What it does:

- runs a dry-run against the inserted disc
- performs a small subset FLAC rip and verifies `TRACKNUMBER` / `TRACKTOTAL`
- optionally tries an image-only `readom` run
- performs an image-only `cdrdao` run and verifies the image artifacts plus no-eject behavior

Useful options:

```bash
python tests/manual/real_disc_smoke.py --output-root /tmp/discvault-smoke
python tests/manual/real_disc_smoke.py --skip-readom
python tests/manual/real_disc_smoke.py --require-readom-success
python tests/manual/real_disc_smoke.py --device /dev/sr0
```

The script writes only into a temporary output root and uses isolated HOME directories so it does not modify your normal DiscVault config.

## Verification and Cover Art

AccurateRip:

- optional
- disabled by default
- requires `arver` or `trackverify`
- skipped cleanly when no helper is installed

Supported URL imports:

- Bandcamp album URLs

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
