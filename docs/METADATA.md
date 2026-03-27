# Metadata

DiscVault identifies discs by their physical structure (TOC), not audio fingerprinting. This works well for discs that exist in online databases, and you can always provide metadata manually via imports or CLI flags.

## Lookup Order

When you search for metadata, DiscVault queries sources in this order:

1. **Imported file** - `.cue`, `.toc`, `.json`, or `.toml` via `--metadata-file`
2. **Imported URL** - Bandcamp album URL via `--metadata-url`
3. **CD-Text** - Metadata embedded on the disc itself
4. **Local CDDB cache** - `~/.cddb` directory
5. **MusicBrainz** - Via disc ID and TOC
6. **GnuDB** - Via CDDBP (disabled by default)
7. **Discogs** - Via search with artist/album hints

The first source that returns a match is used. You can enable/disable sources in your config file or the TUI settings.

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

Currently supported:

- **Bandcamp album URLs** - e.g., `https://artist.bandcamp.com/album/title`

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
