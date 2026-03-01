# ⚙️ Configuration Guide - tiddl

**For complete placeholder reference, see [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md) ⭐**

Configuration file location and all available options.

---

## 📍 Configuration File Location

**Windows:**
```
C:\Users\YourName\.tiddl\config.toml
```

**Linux/macOS:**
```
~/.tiddl/config.toml
```

---

## 🚀 Quick Start Config

```toml
enable_cache = true
debug = false

[download]
track_quality = "max"
video_quality = "fhd"
skip_existing = true
threads_count = 4
download_path = "~/Music/tiddl"

[metadata]
enable = true
lyrics = true
save_lyrics = true
cover = true

[templates]
default = "{album.artist}/{album.title}/{item.number}. {item.title}"
```

---

## 📝 General Settings

### `enable_cache`
- **Type**: boolean
- **Default**: true
- **Description**: Enable API response caching

### `debug`
- **Type**: boolean
- **Default**: false
- **Description**: Enable verbose logging to `~/.tiddl/api_debug/`

---

## 🎵 [download] Section

### `track_quality`
- **Type**: low / normal / high / max
- **Default**: high
- Options:
  - `max`: 24-bit, 192kHz FLAC (best)
  - `high`: 16-bit, 44.1kHz FLAC
  - `normal`: 320kbps AAC
  - `low`: 96kbps AAC (worst)

### `video_quality`
- **Type**: sd / hd / fhd
- **Default**: fhd
- Options:
  - `fhd`: 1080p (best)
  - `hd`: 720p
  - `sd`: 360p (worst)

### `skip_existing`
- **Type**: boolean
- **Default**: true
- Skip files already downloaded

### `threads_count`
- **Type**: integer
- **Default**: 4
- **Range**: 1-20
- Number of concurrent downloads

### `download_path`
- **Type**: path
- **Default**: ~/Music/tiddl
- Base directory for downloads

### `scan_path`
- **Type**: path
- **Default**: same as download_path
- Directory to scan for existing files

### `singles_filter`
- **Type**: none / only / include
- **Default**: none
- How to handle artist singles

### `videos_filter`
- **Type**: none / only / allow
- **Default**: none
- How to handle music videos

---

## 📝 [metadata] Section

### `enable`
- **Type**: boolean
- **Default**: true
- Master switch for all metadata processing

### `lyrics`
- **Type**: boolean
- **Default**: false
- Embed lyrics in file metadata

### `save_lyrics`
- **Type**: boolean
- **Default**: false
- Save lyrics as separate `.lrc` file

### `cover`
- **Type**: boolean
- **Default**: false
- Embed album cover in file metadata

### `album_review`
- **Type**: boolean
- **Default**: false
- Embed album review in metadata

---

## 🖼️ [cover] Section

### `save`
- **Type**: boolean
- **Default**: false
- Save cover as separate image file

### `size`
- **Type**: integer
- **Default**: 1280
- **Range**: 1-1280
- Cover image width in pixels

### `allowed`
- **Type**: array
- **Default**: []
- Resource types: track, album, playlist

---

## 📂 [templates] Section

Controls file naming and organization.

### `default`
- **Type**: string
- **Default**: "{album.artist}/{album.title}/{item.title}"
- Default template for all content

### `track`
- **Type**: string
- Specific template for tracks

### `album`
- **Type**: string
- Specific template for albums

### `playlist`
- **Type**: string
- Specific template for playlists

### `video`
- **Type**: string
- Specific template for videos

---

## 📝 Template Variables

**For complete placeholder reference, see [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)**

Common variables:

```bash
{item.title}              # Track title
{item.number}             # Track number (01, 02, etc)
{item.version}            # Track version (Remix, etc)
{item.artist}             # Track artist
{item.artists_with_features}  # With featuring artists
{item.releaseDate:%Y}     # Year

{album.artist}            # Album artist
{album.title}             # Album name
{album.date:%Y}           # Release year

{artist_initials}         # First letter (groups by letter)
{playlist.title}          # Playlist name
```

---

## 💡 Common Templates

### Simple (Default)
```toml
default = "{album.artist}/{album.title}/{item.title}"
```

### With Track Numbers
```toml
default = "{album.artist}/{album.title}/{item.number}. {item.title}"
```

### By Year
```toml
default = "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"
```

### Grouped by Initial
```toml
default = "{artist_initials}/{album.artist}/{album.title}/{item.title}"
```

### With Featuring Artists
```toml
default = "{album.artist}/{album.title}/{item.number}. {item.artists_with_features}"
```

---

## 🎬 [m3u] Section

M3U8 playlist export settings.

### `save`
- **Type**: boolean
- **Default**: false
- Save M3U8 files

### `allowed`
- **Type**: array
- **Default**: []
- Resource types: album, playlist, mix

---

## 📋 Full Example Config

```toml
enable_cache = true
debug = false

[download]
track_quality = "max"
video_quality = "fhd"
skip_existing = true
threads_count = 4
download_path = "~/Music/tiddl"
scan_path = "~/Music/tiddl"
singles_filter = "include"
videos_filter = "allow"
update_mtime = false
rewrite_metadata = true

[metadata]
enable = true
lyrics = true
save_lyrics = true
cover = true
album_review = false

[cover]
save = true
size = 1280
allowed = ["track", "album", "playlist"]

[templates]
track = ""
video = ""
album = ""
playlist = ""
default = "{album.artist}/{album.title}/{item.number}. {item.title}"

[m3u]
save = false
allowed = ["album", "playlist"]
```

---

## 🔄 Command-Line Overrides

Command-line arguments override config.toml:

```bash
# Override quality
tiddl download url --track-quality high https://...

# Override download path
tiddl download url --path "D:/Music" https://...

# Override threads
tiddl download url --threads-count 8 https://...
```

---

## 🛠️ Troubleshooting

### Config Not Loading
```bash
# Check location
cat ~/.tiddl/config.toml

# Validate TOML syntax
```

### Metadata Not Embedding
```toml
[metadata]
enable = true  # Must be true
```

### Wrong Quality
```bash
# Check config
grep track_quality ~/.tiddl/config.toml

# Override with flag
tiddl download url --track-quality max https://...
```

---

## 📚 More Information

- **[COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)** - Complete placeholders and variables
- **[USAGE.md](USAGE.md)** - Usage examples
- **[README.md](README.md)** - Overview

---

**For complete placeholder reference, see [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)**
