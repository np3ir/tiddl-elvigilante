# Configuration Guide for tiddl

This guide provides a detailed overview of all configuration options available through the `config.toml` file and command-line arguments.

## `config.toml` File

The configuration file is the best way to set your preferences permanently. The file is located at `~/.tiddl/config.toml` (or `%USERPROFILE%\.tiddl\config.toml` on Windows).

### General Settings

| Parameter      | Type    | Default | Description                                                   |
| -------------- | ------- | ------- | ------------------------------------------------------------- |
| `enable_cache` | boolean | `true`  | Enables caching for API responses to speed up repeated requests. |
| `debug`        | boolean | `false` | Enables verbose debug logging.                                |

### `[metadata]` Section

Controls how metadata is handled for downloaded files.

| Parameter        | Type    | Default | Description                                                          |
| ---------------- | ------- | ------- | -------------------------------------------------------------------- |
| `enable`         | boolean | `true`  | Master switch to enable or disable all metadata processing.          |
| `embed_lyrics`   | boolean | `false` | Embeds lyrics into the music file's metadata tag.                  |
| `save_lyrics`    | boolean | `false` | Saves lyrics as a separate `.lrc` file alongside the music file.     |
| `cover`          | boolean | `false` | Embeds the album cover art into the music file's metadata.         |
| `album_review`   | boolean | `false` | Embeds the album review (if available) into the comment metadata tag. |

### `[cover]` Section

Controls the handling of separate cover art image files.

| Parameter | Type                  | Default | Description                                                                |
| --------- | --------------------- | ------- | -------------------------------------------------------------------------- |
| `save`    | boolean               | `false` | Saves cover art as a separate image file.                                  |
| `size`    | integer               | `1280`  | The desired size (width) of the cover art image in pixels.                 |
| `allowed` | list of strings       | `[]`    | Specifies for which resource types to save covers. e.g., `["album", "playlist"]` |

#### `[cover.templates]`

Defines the filename for saved cover art.

| Parameter  | Type   | Default | Description                       |
| ---------- | ------ | ------- | --------------------------------- |
| `track`    | string | `""`    | Template for track-specific covers. |
| `album`    | string | `""`    | Template for album covers.        |
| `playlist` | string | `""`    | Template for playlist covers.     |

### `[download]` Section

Core settings related to the download process.

| Parameter          | Type    | Default                          | Description                                                                                             |
| ------------------ | ------- | -------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `track_quality`    | string  | `"high"`                         | Desired track quality. Options: `"LOW"`, `"HIGH"`, `"LOSSLESS"`, `"HIRES"`.                           |
| `video_quality`    | string  | `"fhd"`                          | Desired video quality. Options: `"360"`, `"480"`, `"720"`, `"1080"`.                                 |
| `skip_existing`    | boolean | `true`                           | If `true`, skips downloading files that already exist in the destination.                               |
| `threads_count`    | integer | `2`                              | Number of concurrent download threads.                                                                  |
| `download_path`    | string  | `"~/Music/tiddl"`                | The base directory where all files will be downloaded.                                                  |
| `scan_path`        | string  | `"~/Music/tiddl"`                | The directory to scan for existing files (defaults to `download_path` if not set).                      |
| `singles_filter`   | string  | `"none"`                         | When downloading an artist: `"none"` (albums only), `"only"` (singles only), or `"include"` (both). |
| `videos_filter`    | string  | `"none"`                         | `"none"` (no videos), `"allow"` (download videos alongside tracks), `"only"` (download only videos). |
| `update_mtime`     | boolean | `false`                          | If `true`, updates the file's modification time upon download/metadata rewrite.                         |
| `rewrite_metadata` | boolean | `false`                          | If `true`, forces a rewrite of metadata tags for already existing files.                                |

### `[m3u]` Section

Controls the creation of M3U playlist files.

| Parameter | Type                  | Default | Description                                                                   |
| --------- | --------------------- | ------- | ----------------------------------------------------------------------------- |
| `save`    | boolean               | `false` | If `true`, creates an `.m3u` playlist file for albums, playlists, or mixes.   |
| `allowed` | list of strings       | `[]`    | Specifies for which resource types to create M3U files. e.g., `["album"]` |

#### `[m3u.templates]`

| Parameter  | Type   | Default | Description                          |
| ---------- | ------ | ------- | ------------------------------------ |
| `album`    | string | `""`    | Filename template for album M3U files. |
| `playlist` | string | `""`    | Filename template for playlist M3U files. |
| `mix`      | string | `""`    | Filename template for mix M3U files.      |

### `[templates]` Section

Defines the directory and file naming structure for downloads.

| Parameter  | Type   | Default                                     | Description                                                                                                                              |
| ---------- | ------ | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `default`  | string | `"{album.artist}/{album.title}/{item.title}"` | The global fallback template used if a more specific template is not provided.                                                           |
| `track`    | string | `""`                                        | Specific template for track downloads. Falls back to `default`.                                                                          |
| `video`    | string | `""`                                        | Specific template for video downloads. Falls back to `default`.                                                                          |
| `album`    | string | `""`                                        | Specific template for album downloads (used for folder structure). Falls back to `default`.                                            |
| `playlist` | string | `""`                                        | Specific template for playlist downloads (used for folder structure). Falls back to `default`.                                           |
| `mix`      | string | `""`                                        | Specific template for mix downloads. Falls back to `default`.                                                                            |

---

## Command-Line Options

These options can be used with `tiddl download` to override the `config.toml` settings for a single run.

| Option                 | Short | Description                                                   |
| ---------------------- | ----- | ------------------------------------------------------------- |
| `--track-quality`      | `-q`  | Set the track quality for this run.                           |
| `--video-quality`      | `-vq` | Set the video quality for this run.                           |
| `--no-skip`            | `-ns` | Force downloads even if files exist (opposite of `skip_existing`). |
| `--rewrite-metadata`   | `-r`  | Force a rewrite of metadata for existing files.               |
| `--threads-count`      | `-t`  | Set the number of concurrent download threads.                |
| `--path`               | `-p`  | Set the base download directory for this run.                 |
| `--scan-path`          | `--sp`| Set the directory to scan for existing files.                 |
| `--template`, `--output`| `-o`  | Set the global fallback template for this run.                |
| `--album-template`     | `--atf` | Set the album folder template for this run.                   |
| `--track-template`     | `--ttf` | Set the track filename template for this run.                 |
| `--video-template`     | `--vtf` | Set the video filename template for this run.                 |
| `--playlist-template`  | `--ptf` | Set the playlist folder template for this run.                |
| `--singles`            | `-s`  | Set the artist singles filter for this run.                   |
| `--videos`             | `-vid`| Set the video download filter for this run.                   |
