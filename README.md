⚠️ **Disclaimer**: This application is for personal, educational, and archival purposes only. It is not affiliated with TIDAL. Users must ensure their use complies with TIDAL's Terms of Service and all applicable copyright laws.

---

# tiddl - TIDAL Downloader

Modern Python 3.10+ compatible TIDAL downloader. Download music and videos with complete metadata preservation.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## 🚀 Install & Use

### Simplest Way
```bash
pip install git+https://github.com/yourusername/tiddl-elvigilante.git
```

Then use:
```bash
tiddl-elvigilante auth
tiddl-elvigilante download "https://tidal.com/browse/album/123456"
```

### Or Clone
```bash
git clone https://github.com/yourusername/tiddl-elvigilante.git
cd tiddl-elvigilante
pip install -r requirements.txt
python -m cli auth
```

## ✨ Features

- 🎵 Download tracks, albums, playlists
- 🎬 Download music videos
- 📝 Complete metadata (artist, album, cover, lyrics)
- 🌍 Unicode support (CJK, Arabic, Vietnamese)
- ⚡ Async downloading
- 📦 M3U8 playlist export
- 🔐 Secure authentication

## 📋 Requirements

- Python 3.10+
- FFmpeg
- TIDAL account

## 🔧 Install FFmpeg

**Windows:**
```bash
winget install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt install ffmpeg
```

## 📖 Usage Examples

```bash
# Authenticate
tiddl-elvigilante auth

# Download track
tiddl-elvigilante download "https://tidal.com/browse/track/123"

# Download album
tiddl-elvigilante download "https://tidal.com/browse/album/456"

# Download playlist
tiddl-elvigilante download "https://tidal.com/browse/playlist/789"

# Download favorites
tiddl-elvigilante download fav

# Get info
tiddl-elvigilante info "https://..."

# Export playlist
tiddl-elvigilante export "https://..." -o playlist.m3u8
```

## 📚 Documentation

- [FORK.md](FORK.md) - About this fork
- [CONFIG.md](CONFIG.md) - Configuration options
- [USAGE.md](USAGE.md) - Detailed examples
- [CONTRIBUTING.md](CONTRIBUTING.md) - How to contribute

## 📜 License

MIT - See [LICENSE](LICENSE)

## 🔗 Credits

Fork of [oskvr37/tiddl](https://github.com/oskvr37/tiddl)
