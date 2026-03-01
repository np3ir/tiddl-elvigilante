⚠️ **Disclaimer**: This application is for personal, educational, and archival purposes only. It is not affiliated with TIDAL. Users must ensure their use complies with TIDAL's Terms of Service and all applicable copyright laws. Downloaded content is for personal use only and may not be shared or redistributed. The developer assumes no responsibility for misuse.

---

# tiddl - TIDAL Downloader

**Modern Python 3.10+ Compatible Fork** - Download music and videos from TIDAL with complete metadata preservation and Unicode support.

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Fork](https://img.shields.io/badge/Fork-oskvr37/tiddl-lightgrey)

## 📝 About This Fork

This is an **independent fork** of the popular [oskvr37/tiddl](https://github.com/oskvr37/tiddl) project, with significant improvements focused on **Python 3.10+ compatibility, modern standards, and production-grade quality**.

**Key Improvements**:
- ✅ **Python 3.10 Compatible** (original requires 3.11+)
- ✅ **Clean English** codebase
- ✅ **Modern Architecture** - Refactored to layered design (CLI vs Core)
- ✅ **Type Safety** - Full PEP 563 annotations
- ✅ **Production Ready** - Complete testing and documentation

**Original Credits**: Thanks to [@oskvr37](https://github.com/oskvr37) for the original tiddl project that inspired this fork.

See [FORK.md](FORK.md) for detailed information about differences and why this fork exists.

---

## ✨ Features

- 🎵 **Download Tracks, Albums, Playlists** - Full support for all TIDAL content types
- 🎬 **Music Videos** - Download video content with metadata
- 📝 **Complete Metadata** - Artist, album, cover art, lyrics, genre, year, credits
- 🌍 **Unicode Support** - CJK (Chinese, Japanese, Korean), Arabic, Vietnamese, Devanagari
- 💾 **File Integrity** - Hash verification and corruption detection
- ⚡ **Async Downloading** - Concurrent downloads for improved performance
- 🔍 **Smart Quality Selection** - Automatic fallback for unavailable qualities
- 📦 **M3U8 Export** - Create playlists for media players
- 🔐 **Secure Auth** - Device flow authentication with credential storage
- 🛡️ **Cultural Preservation** - Respects original scripts and diacritics
- 🚀 **Production Ready** - Type hints, tests, error handling

## 🚀 Quick Start

### 1. Requirements

- **Python 3.10 or higher** (3.11, 3.12, 3.13 supported)
- **FFmpeg** installed and in PATH
- **TIDAL account** (free or paid)

### 2. Install

```bash
# Clone repository
git clone https://github.com/yourusername/tiddl.git
cd tiddl

# Create virtual environment (recommended)
python3.10 -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Authenticate

```bash
python -m cli auth
```
Follow the browser prompts to log in to TIDAL.

### 4. Download

```bash
# Single track
python -m cli download "https://tidal.com/browse/track/XXXXX"

# Album
python -m cli download "https://tidal.com/browse/album/XXXXX"

# Playlist
python -m cli download "https://tidal.com/browse/playlist/XXXXX"
```

## 📚 Documentation

- **[Installation Guide](README.md#installation)** - Detailed setup instructions
- **[Configuration Reference](CONFIG.md)** - All available settings
- **[Usage Guide](USAGE.md)** - Commands and examples
- **[Design Constraints](DESIGN_CONSTRAINTS.md)** - Architecture decisions

## 🔧 Installation (Detailed)

### Prerequisites

**Python 3.10+:**
```bash
# Check version
python3 --version  # Should be 3.10 or higher
```

**FFmpeg:**
```bash
# Check installation
ffmpeg -version

# Install if missing:
# Windows: winget install ffmpeg
# macOS: brew install ffmpeg
# Linux: sudo apt install ffmpeg
```

### Setup Steps

```bash
# 1. Clone
git clone https://github.com/yourusername/tiddl.git
cd tiddl

# 2. Virtual environment (optional but recommended)
python3.10 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify installation
python -m cli --help
```

## 💻 Usage Examples

```bash
# Authenticate
python -m cli auth

# Download track
python -m cli download "https://tidal.com/browse/track/123456"

# Download album
python -m cli download "https://tidal.com/browse/album/123456"

# Download with specific output directory
python -m cli download -o ~/Music/TIDAL "https://tidal.com/browse/album/123456"

# Download multiple from file
python -m cli download --file urls.txt

# Show track info
python -m cli info "https://tidal.com/browse/track/123456"

# Export playlist to M3U8
python -m cli export "https://tidal.com/browse/playlist/123456" -o playlist.m3u8

# Download all favorites
python -m cli download fav

# Download favorite albums only
python -m cli download fav --type album
```

## ⚙️ Configuration

Edit `~/.tiddl/config.toml`:

```toml
[download]
output_dir = "~/Downloads/TIDAL"
audio_quality = "LOSSLESS"  # LOSSLESS, HI_RES_LOSSLESS, HIGH, NORMAL, LOW
max_concurrent = 3
verify_integrity = true

[metadata]
save_cover = true
save_lyrics = true
folder_structure = "{artist}/{album}/{track}"
```

See [CONFIG.md](CONFIG.md) for complete options.

## 🆘 Troubleshooting

| Issue | Solution |
|-------|----------|
| "Python not found" | Install Python 3.10+ and add to PATH |
| "FFmpeg not found" | Install FFmpeg and add to PATH |
| Auth fails | Check internet, try `python -m cli auth --force` |
| Slow downloads | Increase `max_concurrent` in config |
| Files corrupted | Check disk space, disable `verify_integrity` temporarily |

## 📁 Project Structure

```
tiddl/
├── cli/                    # Command-line interface
│   ├── commands/          # Commands (download, auth, info, export)
│   ├── utils/             # CLI utilities and helpers
│   └── app.py             # CLI application entry point
├── core/                   # Core business logic (no CLI dependencies)
│   ├── api/               # TIDAL API integration
│   ├── auth/              # Authentication and token management
│   ├── metadata/          # Metadata processing (track, cover, video)
│   └── utils/             # Core utilities (download, format, strings, etc.)
├── tests/                 # Test suite
├── README.md              # This file
├── CONFIG.md              # Configuration guide
├── USAGE.md               # Detailed usage examples
├── DESIGN_CONSTRAINTS.md  # Architecture decisions
├── pyproject.toml         # Python project metadata
├── requirements.txt       # Python dependencies
└── .gitignore            # Git ignore patterns
```

## 🛠️ Development

```bash
# Setup dev environment
python3.10 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest mypy black ruff

# Run tests
pytest tests/

# Type checking
mypy . --strict

# Format code
black cli/ core/ tests/
ruff check cli/ core/ tests/
```

## 🌟 Key Features

### Advanced Metadata
- Preserves complete ID3/MP4 tags
- Genre and year formatting
- Lyrics storage
- Album art and cover images

### Robust Filename Handling
- Preserves Unicode characters (CJK, Arabic, etc.)
- Converts forbidden characters safely
- Respects filesystem limits
- Prevents ghost files (Windows)

### Performance
- Directory caching for fast verification
- Concurrent downloads
- Smart retry logic
- Rate limit handling

### Quality Selection
- LOSSLESS (FLAC, 1411 kbps)
- HI_RES_LOSSLESS (up to 2304 kbps)
- HIGH (320 kbps AAC)
- NORMAL (96 kbps AAC)
- LOW (32 kbps AAC)

## 📋 Requirements Compatibility

- Python: 3.10, 3.11, 3.12, 3.13+
- FFmpeg: 4.0+
- OS: Windows, macOS, Linux

## 📄 License

MIT License - See [LICENSE](LICENSE) file

## 🤝 Contributing

Contributions welcome! Please:

1. Fork repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push branch (`git push origin feature/amazing-feature`)
5. Open Pull Request

## 📞 Support

- 🐛 **Issues**: [GitHub Issues](https://github.com/yourusername/tiddl/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/yourusername/tiddl/discussions)
- 📖 **Docs**: [CONFIG.md](CONFIG.md), [USAGE.md](USAGE.md)

## 🙏 Acknowledgments

Built with:
- Python 3.10+
- Pydantic for data validation
- Typer for CLI framework
- Rich for terminal output
- Mutagen for audio metadata

---

**Made with ❤️ for music lovers everywhere**
