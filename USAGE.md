# Tiddl User Manual

Tiddl is a command-line interface (CLI) tool for downloading music and videos from Tidal.

## General Usage

```bash
tiddl [GLOBAL_OPTIONS] COMMAND [ARGS]...
```

### Global Options
*   `--version`, `-v`: Show the version and exit.
*   `--debug`: Enable debug logging (useful for troubleshooting).
*   `--omit-cache`: Disable API caching.

---

## Authentication (`auth`)

Manage your Tidal session.

### `login`
Log in to your Tidal account using the device authorization flow.
```bash
tiddl auth login
```
Follow the on-screen instructions to authenticate via your browser.

### `logout`
Log out and remove the stored access token.
```bash
tiddl auth logout
```

### `refresh`
Manually refresh your access token.
```bash
tiddl auth refresh [OPTIONS]
```
*   `--force`, `-f`: Force a token refresh even if the current one is valid.
*   `--early-expire`, `-e <seconds>`: Refresh if the token expires within the specified number of seconds.

---

## Downloading (`download`)

The core functionality of Tiddl. The `download` command groups common configuration options for its subcommands (`url` and `fav`).

```bash
tiddl download [OPTIONS] SUBCOMMAND [ARGS]...
```

### Configuration Options
These options apply to all download subcommands.

#### Audio & Video Quality
*   `--track-quality`, `-q`: Select audio quality.
    *   Values: `LOW`, `HIGH`, `LOSSLESS`, `HI_RES`, `MAX` (default).
*   `--video-quality`, `-vq`: Select video quality.
    *   Values: `AUDIO_ONLY`, `LOW`, `MEDIUM`, `HIGH`, `MAX` (default).

#### Output & Filesystem
*   `--path`, `-p <path>`: Base directory for downloads.
*   `--scan-path`, `--sp <path>`: Directory to scan for existing files (to avoid re-downloading).
*   `--no-skip`, `-ns`: Download files even if they already exist (overwrite).
*   `--rewrite-metadata`, `-r`: Update tags/metadata for already downloaded files without re-downloading audio.
*   `--threads-count`, `-t <int>`: Number of concurrent download threads (default: 1).
*   `--m3u`, `-m`: Generate M3U8 playlists for albums and playlists.
*   `--keep-cover`, `-kc`: Keep the album cover image file (`cover.jpg`) in the album folder.

#### Filters
*   `--no-singles`, `-nsi`: When downloading an artist, skip singles and EPs.
*   `--videos`, `-v`: Video download policy.
    *   Values: `true` (download videos), `false` (skip videos), `only` (download *only* videos).

#### Templates (Advanced)
Customize how files and folders are named. Templates allow you to define the directory structure and filenames for your downloads.

**Options:**
*   `--template`, `--output`, `-o`: Global fallback template. Used if a specific template is not provided.
*   `--album-template`, `--atf`: Template for album tracks.
*   `--track-template`, `--ttf`: Template for individual tracks (singles).
*   `--video-template`, `--vtf`: Template for videos.
*   `--playlist-template`, `--ptf`: Template for playlist tracks.

**Template Variables:**
You can use the following placeholders in your templates. They support Python-style attribute access (e.g., `{album.title}`).

*   **Common Variables:**
    *   `{item.title}`: Track or video title.
    *   `{item.artist.name}`: Artist name of the track/video.
    *   `{item.trackNumber}`: Track number.
    *   `{item.volumeNumber}`: Disc number.
    *   `{item.duration}`: Duration in seconds.
    *   `{quality}`: Quality of the download (e.g., "LOSSLESS", "HI_RES").

*   **Album Variables:**
    *   `{album.title}`: Album title.
    *   `{album.artist.name}`: Album artist name.
    *   `{album.releaseDate}`: Release date (YYYY-MM-DD).
    *   `{album.year}`: Release year (extracted from date).

*   **Playlist Variables (only for playlists):**
    *   `{playlist.title}`: Playlist title.
    *   `{playlist.uuid}`: Playlist ID.
    *   `{playlist_index}`: Position of the track in the playlist.

**Examples:**
*   Default structure:
    `{album.artist.name}/{album.title}/{item.trackNumber} - {item.title}`
*   Flat structure with quality:
    `{item.artist.name} - {item.title} [{quality}]`
*   Playlist with index:
    `{playlist.title}/{playlist_index:02d} - {item.title}`

### Subcommands

#### 1. `url`
Download specific resources by URL or ID.

```bash
tiddl download [OPTIONS] url [URLS]...
```

**Arguments:**
*   `URLS`: One or more Tidal URLs (e.g., `https://tidal.com/album/12345`) or ID strings (e.g., `album/12345`, `track/98765`). Supported types: `track`, `video`, `album`, `playlist`, `artist`, `mix`.

**Examples:**
```bash
# Download an album in Lossless quality
tiddl download -q LOSSLESS url https://tidal.com/album/12345

# Download a specific track and a playlist
tiddl download url track/123456 playlist/789012
```

#### 2. `fav`
Download items from your Tidal favorites (My Collection).

```bash
tiddl download [OPTIONS] fav [OPTIONS]
```

**Options:**
*   `--types`, `-t`: Specify which resource types to download. Can be used multiple times.
    *   Values: `track`, `video`, `album`, `playlist`, `artist`.
    *   Default: All types.

**Examples:**
```bash
# Download all favorite albums and playlists
tiddl download fav -t album -t playlist

# Download everything in your collection
tiddl download fav
```

---

## Other Commands

### `info`
Get information about a specific resource (metadata).
*(Usage details depending on implementation)*

### `export`
Export data.
*(Usage details depending on implementation)*
