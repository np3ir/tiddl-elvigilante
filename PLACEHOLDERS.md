# tiddl-elvigilante template placeholders

> [Versión en español](PLACEHOLDERS_ES.md)

This reference is derived from the current `tiddl-elvigilante` code, primarily `tiddl/core/utils/format.py` and the additional variables supplied by download commands.

Placeholders are written inside braces in a template:

```toml
[templates]
default = "{album.artist}/{album.title}/{item.number:02}. {item.title}"
```

Use `/` to separate directories, including on Windows. tiddl converts and sanitizes the resulting path for the target filesystem.

## Track or video — `{item.*}`

| Placeholder | Description |
|---|---|
| `{item.id}` | TIDAL track or video ID. |
| `{item.title}` | Clean title without the appended version. |
| `{item.safe_title}` | Title sanitized for use in filenames. |
| `{item.title_version}` | Title plus the version in parentheses, for example `Song (Remastered 2011)`. |
| `{item.number}` | Track number. Supports zero padding, for example `{item.number:02}`. |
| `{item.volume}` | Disc or volume number. |
| `{item.version}` | Raw version text, for example `Remastered 2011`; parentheses are not added automatically. |
| `{item.copyright}` | Copyright text. |
| `{item.bpm}` | Beats per minute. |
| `{item.isrc}` | ISRC code. |
| `{item.quality}` | Quality supplied to the formatter for this item. |
| `{item.artist}` | Primary artist. |
| `{item.safe_artist}` | Primary artist sanitized for the filesystem. |
| `{item.artists}` | Primary artists joined with `artist_separator`. |
| `{item.safe_artists}` | Joined primary artists, sanitized for the filesystem. |
| `{item.features}` | Featured artists joined with `artist_separator`. |
| `{item.artists_with_features}` | Primary and featured artists joined with `artist_separator`. |
| `{item.explicit}` | Explicit-content indicator. Supports the modifiers described below. |
| `{item.genre}` | Genre obtained from the item's album. |
| `{item.dolby}` | Conditional value for Dolby Atmos. It prints the supplied format text only for Atmos items. |
| `{item.releaseDate}` | Release date. Supports `strftime` formatting. |
| `{item.streamStartDate}` | Streaming availability start date. Supports `strftime` formatting. |

Artist names displayed in paths are limited to the first three. If more artists exist, tiddl appends `& others`. Internal media tags retain the complete artist information.

## Album — `{album.*}`

| Placeholder | Description |
|---|---|
| `{album.id}` | TIDAL album ID. |
| `{album.title}` | Album title. |
| `{album.safe_title}` | Album title sanitized for the filesystem. |
| `{album.artist}` | Album's primary artist. |
| `{album.safe_artist}` | Album's primary artist sanitized for the filesystem. |
| `{album.artists}` | Album primary artists joined with `artist_separator`. |
| `{album.safe_artists}` | Joined primary artists, sanitized for the filesystem. |
| `{album.date}` | Album release date. Supports `strftime` formatting. |
| `{album.explicit}` | Explicit-content indicator. Supports the same modifiers as `{item.explicit}`. |
| `{album.master}` | Conditional Master/HiRes quality value. It prints the supplied format text only when applicable. |
| `{album.release}` | Release type, normally `ALBUM`, `SINGLE`, or `EP`. |

When a video or another item has no album, tiddl builds a fallback album: it uses the item's title and artist, sets `{album.id}` to `0`, sets `{album.release}` to `SINGLE`, and disables `{album.master}`.

## Playlist — `{playlist.*}`

| Placeholder | Description |
|---|---|
| `{playlist.uuid}` | Playlist UUID. |
| `{playlist.title}` | Playlist title. |
| `{playlist.index}` | Item position within the playlist. |
| `{playlist.created}` | Creation date. Supports `strftime` formatting. |
| `{playlist.updated}` | Last update date. Supports `strftime` formatting. |

## Unprefixed global aliases

| Placeholder | Description and availability |
|---|---|
| `{title}` | Alias for `{item.title}`. Available only when an item is present. |
| `{artist}` | Alias for `{item.artist}`. Available only when an item is present. |
| `{albumartist}` | Alias for `{album.artist}`. Available only when an album is present. |
| `{artist_initials}` | Initial letter or category for the artist. When an album is present, tiddl prefers the album artist; otherwise it uses the item artist. |
| `{release_date}` | Alias for `{album.date}`. Available only when an album is present. |
| `{quality}` | Quality passed to the formatter, such as `MAX`, `HIGH`, or another value from the download flow. |
| `{now}` | Current date and time. Supports `strftime` formatting. |

## Contextual variables

These variables are not available in every template. The download command supplies them only in specific contexts.

| Placeholder | Availability | Description |
|---|---|---|
| `{mix_id}` | Mix and mix M3U templates | Mix ID. |
| `{type}` | Album, playlist, or mix M3U templates | Resource type: `album`, `playlist`, or `mix`. |

## Date and time formatting

Date fields are `datetime` objects and accept standard `strftime` codes:

| Example | Approximate result |
|---|---|
| `{item.releaseDate}` | `2024-03-15 00:00:00` |
| `{item.releaseDate:%Y}` | `2024` |
| `{item.releaseDate:%Y-%m}` | `2024-03` |
| `{item.releaseDate:%Y-%m-%d}` | `2024-03-15` |
| `{album.date:%B}` | `March` |
| `{playlist.created:%d-%m-%Y}` | `15-03-2024` |
| `{now:%Y-%m-%d}` | Current date. |
| `{now:%H-%M}` | Current hour and minute. |

Other supported codes include `%d` (day), `%m` (month), `%b` (abbreviated month), `%B` (month name), `%A` (weekday), `%H` (hour), `%M` (minute), and `%S` (second).

