# 🎵 tiddl - TIDAL Downloader

**Production-Ready TIDAL Music Downloader** | Python 3.10+ Compatible | Pydantic v1 Optimized

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Fork of oskvr37/tiddl](https://img.shields.io/badge/Fork%20of-oskvr37%2Ftiddl-lightgrey)](https://github.com/oskvr37/tiddl)
[![Status: Production](https://img.shields.io/badge/Status-Production%20Ready-green)](https://github.com)

---

## ⚠️ Disclaimer

This application is for personal, educational, and archival purposes only. It is not affiliated with TIDAL. Users must ensure their use complies with TIDAL's Terms of Service and all applicable copyright laws. Downloaded content is for personal use only.

---

## 🚀 Quick Start

### Installation (Easiest)
```bash
pip install git+https://github.com/Np3ir/tiddl-elvigilante.git
```

### First Use
```bash
# Authenticate with TIDAL
tiddl auth

# Download an album
tiddl download url https://tidal.com/album/497662013

# Download a track
tiddl download url https://tidal.com/track/123456789
```

---

## ✨ Features

- 🎵 **Download Tracks, Albums, Playlists** - All TIDAL content types
- 🎬 **Music Videos** - Download with full metadata
- 📝 **Complete Metadata** - Artist, album, cover, lyrics, credits
- 🌍 **Unicode Support** - CJK, Arabic, Vietnamese, Devanagari
- 💾 **File Integrity** - Hash verification & corruption detection
- ⚡ **Async Downloads** - Concurrent multi-threaded downloads
- 🔍 **Smart Quality** - Automatic fallback for unavailable qualities
- 📦 **M3U8 Export** - Create playlists for media players
- 🔐 **Secure Auth** - Device flow authentication
- 🚀 **Production Grade** - Type hints, comprehensive tests, error handling

---

## 📋 Requirements

- **Python 3.10+** (3.11, 3.12, 3.13, 3.14+)
- **FFmpeg** - For audio/video processing
- **TIDAL Account** - Free or Premium

---

## 🔧 Installation

### From GitHub (Recommended)
```bash
pip install git+https://github.com/Np3ir/tiddl-elvigilante.git
```

### Local Development
```bash
git clone https://github.com/Np3ir/tiddl-elvigilante.git
cd tiddl
pip install -e .
```

### Install FFmpeg

**Windows:**
```bash
winget install ffmpeg
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

---

## 🎯 Usage

### Basic Commands

```bash
# Authenticate
tiddl auth

# Download track
tiddl download url https://tidal.com/track/123456789

# Download album
tiddl download url https://tidal.com/album/497662013

# Download playlist
tiddl download url https://tidal.com/playlist/abc123xyz

# Download your favorites
tiddl download fav

# Get information about a track
tiddl info url https://tidal.com/track/123456789

# Export playlist as M3U8
tiddl export url https://tidal.com/playlist/xyz -o my_playlist.m3u8
```

### Options

```bash
# Use maximum quality
tiddl download url --track-quality max https://...

# Specify download location
tiddl download url --download-path "D:/Music" https://...

# Custom naming template
tiddl download url --template "{album.artist}/{album.title}/{item.title}" https://...

# Debug mode
tiddl download url --debug https://...
```

See [USAGE.md](USAGE.md) for complete examples.

---

## ⚙️ Configuration

Configuration is stored in: `~/.tiddl/config.toml`

**Windows:** `C:\Users\YourName\.tiddl\config.toml`  
**Linux/Mac:** `~/.tiddl/config.toml`

See [CONFIG.md](CONFIG.md) for all available options.

Example config:
```toml
[download]
track_quality = "max"
video_quality = "fhd"
download_path = "~/Music/tiddl"
threads_count = 4

[metadata]
enable = true
lyrics = true
save_lyrics = true
cover = true
```

---

## 📚 Documentation

### 📖 Getting Started
- **[COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)** ⭐ **START HERE** - Complete command and placeholder reference (734 lines)
- **[QUICK_INDEX.md](QUICK_INDEX.md)** - Quick index and navigation guide

### 📋 Detailed Guides
- **[USAGE.md](USAGE.md)** - Practical command examples and scenarios
- **[CONFIG.md](CONFIG.md)** - Configuration reference with all options
- **[FORK.md](FORK.md)** - About this fork and improvements over original

### 🤝 Community
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and release notes
- **[DESIGN_CONSTRAINTS.md](DESIGN_CONSTRAINTS.md)** - Design principles and architecture

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick start:
```bash
# Fork and clone
git clone https://github.com/Np3ir/tiddl-elvigilante.git
cd tiddl

# Create feature branch
git checkout -b feature/my-feature

# Make changes
git commit -m "feat: add my feature"
git push origin feature/my-feature
```

---

## 📜 License

MIT License - See [LICENSE](LICENSE) file for details.

---

## 🔗 Links

- **This Fork:** https://github.com/Np3ir/tiddl-elvigilante
- **Original Project:** https://github.com/oskvr37/tiddl
- **TIDAL:** https://tidal.com
- **Python:** https://python.org
- **FFmpeg:** https://ffmpeg.org

---

## 🙏 Credits

Fork of [oskvr37/tiddl](https://github.com/oskvr37/tiddl)

This fork extends the original with:
- ✅ Python 3.10-3.12 support (original requires 3.13+)
- ✅ Pydantic v1 compatibility for Python 3.14
- ✅ Enhanced documentation
- ✅ Modular architecture
- ✅ Production-grade quality

---

## ⚠️ Legal Notice

This tool respects TIDAL's ToS and copyright laws. Users are responsible for ensuring their use is legal in their jurisdiction. The developer assumes no responsibility for misuse of this tool.

---

**Version:** 1.0.1
**Status:** Production Ready ✅
**Last Updated:** March 4, 2026
