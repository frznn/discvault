# Installation

## Python Package

**Recommended** (isolated install):

```bash
pipx install discvault
```

Standard pip install:

```bash
pip install discvault
```

From source:

```bash
git clone https://github.com/frznn/discvault
cd discvault
pip install -e .
```

## System Dependencies

DiscVault relies on external tools for disc access, audio extraction, and encoding.

### Dependency Check

Before your first rip, verify that required tools are available:

```bash
discvault --check-deps
```

This command reports missing dependencies with distro-specific install hints and exits with code `1` if anything required is missing.

### Core Tools

These are required for basic operation:

| Tool | Purpose |
|------|---------|
| `cdrdao` | Raw disc image creation |
| `cdparanoia` | Audio track extraction |
| `discid` or `cd-discid` | Disc ID calculation for metadata lookup |

Optional core tools:

| Tool | Purpose |
|------|---------|
| `readom` | Alternative image ripper (from `wodim`/`cdrtools`) |
| `cd-info` | Track mode detection (from `libcdio`) |

### Audio Encoders

Enable output formats by installing the corresponding encoder:

| Format | Tool |
|--------|------|
| FLAC | `flac` |
| MP3 | `lame` |
| OGG Vorbis | `oggenc` (from `vorbis-tools`) |
| Opus | `opusenc` (from `opus-tools`) |
| ALAC | `ffmpeg` |
| AAC/M4A | `ffmpeg` |

### Optional Extras

| Tool | Purpose |
|------|---------|
| `eject` | Eject disc after ripping |
| `notify-send` | Desktop notifications |
| `pw-play` / `paplay` / `aplay` / `canberra-gtk-play` | Completion sound |
| `arver` or `trackverify` | AccurateRip verification |

## Distro Install Commands

### Debian / Ubuntu

```bash
sudo apt install cdrdao wodim cdparanoia cd-discid libcdio-utils \
  flac lame vorbis-tools opus-tools ffmpeg eject libnotify-bin
```

For exact MusicBrainz disc IDs (otherwise DiscVault falls back to the TOC from `cd-discid`), install the libdiscid Python binding. For a pipx or virtualenv install, add the extra and the system library; for a system-wide Python, the distro package is enough:

```bash
sudo apt install libdiscid0
pipx install 'discvault[discid]'      # or: pip install 'discvault[discid]'
# system Python instead: sudo apt install python3-libdiscid
```

### Arch Linux

```bash
sudo pacman -S cdrdao cdrtools cdparanoia libdiscid libcdio \
  flac lame vorbis-tools opus-tools ffmpeg eject libnotify
```

### Fedora / RHEL

```bash
sudo dnf install cdrdao cdrtools cdparanoia libdiscid cd-discid libcdio \
  flac lame vorbis-tools opus-tools ffmpeg eject libnotify
```