A missing or invalid date is converted internally to `datetime.min`; verify the result before using dates from incomplete sources in final filenames.

## Number formatting

Numbers use Python's standard format specification mini-language:

```toml
track = "{album.artist}/{album.title}/{item.number:02}. {item.title}"
```

Examples:

| Placeholder | Value 5 | Result |
|---|---:|---:|
| `{item.number}` | 5 | `5` |
| `{item.number:02}` | 5 | `05` |
| `{item.number:03}` | 5 | `005` |
| `{playlist.index:02}` | 5 | `05` |

## Explicit-content modifiers

When the item or album is not explicit, every format below produces an empty string.

| Placeholder | Result when explicit |
|---|---|
| `{item.explicit}` | `E` |
| `{item.explicit:upper}` | `E` |
| `{item.explicit:long}` | `explicit` |
| `{item.explicit:upperlong}` | `EXPLICIT` |
| `{item.explicit:parens}` | ` (Explicit)` |
| `{item.explicit:shortparens}` | ` (explicit)` |

The same modifiers work with `{album.explicit}`.

Example:

```toml
track = "{item.number:02}. {item.title}{item.explicit:parens}"
```

Result: `01. Song Name (Explicit)` or `01. Song Name`.

## Conditional text for Master and Dolby Atmos

`{album.master}` and `{item.dolby}` are conditional values. Text written after `:` appears only when the condition is true:

```toml
track = "{item.title} {album.master:MQA}{item.dolby:Dolby Atmos}"
```

| Placeholder | True condition | False condition |
|---|---|---|
| `{album.master:HiRes}` | `HiRes` | empty string |
| `{album.master:[MASTER]}` | `[MASTER]` | empty string |
| `{item.dolby:Atmos}` | `Atmos` | empty string |
| `{item.dolby:[DOLBY ATMOS]}` | `[DOLBY ATMOS]` | empty string |

Without format text, `{album.master}` and `{item.dolby}` produce an empty string even when the condition is true. They should therefore normally be used with `:text`.

## Artist separator

Configure the separator in `config.toml`:

```toml
[templates]
artist_separator = " / "
```

It affects:

- `{item.artists}`
- `{item.safe_artists}`
- `{item.features}`
- `{item.artists_with_features}`
- `{album.artists}`
- `{album.safe_artists}`
- artist tags written to media files

Common values include `" / "`, `", "`, `" & "`, and `"; "`.

## Where templates are configured

```toml
[templates]
default = "{album.artist}/{album.title}/{item.title}"
track = ""
video = ""
album = ""
playlist = ""
mix = ""
artist_separator = " / "
```

Empty `track`, `video`, `album`, `playlist`, and `mix` values inherit from `default`.

Templates are also reused for covers and M3U files:

```toml
[cover.templates]
track = ""
album = ""
playlist = ""

[m3u.templates]
album = ""
playlist = ""
mix = ""
```

Placeholder availability depends on the objects passed to the formatter. For example, a mix M3U template receives `{mix_id}` and `{type}`, but does not necessarily receive `{item.*}` or `{album.*}`.

## Complete examples

### Library by initial, artist, and year

```toml
[templates]
default = "{artist_initials}/{album.artist}/({album.date:%Y}) {album.title}/{item.number:02}. {item.title}"
```

```text
B/The Beatles/(1969) Abbey Road/01. Come Together.flac
```

### Featured artists and explicit content

```toml
[templates]
track = "{album.artist}/{album.title}/{item.number:02}. {item.artists_with_features} - {item.title}{item.explicit:parens}"
```

### Ordered playlist

```toml
[templates]
playlist = "Playlists/{playlist.title}/{playlist.index:03}. {item.artist} - {item.title}"
```

### Mix

```toml
[templates]
mix = "Mixes/{mix_id}/{item.artist} - {item.title}"

[m3u.templates]
mix = "Mixes/{mix_id}/{type}-{mix_id}"
```

### Conditional quality indicators

```toml
[templates]
album = "{album.artist}/{album.title} {album.master:[HIRES]}/{item.number:02}. {item.title}{item.dolby: [ATMOS]}"
```

## Summary: all placeholders

```text
{item.id}
{item.title}
{item.safe_title}
{item.title_version}
{item.number}
{item.volume}
{item.version}
{item.copyright}
{item.bpm}
{item.isrc}
{item.quality}
{item.artist}
{item.safe_artist}
{item.artists}
{item.safe_artists}
{item.features}
{item.artists_with_features}
{item.explicit}
{item.genre}
{item.dolby}
{item.releaseDate}
{item.streamStartDate}

{album.id}
{album.title}
{album.safe_title}
{album.artist}
{album.safe_artist}
{album.artists}
{album.safe_artists}
{album.date}
{album.explicit}
{album.master}
{album.release}

{playlist.uuid}
{playlist.title}
{playlist.index}
{playlist.created}
{playlist.updated}

{title}
{artist}
{albumartist}
{artist_initials}
{release_date}
{quality}
{now}

{mix_id}
{type}
```

## Technical notes

- If a template contains a missing or context-incompatible placeholder, tiddl does not always raise an error: the segment may become sanitized literal text. Test a new template with a small download first.
- If an album has multiple discs and the template does not include `{item.volume}`, tiddl automatically inserts a `Disc N` directory before the filename.
- Names are normalized to Unicode NFC and sanitized to remove filesystem-incompatible characters.
- Each path component is limited to 255 bytes. The final component reserves space for the extension.
- `{item.safe_title}`, `{item.safe_artist}`, `{item.safe_artists}`, `{album.safe_title}`, `{album.safe_artist}`, and `{album.safe_artists}` are useful when you want explicit control over sanitized parts, although the complete final path is sanitized as well.
