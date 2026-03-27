# CLI Reference

Force CLI mode (skip TUI):

```bash
discvault --cli
```

## Options

### General

| Option | Description |
|--------|-------------|
| `--device DEV` | CD device path (default: `/dev/cdrom`) |
| `--base-dir DIR` | Library root for album folders |
| `--work-dir DIR` | Temporary work directory |
| `--cli` | Use CLI mode instead of TUI |
| `--check-deps` | Check system dependencies and exit |
| `--dry-run` | Show what would happen without writing files |
| `--debug` | Verbose logging |
| `--version` | Print version and exit |

### Track Selection

| Option | Description |
|--------|-------------|
| `--tracks SPEC` | Track range (e.g., `1-8`, `1,3,5`, `2-`) |

### Metadata

| Option | Description |
|--------|-------------|
| `--metadata-file FILE` | Import metadata from `.cue`, `.toc`, `.json`, or `.toml` |
| `--metadata-url URL` | Import metadata from URL (e.g., Bandcamp album) |
| `--artist NAME` | Override artist name |
| `--album NAME` | Override album name |
| `--year YYYY` | Override release year |
| `--skip-metadata` | Skip all metadata lookup |
| `--strict-manual-fallback` | Require exact match for manual hints |
| `--metadata-timeout SEC` | Timeout for metadata requests |
| `--metadata-debug` | Debug metadata lookup |

### Audio Outputs

| Option | Description |
|--------|-------------|
| `--no-flac` | Disable FLAC output |
| `--no-mp3` | Disable MP3 output |
| `--ogg` | Enable OGG Vorbis output |
| `--opus` | Enable Opus output |
| `--alac` | Enable ALAC output |
| `--aac` | Enable AAC/M4A output |
| `--wav` | Keep final WAV copies |
| `--keep-wav` | Keep intermediate WAV files |
| `--no-verify` | Skip FLAC verification |

### Encoder Settings

| Option | Description |
|--------|-------------|
| `--flac-compression N` | FLAC compression level (0-8) |
| `--mp3-quality N` | MP3 VBR quality (0-9, lower is better) |
| `--mp3-bitrate KBPS` | MP3 CBR bitrate |
| `--opus-bitrate KBPS` | Opus bitrate (default: 160) |
| `--aac-bitrate KBPS` | AAC bitrate (default: 256) |

### Disc Image

| Option | Description |
|--------|-------------|
| `--no-image` | Skip disc image creation |
| `--iso` | Also create ISO when possible |
| `--cdrdao-driver DRV` | cdrdao driver override |
| `--sample-offset SAMPLES` | cdparanoia sample offset correction |

### Verification & Extras

| Option | Description |
|--------|-------------|
| `--accuraterip` | Enable AccurateRip verification |
| `--no-accuraterip` | Disable AccurateRip verification |
| `--no-cover-art` | Skip cover art download |
| `--eject` | Eject disc when done |

## Examples

```bash
# Basic rip with default settings
discvault --cli

# Specify device and tracks
discvault --cli --device /dev/sr0 --tracks 1-8

# Audio only (no disc image), with Opus and OGG
discvault --cli --no-image --ogg --opus

# Import metadata from cue sheet
discvault --cli --metadata-file album.cue

# Import from Bandcamp
discvault --cli --metadata-url https://artist.bandcamp.com/album/title

# Manual metadata
discvault --cli --artist "Artist" --album "Album" --year 1997

# Check dependencies for specific output config
discvault --check-deps --no-image --ogg --opus
```

## Output Layout

Albums are saved under your library root (default: `~/Music/Library`):

```
Artist/
  1997. Album/
    backup-info.txt
    cover.jpg
    image/
      Artist-Album-1997.bin
      Artist-Album-1997.toc
      Artist-Album-1997.cue
      Artist-Album-1997.iso      # if data track present
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
- `.iso` is only created when the disc has a supported data track layout
- `.cue` is written alongside `.toc` for compatibility with more tools
- When using `readom` as the image ripper, a `.cue` sidecar is synthesized

## backup-info.txt

Every successful rip writes a manifest with:

| Field | Description |
|-------|-------------|
| `Backup timestamp` | ISO 8601 timestamp |
| `DiscVault version` | Version used |
| `Device` | CD device path |
| `Artist` / `Album` / `Year` | Final metadata |
| `Metadata source` | Provider name |
| `Disc track count` | Total tracks on disc |
| `Selected tracks` | Tracks chosen for rip |
| `Audio tracks written` | Tracks actually extracted |
| `Image BIN/CUE/TOC/ISO` | Image artifact paths |
| `FLAC/MP3/OGG/...` | Enabled output formats |
| `AccurateRip result` | Verification result (if enabled) |
| `Cover art` | Cover art path (if downloaded) |
