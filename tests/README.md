# Testing

## Unit Tests

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

Or with pytest:

```bash
pytest tests/ -v
```

## Real-Disc Smoke Test

For hardware validation with an actual CD, use the manual smoke test:

```bash
python tests/manual/real_disc_smoke.py
```

This script:

1. Runs a dry-run against the inserted disc
2. Rips a small subset of tracks to FLAC and verifies metadata tags
3. Optionally tests `readom` image ripping
4. Tests `cdrdao` image ripping and verifies artifacts

The script uses isolated directories and won't modify your normal DiscVault config.

### Options

```bash
# Custom output directory
python tests/manual/real_disc_smoke.py --output-root /tmp/discvault-smoke

# Skip readom test
python tests/manual/real_disc_smoke.py --skip-readom

# Fail if readom doesn't work
python tests/manual/real_disc_smoke.py --require-readom-success

# Use specific device
python tests/manual/real_disc_smoke.py --device /dev/sr0
```

## Project Structure

```
tests/
  manual/
    real_disc_smoke.py    # Hardware integration test
  test_alerts.py          # Notification tests
  test_artwork.py         # Cover art download tests
  test_bandcamp.py        # Bandcamp import tests
  test_cleanup.py         # Temp file cleanup tests
  test_cli.py             # CLI argument parsing tests
  test_config.py          # Config loading tests
  test_deps.py            # Dependency checking tests
  test_device.py          # CD device detection tests
  test_encode.py          # Audio encoding tests
  test_fileimport.py      # Metadata file import tests
  test_musicbrainz.py     # MusicBrainz lookup tests
  test_rip.py             # Ripping pipeline tests
  test_tracks.py          # Track selection tests
  test_tui.py             # TUI component tests
  test_urlimport.py       # URL import tests
```

## Development

Entry points:

- CLI: [discvault/cli.py](../discvault/cli.py)
- TUI: [discvault/ui/tui.py](../discvault/ui/tui.py)

The CLI module handles argument parsing and dispatches to either the TUI app or the headless ripping pipeline.
