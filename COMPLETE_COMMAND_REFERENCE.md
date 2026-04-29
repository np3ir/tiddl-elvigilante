# 🎯 Complete Command Reference - tiddl

**Comprehensive guide to using tiddl** | Simple explanations for everyone

---

## 📋 Table of Contents

1. [Main Commands](#main-commands)
2. [Download Subcommands](#download-subcommands)
3. [Global Options](#global-options)
4. [Command Options](#command-options)
5. [Path Placeholders](#path-placeholders)
6. [Practical Examples](#practical-examples)
7. [Common Use Cases](#common-use-cases)

---

# 🎵 Main Commands

## 1. `tiddl auth` - Authentication

Manage your TIDAL access.

### Subcommands

#### **`tiddl auth login`**
Sign in with your TIDAL account.

```bash
tiddl auth login
```

**What it does:**
1. Opens your browser
2. Shows a code to enter
3. Waits for you to enter code at tidal.com
4. Saves credentials locally

**Requirements**: None on first use

---

#### **`tiddl auth logout`**
Sign out.

```bash
tiddl auth logout
```

**What it does:**
- Removes local credentials
- Invalidates token on TIDAL

---

## 2. `tiddl download` - Download Content

Download music, videos, playlists, etc.

### 2.1 Download by URL: `tiddl download url`

Download content using a link.

#### Basic Syntax
```bash
tiddl download url <URL>
```

#### Supported URLs

```bash
# Track (song)
tiddl download url https://tidal.com/track/123456789

# Album
tiddl download url https://tidal.com/album/497662013

# Playlist
tiddl download url https://tidal.com/playlist/abc123xyz

# Artist (all albums)
tiddl download url https://tidal.com/artist/789123456

# Mix
tiddl download url https://tidal.com/mix/mixed123xyz
```

#### Options

```bash
# Audio quality
tiddl download url --track-quality max https://...     # 24-bit, 192kHz FLAC
tiddl download url --track-quality high https://...    # 16-bit, 44.1kHz FLAC
tiddl download url --track-quality normal https://...  # 320kbps AAC
tiddl download url --track-quality low https://...     # 96kbps AAC

# Video quality
tiddl download url --video-quality fhd https://...     # 1080p
tiddl download url --video-quality hd https://...      # 720p
tiddl download url --video-quality sd https://...      # 360p

# Download location
tiddl download url --path "D:/Music" https://...
tiddl download url -p "~/Music/Tidal" https://...

# Don't skip existing files (re-download)
tiddl download url --no-skip https://...
tiddl download url -ns https://...

# Number of download threads
tiddl download url --threads-count 8 https://...
tiddl download url -t 4 https://...

# Rewrite metadata
tiddl download url --rewrite-metadata https://...
tiddl download url -r https://...

# Naming template
tiddl download url --template "{album.artist}/{album.title}/{item.title}" https://...

# Debug
tiddl download url --debug https://...
```

---

### 2.2 Download Favorites: `tiddl download fav`

Download all your TIDAL favorites.

```bash
tiddl download fav
```

**What it does:**
- Downloads all songs marked as favorite
- Supports all `download url` options

**Example with options:**
```bash
tiddl download fav --track-quality max --threads-count 8
```

---

### 2.3 Search TIDAL: `tiddl download search`

Search TIDAL for tracks, albums, and artists.

```bash
tiddl download search <query>
```

**What it does:**
- Searches TIDAL for the given query
- Displays the Top Hit prominently with a ready-to-use download command
- Shows tables of matching tracks, albums, and artists with their IDs
- Works even when the Bearer token is unavailable (uses x-tidal-token fallback)

**Options:**
```bash
# Limit results per category (default: 10, max: 50)
tiddl download search "Pink Floyd" --limit 5
tiddl download search "Dark Side of the Moon" -l 20
```

**Example output:**
```
Top Hit: [tracks] Money (ID: 12345678)
  tiddl download url tracks/12345678

Tracks
 ID           Title            Artist        Album                  Quality
 12345678     Money            Pink Floyd    The Dark Side...       LOSSLESS

Download: tiddl download url track/{ID}
```

**Workflow:**
1. Search for content: `tiddl download search "artist or album"`
2. Copy the ID from results
3. Download: `tiddl download url track/12345678`

---

## 3. `tiddl info` - Information

Get details about content without downloading.

```bash
tiddl info url https://tidal.com/album/497662013
```

**Shows:**
- Title
- Artist/Artists
- Duration
- Available bitrate
- Release date
- Availability

---

## 4. `tiddl export` - Export Playlist

Save a playlist as M3U8 file (compatible with media players).

```bash
tiddl export url https://tidal.com/playlist/xyz -o my_playlist.m3u8
```

**Options:**
```bash
# Save to specific folder
tiddl export url https://... -o "D:/Playlists/playlist.m3u8"
tiddl export url https://... --output "~/Music/my_playlist.m3u8"
```

---

# 🔄 Download Subcommands

## Complete Structure

```
tiddl download
├── url          # Download by link
│   ├── https://tidal.com/track/...
│   ├── https://tidal.com/album/...
│   ├── https://tidal.com/playlist/...
│   └── https://tidal.com/artist/...
├── fav          # Download favorites
└── search       # Search TIDAL catalog
```

---

# ⚙️ Global Options

These options work with **ALL** commands:

```bash
# Show version
tiddl --version
tiddl -v

# Show help
tiddl --help
tiddl -h

# Debug (saves detailed logs)
tiddl --debug <command>

# Skip cache
tiddl --omit-cache <command>
```

---

# 📋 Command Options

## Download Command Options

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--track-quality` | `-q` | low/normal/high/max | high | Audio quality |
| `--video-quality` | `-vq` | sd/hd/fhd | fhd | Video quality |
| `--no-skip` | `-ns` | bool | false | Don't skip existing |
| `--rewrite-metadata` | `-r` | bool | false | Rewrite existing metadata |
| `--threads-count` | `-t` | 1-20 | 4 | Concurrent downloads |
| `--path` | `-p` | path | ~/Music/tiddl | Download folder |
| `--template` | - | string | config | Naming template |
| `--scan-path` | `--sp` | path | same as path | Folder to scan |
| `--debug` | - | bool | false | Save API logs |

---

# 🎨 Path Placeholders

"Placeholders" are variables automatically replaced with real information.

## Item Placeholders (Songs/Videos)

```bash
{item.id}                      # Song ID
                               # Example: 123456789

{item.title}                   # Song title
                               # Example: "Song Name"

{item.title_version}           # Title with version
                               # Example: "Song Name (Remix)"

{item.number}                  # Track number
                               # Example: 1, 2, 3

{item.volume}                  # Volume/disc number
                               # Example: 1, 2

{item.version}                 # Extended version
                               # Example: "(Remix)", "(Acoustic)"

{item.artist}                  # Main artist
                               # Example: "The Beatles"

{item.safe_artist}             # Artist with safe characters

{item.artists}                 # All artists (separated by artist_separator)
                               # Example: "Artist1, Artist2"
                               # With artist_separator = " / ": "Artist1 / Artist2"

{item.safe_artists}            # Artists with safe characters

{item.features}                # Only featured artists (separated by artist_separator)
                               # Example: "Artist3, Artist4"

{item.artists_with_features}   # Artists + featured (separated by artist_separator)
                               # Example: "Artist1, Artist2"

{item.explicit}                # Explicit indicator
                               # Example: "[E]" if explicit

{item.genre}                   # Genre
                               # Example: "Pop", "Hip-Hop"

{item.copyright}               # Copyright info

{item.bpm}                     # BPM (beats per minute)
                               # Example: 120

{item.isrc}                    # ISRC code

{item.quality}                 # Downloaded quality
                               # Example: "FLAC", "AAC"

{item.releaseDate}             # Release date
                               # See date formatting below

{item.streamStartDate}         # Availability date
                               # See date formatting below

{item.dolby}                   # Dolby Atmos (if available)
```

---

## Album Placeholders

```bash
{album.id}                     # Album ID
                               # Example: 497662013

{album.title}                  # Album name
                               # Example: "Album Name"

{album.safe_title}             # Title with safe characters

{album.artist}                 # Album artist
                               # Example: "The Beatles"

{album.safe_artist}            # Artist with safe characters

{album.artists}                # All album artists (separated by artist_separator)

{album.safe_artists}           # Artists with safe characters

{album.date}                   # Release date
                               # Example: 2023-01-15
                               # See date formatting below

{album.explicit}               # Explicit indicator

{album.master}                 # If Master Quality
                               # (empty if not, "Master" if yes)

{album.release}                # Release type
                               # Example: "ALBUM", "SINGLE", "EP"
```

---

## Playlist Placeholders

```bash
{playlist.uuid}                # Playlist unique ID
                               # Example: "abc123xyz"

{playlist.title}               # Playlist name
                               # Example: "My Playlist"

{playlist.index}               # Track number in playlist
                               # Example: 1, 2, 3

{playlist.created}             # Creation date
                               # See date formatting below

{playlist.updated}             # Last update
                               # See date formatting below
```

---

## Special Placeholders

```bash
{artist_initials}              # Artist first letter
                               # Example: "T" for "The Beatles"
                               # Groups by letter

{album.artist}                 # Same as album.artist
```

---

## Date Formatting

Dates can be formatted many ways:

```bash
# Basic format (ISO)
{item.releaseDate}             # 2023-01-15

# Year only
{item.releaseDate:%Y}          # 2023

# Year-month
{item.releaseDate:%Y-%m}       # 2023-01

# Year-month-day
{item.releaseDate:%Y-%m-%d}    # 2023-01-15

# Month name
{item.releaseDate:%B}          # January

# Month short
{item.releaseDate:%b}          # Jan

# Day
{item.releaseDate:%d}          # 15

# American format
{item.releaseDate:%m/%d/%Y}    # 01/15/2023

# European format
{item.releaseDate:%d/%m/%Y}    # 15/01/2023

# With time
{item.releaseDate:%Y-%m-%d %H:%M}  # 2023-01-15 14:30

# Custom - combine as needed
{item.releaseDate:%A, %B %d, %Y}   # Sunday, January 15, 2023
```

---

## Artist Separator

Controls how multiple artist names are joined in placeholders like `{item.artists}`, `{item.features}`, and `{item.artists_with_features}`, as well as in embedded metadata tags.

```toml
[templates]
artist_separator = ", "   # Default: comma + space
# Other options:
# artist_separator = "; "   # Semicolon
# artist_separator = " / "  # Slash
# artist_separator = " & "  # Ampersand
```

**Examples with different separators:**
```bash
# artist_separator = ", "  →  "Drake, 21 Savage, Metro Boomin"
# artist_separator = "; "  →  "Drake; 21 Savage; Metro Boomin"
# artist_separator = " / " →  "Drake / 21 Savage / Metro Boomin"
# artist_separator = " & " →  "Drake & 21 Savage & Metro Boomin"
```

---

## Other Variables

```bash
{quality}                      # Download quality
                               # Example: "max", "high"

{now}                          # Current date and time
                               # Example: 2026-03-01
                               # Can be formatted like dates

{now:%Y}                       # Current year
{now:%Y-%m-%d}                 # Current date
{now:%H-%M}                    # Current time
```

---

# 💡 Practical Examples

## Example 1: Simple Structure

```bash
# Config: default = "{album.artist}/{album.title}/{item.title}"

# Result:
The Beatles/Abbey Road/Come Together.flac
The Beatles/Abbey Road/Maxwell's Silver Hammer.flac
The Beatles/Abbey Road/Oh! Darling.flac
```

---

## Example 2: With Track Numbers

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.title}"

# Result:
The Beatles/Abbey Road/01. Come Together.flac
The Beatles/Abbey Road/02. Maxwell's Silver Hammer.flac
The Beatles/Abbey Road/03. Oh! Darling.flac
```

---

## Example 3: With Album Year

```bash
# Template: "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"

# Result:
The Beatles/(1969) Abbey Road/01. Come Together.flac
The Beatles/(1969) Abbey Road/02. Maxwell's Silver Hammer.flac
The Beatles/(1969) Abbey Road/03. Oh! Darling.flac
```

---

## Example 4: Group by Initial Letter

```bash
# Template: "{artist_initials}/{album.artist}/{album.title}/{item.title}"

# Result:
T/The Beatles/Abbey Road/Come Together.flac
T/The Beatles/Abbey Road/Maxwell's Silver Hammer.flac
D/Drake/Certified Lover Boy/Champagne Poetry.flac
D/Drake/Certified Lover Boy/In the Cut.flac
```

---

## Example 5: With Featured Artists

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.artists_with_features}"

# Result:
Drake/Certified Lover Boy/01. Drake feat. 21 Savage.flac
Drake/Certified Lover Boy/02. Drake feat. Giveon.flac
Drake/Certified Lover Boy/03. Drake.flac
```

---

## Example 6: With Version (Remix, Acoustic)

```bash
# Template: "{album.artist}/{album.title}/{item.number}. {item.title} {item.version}"

# Result:
The Weeknd/Dawn FM/01. Gasoline (Remix).flac
The Weeknd/Dawn FM/02. Take My Breath (Extended).flac
The Weeknd/Dawn FM/03. Sacrifice (Acoustic).flac
```

---

## Example 7: Artist Only

```bash
# Template: "{album.artist}/{item.title}"

# Result:
The Beatles/Come Together.flac
The Beatles/Maxwell's Silver Hammer.flac
Drake/Champagne Poetry.flac
Drake/In the Cut.flac
```

---

## Example 8: All Album Artists

```bash
# Template: "{album.artists}/{album.title}/{item.number}. {item.title}"

# Result (if multiple artists):
The Beatles, Yoko Ono/Abbey Road/01. Come Together.flac
```

---

# 🎯 Common Use Cases

## Case 1: "I have limited space"

```bash
tiddl download url https://... \
  --track-quality normal \
  --threads-count 2
```

**Explanation:**
- `normal` = 320kbps (much less than FLAC)
- Fewer threads = lower bandwidth and RAM usage

---

## Case 2: "I want maximum quality"

```bash
tiddl download url https://tidal.com/album/497662013 \
  --track-quality max \
  --path "D:/HighQuality"
```

**Explanation:**
- `max` = 24-bit, 192kHz FLAC (best quality)
- Separate folder to organize them

---

## Case 3: "I want to organize by year"

In `config.toml`:
```toml
[templates]
default = "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"
```

```bash
tiddl download url https://...
```

**Result:**
```
Adele/(2008) 21/01. Rolling in the Deep.flac
Adele/(2015) 25/01. Hello.flac
Adele/(2019) 30/01. Easy On Me.flac
```

---

## Case 4: "Change download folder quickly"

```bash
tiddl download url https://... --path "E:/Backup"
```

No need to edit config.toml, the flag overrides it.

---

## Case 5: "Don't re-download"

```bash
# Keep skip_existing = true in config.toml (default)
tiddl download url https://...

# Or use the flag
tiddl download url https://... --no-skip   # RE-DOWNLOADS EVERYTHING
```

---

## Case 6: "Download album fast"

```bash
tiddl download url https://tidal.com/album/497662013 \
  --track-quality high \
  --threads-count 8
```

**Explanation:**
- `high` = Good quality without being excessive
- 8 threads = maximum speed

---

## Case 7: "Update outdated metadata"

```bash
tiddl download url https://... \
  --rewrite-metadata \
  --no-skip
```

---

## Case 8: "Download with custom naming"

In `config.toml`:
```toml
[templates]
default = "{album.artist} - ({album.date:%Y}) {album.title}/{item.number:02d} - {item.title}"
```

```bash
tiddl download fav
```

---

# 🔧 Troubleshooting

## "What is --debug?"

```bash
tiddl download url https://... --debug
```

Creates detailed logs in `~/.tiddl/api_debug/`

**Use it if:**
- Download fails
- Want to see what the app does
- Having network problems

---

## "Why don't some placeholders work?"

```bash
# ❌ This fails:
{item.unknown_field}

# ✅ Use valid placeholders:
{item.title}
{album.artist}
{item.releaseDate:%Y}
```

---

## "How do I use network paths?"

```bash
# Windows UNC
--path "//server/share/Music"

# Or like this:
--path "\\\\server\\share\\Music"
```

---

# 📚 Quick Reference

```bash
# AUTHENTICATION
tiddl auth login
tiddl auth logout

# DOWNLOAD
tiddl download url https://tidal.com/album/123      # By URL
tiddl download fav                                    # Favorites

# INFORMATION
tiddl info url https://tidal.com/album/123

# EXPORT
tiddl export url https://tidal.com/playlist/xyz -o file.m3u8

# COMMON OPTIONS
--track-quality max                                   # Maximum quality
--path "D:/Music"                                     # Folder
--threads-count 8                                     # Speed
--no-skip                                             # Re-download
--template "{artist}/{album}/{title}"                # Custom naming
--debug                                               # Logs

# MAIN VARIABLES
{item.title}                                          # Song
{album.artist}                                        # Artist
{album.title}                                         # Album
{album.date:%Y}                                       # Year
{item.number}                                         # Track #
{item.artists_with_features}                         # Featured artists
```

---

**End of Complete Reference** 🎉

All commands are simple to understand if you follow these examples.

You're ready to use tiddl! 🚀

