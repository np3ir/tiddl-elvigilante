# 📖 Usage Guide - tiddl

**For detailed command reference and placeholders, see [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md) ⭐**

This guide covers practical examples and common scenarios.

---

## 🔐 Authentication

Before downloading, you must authenticate with TIDAL.

### Initial Setup
```bash
tiddl auth login
```

This will:
1. Open your browser
2. Show a code to enter
3. Redirect to tidal.com
4. Save credentials locally

**Credentials stored at:** `~/.tiddl/auth.json`

---

## 🎵 Downloading Music

### Download Single Track
```bash
tiddl download url https://tidal.com/track/123456789
```

### Download Album
```bash
tiddl download url https://tidal.com/album/497662013
```

### Download Playlist
```bash
tiddl download url https://tidal.com/playlist/abc123xyz
```

### Download Artist (All Albums)
```bash
tiddl download url https://tidal.com/artist/789123456
```

### Download Your Favorites
```bash
tiddl download fav
```

Supports all options of `download url`.

---

## 📝 Advanced Options

### Quality
```bash
# Maximum quality (24-bit, 192kHz FLAC)
tiddl download url --track-quality max https://...

# High quality (16-bit, 44.1kHz FLAC)
tiddl download url --track-quality high https://...

# Normal quality (320kbps AAC)
tiddl download url --track-quality normal https://...

# Low quality (96kbps AAC)
tiddl download url --track-quality low https://...
```

### Download Location
```bash
tiddl download url --path "D:/Music" https://...
tiddl download url --path "~/Music/Tidal" https://...
```

### Number of Threads
```bash
# Faster
tiddl download url --threads-count 8 https://...

# Default
tiddl download url --threads-count 4 https://...

# Slower but less resource-intensive
tiddl download url --threads-count 2 https://...
```

### Custom File Naming
```bash
# Artist/Album/Track format
tiddl download url --template "{album.artist}/{album.title}/{item.title}" https://...

# With year
tiddl download url --template "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}" https://...
```

**See [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md) for complete placeholder reference.**

---

## 📊 Getting Information

### Track Info
```bash
tiddl info url https://tidal.com/track/123456789
```

Shows:
- Title, artist, album
- Duration, bitrate
- Release date
- Availability

---

## 📦 Playlist Export

### Export as M3U8
```bash
tiddl export url https://tidal.com/playlist/xyz -o my_playlist.m3u8
```

Works with VLC, Winamp, iTunes, and other media players.

---

## 💡 Common Use Cases

### Maximum Quality Download
```bash
tiddl download url \
  --track-quality max \
  --threads-count 8 \
  https://tidal.com/album/497662013
```

### Organize by Year
In `config.toml`:
```toml
[templates]
default = "{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}"
```

Then:
```bash
tiddl download url https://...
```

Result:
```
Adele/(2008) 21/01. Rolling in the Deep.flac
Adele/(2015) 25/01. Hello.flac
```

### Space-Limited Download
```bash
tiddl download url \
  --track-quality normal \
  --threads-count 2 \
  https://...
```

### Re-download Everything
```bash
tiddl download url --no-skip https://...
```

---

## 🛠️ Troubleshooting

### Authentication Issues
```bash
# Re-authenticate
tiddl auth login

# Debug
tiddl download url --debug https://...
```

### Slow Downloads
```bash
# Increase threads
tiddl download url --threads-count 8 https://...

# Reduce quality
tiddl download url --track-quality high https://...
```

### Network Problems
```bash
# Use fewer threads
tiddl download url --threads-count 2 https://...

# Check debug logs
cat ~/.tiddl/api_debug/...
```

---

## 📚 Reference

- **[COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)** - All commands and placeholders
- **[INDICE_RAPIDO.md](INDICE_RAPIDO.md)** - Quick index
- **[CONFIG.md](CONFIG.md)** - Configuration options

---

**For more options and complete reference, see [COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)**
