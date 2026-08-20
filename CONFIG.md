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
requests_per_minute = 50
download_path = "~/Music/tiddl"
destination_identity = "off"

[metadata]
enable = true
lyrics = true
save_lyrics = true
cover = true

[templates]
default = "{album.artist}/{album.title}/{item.number}. {item.title}"
artist_separator = " / "
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
- **Default**: 1
- **Range**: 1-20
- Number of concurrent downloads (tracks in flight at once, within a single album/playlist). Higher values increase speed but mean more simultaneous connections to Tidal, which is more detectable. The default of 1 is the most conservative setting.

### `requests_per_minute`
- **Type**: integer
- **Default**: 20
- **Range**: 1–300
- Maximum TIDAL API calls per minute. The client enforces a fixed-interval gate with
  per-request jitter so downloads never trigger HTTP 429 (Too Many Requests). Lower this
  value if you still see rate-limit errors; raise it only if you have a high-throughput
  account. The adaptive delay mechanism adjusts automatically, so this value is the
  ceiling, not a guaranteed throughput. Note this only paces metadata/API calls — the
  actual audio file transfer is not rate-limited by this setting.
- **Example**:
  ```toml
  [download]
  requests_per_minute = 20   # default; most conservative
  requests_per_minute = 30   # moderate
  requests_per_minute = 50   # aggressive; raise only if 429s never occur
  ```

### `download_path`
- **Type**: path
- **Default**: ~/Music/tiddl
- Base directory for downloads

### `destination_identity`
- **Type**: `off` / `strict`
- **Default**: `off`
- **Description**: Protects NAS, USB and network destinations from accidental
  writes when the expected volume is missing or has been replaced.
- `off`: preserves the traditional behavior and performs no identity checks.
- `strict`: allows writes only when the configured destination root has a
  matching local trust record and `.tiddl-anchor` marker.

Trust the exact root used by `download_path` before enabling strict mode:

```powershell
tiddl destination trust "Z:\"
tiddl destination status "Z:\"
```

Then configure:

```toml
[download]
download_path = "Z:\\"
destination_identity = "strict"
```

See **[DESTINATION_SAFETY.md](DESTINATION_SAFETY.md)** for Windows, Linux,
macOS, second-machine adoption, recovery and troubleshooting instructions.

### `scan_path`
- **Type**: path
- **Default**: same as download_path
- Directory to scan for existing files

### `video_download_path`
- **Type**: path (optional)
- **Default**: not set (falls back to `download_path`)
- Separate base directory for video downloads only. Overrides `download_path` for videos when set.

### `singles_filter`
- **Type**: none / only / include
- **Default**: none
- How to handle artist singles

### `videos_filter`
- **Type**: none / only / allow
- **Default**: none
- How to handle music videos

### `exclude_compilations`
- **Type**: boolean
- **Default**: false
- When downloading a whole **artist**, skip the artist's compilations. TIDAL lists them as ordinary albums, so they are identified from the artist page (the same "Compilations" section the TIDAL app shows) and skipped by album id. CLI override: `--exclude-compilations` / `--no-exclude-compilations`.

### `exclude_live_albums`
- **Type**: boolean
- **Default**: false
- Same as above for the artist's **live albums** ("Live albums" section). CLI override: `--exclude-live-albums` / `--no-exclude-live-albums`.
- (Note: "Appears On" third-party albums are never part of an artist download, so no option is needed for them.)

### `max_tracks_per_session`
- **Type**: integer
- **Default**: 0 (no limit)
- Stop after downloading this many tracks in a single `tiddl download` run. Restart the command to continue.

### `artist_concurrency`
- **Type**: integer
- **Default**: 1
- Max number of albums downloading in parallel when downloading a full artist. 0 means no limit. The default of 1 processes albums one at a time — the most conservative setting. Lower values reduce API pressure and lower the chance of triggering abuse detection.

### `artist_delay`
- **Type**: float (seconds)
- **Default**: 8.0
- Max random delay before each album starts downloading (artist downloads only). Each album waits a random time between 0 and this value before starting. Staggers API requests to avoid sustained hammering.

### `track_delay`
- **Type**: float (seconds)
- **Default**: 3.0
- Max random delay before each track download starts (all download types — album, playlist, artist, mix). Most of the time waits a short random pause (0.5s–this value); ~15% of the time waits a longer "distracted" pause (2×–6× this value) to look less like a bot. Set to `0` to disable — not recommended for bulk downloads.
- **Example**:
  ```toml
  [download]
  artist_concurrency = 1    # one album at a time (default, safest)
  artist_delay = 8.0        # each album starts after a random 0–8s pause
  track_delay = 3.0         # each track starts after a random pause (default, safest)
  ```

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

### `artist_separator`
- **Type**: string
- **Default**: `" / "`
- Separator used between artist names in template placeholders and embedded metadata tags
- **Options**: `" / "` / `", "` / `"; "` / `" & "` or any custom string
- **Example**:
  ```toml
  [templates]
  artist_separator = " / "
  ```
  With `artist_separator = " / "`, a track by Artist1 and Artist2 renders `{item.artists}` as `Artist1 / Artist2`
- Affects: `{item.artists}`, `{item.features}`, `{item.artists_with_features}`, `{album.artists}`, and the ARTIST/©ART metadata tag in FLAC/M4A/MP4 files

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

> ⚠️ This example uses a **faster, more aggressive** throughput profile than the
> shipped defaults (`threads_count`, `requests_per_minute`, `artist_concurrency`,
> `artist_delay` are all higher than default here). See each option's "Default"
> value above for the safest baseline — the defaults process one album/track at
> a time with real pacing, which is recommended for large bulk downloads.

```toml
enable_cache = true
debug = false

[download]
track_quality = "max"
video_quality = "fhd"
skip_existing = true
threads_count = 4
requests_per_minute = 50
download_path = "~/Music/tiddl"
scan_path = "~/Music/tiddl"
singles_filter = "include"
videos_filter = "allow"
update_mtime = false
rewrite_metadata = true
artist_concurrency = 3
artist_delay = 30.0
track_delay = 5.0

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
artist_separator = " / "  # " / ", ", ", " & ", "; "

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
