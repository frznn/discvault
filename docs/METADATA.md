# Metadata

DiscVault identifies discs by their physical structure (TOC), not audio fingerprinting. This works well for discs that exist in online databases, and you can always provide metadata manually via imports, Manual Search in the TUI, or CLI tag overrides.

## Metadata Paths

DiscVault has three distinct metadata paths:

1. **Imports** - Explicit metadata from a file or supported URL.
2. **Automatic disc lookup** - Enabled automatic sources that identify the inserted disc.
3. **Manual Search** - Explicit text search in the TUI.

DiscVault collects candidates from the providers it runs and deduplicates them. In the TUI you can choose among the candidates; in non-interactive CLI runs, the first candidate is auto-selected.

## Automatic Disc Lookup

Automatic disc lookup is what runs on disc insert, on `F5`, and when you use the TUI `Sources…` dialog.

The automatic lookup runs in this order:

1. **Local CDDB cache** - `~/.cddb` directory (always checked first as a free short-circuit when enabled)
2. **CD-Text** - Metadata embedded on the disc itself
3. **MusicBrainz** - Via disc ID or TOC fallback
4. **GnuDB** - Via FreeDB/CDDB disc ID

CD-Text, MusicBrainz, and GnuDB are user-editable. Their on/off state and priority can be changed in the TUI `Sources…` dialog: reorder rows with `↑`/`↓` and toggle checkboxes. The dialog has three actions:

- **Save** — persists both the enabled flags (`default_src_*`) and the priority (`metadata_source_order`) to `config.toml`. No fetch is triggered.
- **Fetch** — runs one lookup using the current dialog state without saving anything. The dialog's changes do not stick: next time you open `Sources…` the saved config is restored, and F5 / re-detects continue to use the saved config.
- **Cancel** — discards changes.

The Local CDDB cache is not reorderable — it stays anchored before the online providers.

By default, automatic lookup **stops as soon as one source returns a result** (including the local cache). This matches the way the priority list is normally used: the first source you trust most fires first, returns metadata, and the rest of the providers are skipped. Set `lookup_stop_at_first_match = false` in the config file to fall back to the old behavior of querying every enabled source and merging all candidates.

Only these automatic sources appear in the config defaults and the TUI source picker.

## Manual Search

Manual Search is separate from automatic lookup.

- **MusicBrainz search** - Text search by artist, album, year, or free-form terms
- **Discogs** - Text search seeded from your explicit search terms and any MusicBrainz search matches

Discogs is manual-search-only. It is not part of normal automatic metadata lookup and does not appear in the automatic source list.

If you leave the Manual Search prompt empty, DiscVault falls back to the current Artist/Album/Year fields as the search text.

## Imports

Imports are explicit user actions rather than automatic metadata sources:

1. **Imported file** - `.cue`, `.toc`, `.json`, or `.toml` via `--metadata-file` or the TUI Import dialog
2. **Imported URL** - Supported page URLs via `--metadata-url` or the TUI Import dialog

Currently supported URL imports:

- **Bandcamp album URLs** - e.g., `https://artist.bandcamp.com/album/title`

Bandcamp is an import source, not part of automatic lookup or Manual Search.

## Disc Identification

DiscVault calculates two types of disc ID:

- **MusicBrainz disc ID** - Based on track count, TOC offsets, and lead-out
- **FreeDB/CDDB disc ID** - Based on track offsets and total length

These IDs are used to query online databases. The same physical disc always produces the same IDs.

## Import Formats

### Cue Sheets (.cue)

Standard cue sheet format. DiscVault extracts artist, album, and track titles:

```
PERFORMER "Artist Name"
TITLE "Album Title"
FILE "image.bin" BINARY
  TRACK 01 AUDIO
    TITLE "Track One"
    PERFORMER "Artist Name"
    INDEX 01 00:00:00
```

### TOC Files (.toc)

cdrdao TOC format with CD-TEXT blocks:

```
CD_DA
CD_TEXT {
  LANGUAGE 0 {
    TITLE "Album Title"
    PERFORMER "Artist Name"
  }
}
TRACK AUDIO
CD_TEXT {
  LANGUAGE 0 {
    TITLE "Track One"
  }
}
```

### JSON

```json
{
  "metadata": {
    "album_artist": "Artist Name",
    "album": "Album Title",
    "year": "1997",
    "cover_art_url": "https://example.com/cover.jpg",
    "tracks": [
      {"number": 1, "title": "Track One", "artist": "Artist Name"},
      {"number": 2, "title": "Track Two", "artist": "Artist Name"}
    ]
  }
}
```

### TOML

```toml
[metadata]
album_artist = "Artist Name"
album = "Album Title"
year = "1997"
cover_art_url = "https://example.com/cover.jpg"

[[metadata.tracks]]
number = 1
title = "Track One"
artist = "Artist Name"

[[metadata.tracks]]
number = 2
title = "Track Two"
artist = "Artist Name"
```

## URL Import

Bandcamp import fetches album artist, title, track listing, and cover art URL.

```bash
discvault --cli --metadata-url https://artist.bandcamp.com/album/example
```

## Cover Art

Cover art is downloaded automatically when:

- Metadata includes a cover art URL (imports, Bandcamp)
- MusicBrainz release has artwork in the Cover Art Archive
- Discogs release has images

The image is saved as `cover.jpg` (or `.png`) in the album folder.

Disable with `--no-cover-art` or `download_cover_art = false` in config.

## AccurateRip

AccurateRip verifies your rip against checksums submitted by other users. This confirms your drive read the disc correctly.

Requirements:
- `arver` or `trackverify` installed
- Disc must exist in the AccurateRip database

Enable with `--accuraterip` or `accuraterip_enabled = true` in config.

Results are logged and written to `backup-info.txt`. If verification fails or the disc isn't in the database, the rip still completes normally.
