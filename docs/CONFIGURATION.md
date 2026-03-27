# Configuration

Config file location:

```
~/.config/discvault/config.toml
```

On first interactive run, DiscVault offers to create this file and set your library directory.

## Example Config

```toml
[discvault]
# Output directories
base_dir = "/home/user/Music/Library"
work_dir = "~/.cache/discvault/work"

# Image ripper: "cdrdao" or "readom"
image_ripper = "cdrdao"
cdrdao_command = "cdrdao read-cd --device {device} --driver generic-mmc-raw -v 1 --read-raw --datafile {datafile} {toc}"

# Post-rip behavior
keep_wav = false
eject_after = false

# Metadata lookup
metadata_timeout = 8
default_src_cdtext = true
default_src_musicbrainz = true
default_src_gnudb = false
default_src_discogs = false
use_local_cddb_cache = true

# Audio extraction
cdparanoia_sample_offset = 0

# Verification and artwork
accuraterip_enabled = false
download_cover_art = true

# UI
completion_sound = "bell"
progress_style = "spinner"

# Encoder defaults
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

## Settings Reference

### Output Directories

| Setting | Description |
|---------|-------------|
| `base_dir` | Library root where album folders are created |
| `work_dir` | Temporary directory for intermediate files |

### Image Ripper

| Setting | Description |
|---------|-------------|
| `image_ripper` | `"cdrdao"` (default) or `"readom"` |
| `cdrdao_command` | Custom cdrdao command template |

### Post-Rip Behavior

| Setting | Description |
|---------|-------------|
| `keep_wav` | Keep intermediate WAV files after encoding |
| `eject_after` | Eject disc when rip completes |

### Metadata Sources

| Setting | Description |
|---------|-------------|
| `metadata_timeout` | Timeout in seconds for metadata requests |
| `default_src_cdtext` | Try CD-Text from disc |
| `default_src_musicbrainz` | Query MusicBrainz |
| `default_src_gnudb` | Query GnuDB (requires `[gnudb]` config) |
| `default_src_discogs` | Query Discogs (requires `[discogs]` config) |
| `use_local_cddb_cache` | Check `~/.cddb` before online lookup |

### Audio Extraction

| Setting | Description |
|---------|-------------|
| `cdparanoia_sample_offset` | Sample offset correction for your drive |

### Verification & Artwork

| Setting | Description |
|---------|-------------|
| `accuraterip_enabled` | Run AccurateRip verification |
| `download_cover_art` | Fetch cover art when available |

### UI

| Setting | Description |
|---------|-------------|
| `completion_sound` | `"bell"`, `"none"`, or path to audio file |
| `progress_style` | `"spinner"` or `"bar"` |

### Encoder Defaults

| Setting | Description |
|---------|-------------|
| `opus_bitrate` | Opus bitrate in kbps (default: 160) |
| `aac_bitrate` | AAC bitrate in kbps (default: 256) |

### GnuDB

| Setting | Description |
|---------|-------------|
| `host` | GnuDB server hostname (empty = disabled) |
| `port` | CDDBP port (default: 8880) |
| `hello_user` | Username for CDDB hello |
| `hello_program` | Program name for CDDB hello |
| `hello_version` | Version for CDDB hello |

### Discogs

| Setting | Description |
|---------|-------------|
| `token` | Discogs API token (optional but recommended) |

A Discogs token improves reliability and avoids rate limits. Get one at [discogs.com/settings/developers](https://www.discogs.com/settings/developers).
