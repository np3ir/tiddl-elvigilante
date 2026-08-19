# 🎵 tiddl - TIDAL Downloader

> [!WARNING]
> **This app is for personal, educational, and archival purposes only.** It is not affiliated with Tidal. Users must ensure their use complies with Tidal's terms of service and all applicable local copyright laws. Downloaded content is for personal use and may not be shared or redistributed. The developer assumes no responsibility for misuse of this app.

**Production-Ready TIDAL Music Downloader** | Python 3.10+ Compatible | Pydantic v1 Optimized

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Fork of oskvr37/tiddl](https://img.shields.io/badge/Fork%20of-oskvr37%2Ftiddl-lightgrey)](https://github.com/oskvr37/tiddl)
[![Status: Production](https://img.shields.io/badge/Status-Production%20Ready-green)](https://github.com)

📘 **[Guía en español / Spanish tutorial →](TUTORIAL_ES.md)**
📖 **[Full documentation wiki (EN/ES) →](https://github.com/np3ir/tiddl-elvigilante/wiki)**

---

## ⚠️ Disclaimer

This application is for personal, educational, and archival purposes only. It is not affiliated with TIDAL. Users must ensure their use complies with TIDAL's Terms of Service and all applicable copyright laws. Downloaded content is for personal use only.

---

## 🚀 Quick Start

### Installation (Easiest)
```bash
pip install git+https://github.com/np3ir/tiddl-elvigilante
```
### For force update 
```bash
pip install --upgrade --force-reinstall "git+https://github.com/np3ir/tiddl-elvigilante.git"
```

### First Use
```bash
# Authenticate with TIDAL
tiddl auth login

# Download an album
tiddl download url https://tidal.com/album/497662013

# Download a track
tiddl download url https://tidal.com/track/123456789
```

> **⚠️ Hybrid login — you'll now see 2 authorizations.**
> `tiddl auth login` sets up **two** device-flow tokens to reach maximum quality without keeping any window open:
> 1. **Step 1/2 — HiRes:** client entitled to `HI_RES_LOSSLESS` (24-bit).
> 2. **Step 2/2 — Fallback:** TV client that serves `LOSSLESS` (16-bit) on tracks where the primary would drop to 320 kbps.
>
> The browser opens **once for each** (approve both codes, first time only). Both tokens then **auto-refresh** — no re-login, no windows to keep open. Result: **24-bit on HiRes tracks + 16-bit LOSSLESS on the rest, never lossy.**
>
> Reconfigure only the second token with `tiddl auth login-fallback`; sign out of both with `tiddl auth logout`.

---

## 🌍 Unicode-First Filenames

Most TIDAL downloaders replace special characters in filenames with underscores:

```
Bad Bunny / Kendrick Lamar  →  Bad Bunny _ Kendrick Lamar.flac
Rosalía: MOTOMAMI          →  Rosalia_ MOTOMAMI.flac
```

tiddl substitutes every Windows-forbidden character with its **visually identical fullwidth Unicode equivalent** — valid on every filesystem (Windows, Linux, macOS, NAS):

```
Bad Bunny ／ Kendrick Lamar  →  Bad Bunny ／ Kendrick Lamar.flac
Rosalía： MOTOMAMI           →  Rosalía： MOTOMAMI.flac
```

All 9 forbidden characters are covered:

| Character | Other tools | tiddl |
|---|---|---|
| `/` slash | `_` | `／` U+FF0F |
| `\` backslash | `_` | `＼` U+FF3C |
| `:` colon | `_` | `：` U+FF1A |
| `*` asterisk | `_` | `＊` U+FF0A |
| `?` question mark | `_` | `？` U+FF1F |
| `"` quotation mark | `_` | `＂` U+FF02 |
| `<` less-than | `_` | `＜` U+FF1C |
| `>` greater-than | `_` | `＞` U+FF1E |
| `\|` pipe | `_` | `｜` U+FF5C |

At scale — tens of thousands of albums — this means your library reflects the actual artist and album names exactly as TIDAL has them. Collaborations, subtitles, and special characters are preserved, not destroyed.

---

## ✨ Features

- 🎵 **Download Tracks, Albums, Playlists** - All TIDAL content types
- 🎬 **Music Videos** - Download with full metadata
- 📝 **Complete Metadata** - Artist, album, cover, lyrics, credits
- 🌍 **Unicode Support** - CJK, Arabic, Vietnamese, Devanagari
- 💾 **File Integrity** - Hash verification & corruption detection
- 🔒 **Destination-Volume Identity** (opt-in) - Refuse to write if a configured NAS/USB destination is unmounted and silently falls back to a same-named local folder — see the **[Destination Safety Guide (EN/ES)](DESTINATION_SAFETY.md)**
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
pip install git+https://github.com/np3ir/tiddl-elvigilante
```

### Local Development
```bash
git clone https://github.com/np3ir/tiddl-elvigilante.git
cd tiddl-elvigilante
pip install -e .
```

### Android (Termux)

`pip install git+…` needs the `git` command available, and Android does not ship it —
that is why you may see an error about `git` not being recognized. Use **Termux**:

1. Install Termux from **[F-Droid](https://f-droid.org/packages/com.termux/)** (the Play Store build is outdated).
2. Then run:

```bash
pkg update && pkg upgrade -y
pkg install -y python git ffmpeg rust clang
pip install git+https://github.com/np3ir/tiddl-elvigilante
```

`ffmpeg` is required for audio processing; `rust`/`clang` let the native dependencies
compile on Android. After that, use `tiddl` exactly as on desktop.

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
tiddl auth login

# Download track
tiddl download url https://tidal.com/track/123456789

# Download album
tiddl download url https://tidal.com/album/497662013

# Download playlist
tiddl download url https://tidal.com/playlist/abc123xyz

# Expand a playlist instead of downloading it as a playlist:
tiddl download --albums url https://tidal.com/playlist/abc123xyz   # full album of every track
tiddl download --artists url https://tidal.com/playlist/abc123xyz  # full discography of every credited artist
tiddl download --tracks url https://tidal.com/playlist/abc123xyz   # each track standalone (track template/folders)

# Download your favorites
tiddl download fav

# Get information about a track
tiddl info url https://tidal.com/track/123456789
```

> **M3U8 playlists**: there's no standalone `export` command — set `[m3u] save = true` in `config.toml` (see [CONFIG.md](CONFIG.md)) and an `.m3u8` file is generated automatically whenever you download an album/playlist/mix.

### Options

```bash
# Use maximum quality
tiddl download url --track-quality max https://...

# Specify download location
tiddl download url --path "D:/Music" https://...

# Custom naming template
tiddl download url --template "{album.artist}/{album.title}/{item.title}" https://...

# Debug mode (global flag — goes before the subcommand)
tiddl --debug download url https://...
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

[templates]
default = "{album.artist}/{album.title}/{item.number}. {item.title}"
artist_separator = " / "
```

---

## 📚 Documentation

### 📖 Getting Started
- **[COMPLETE_COMMAND_REFERENCE.md](COMPLETE_COMMAND_REFERENCE.md)** ⭐ **START HERE** - Complete command and placeholder reference (734 lines)
- **[PLACEHOLDERS.md](PLACEHOLDERS.md)** - Complete template placeholder reference with formatting rules and examples
- **[PLACEHOLDERS_ES.md](PLACEHOLDERS_ES.md)** 🇪🇸 - Referencia completa de placeholders para plantillas, con formatos y ejemplos
- **[QUICK_INDEX.md](QUICK_INDEX.md)** - Quick index and navigation guide
- **[TUTORIAL_ES.md](TUTORIAL_ES.md)** 🇪🇸 - Guía paso a paso en español (instalación y configuración)

### 📋 Detailed Guides
- **[USAGE.md](USAGE.md)** - Practical command examples and scenarios
- **[CONFIG.md](CONFIG.md)** - Configuration reference with all options
- **[DESTINATION_SAFETY.md](DESTINATION_SAFETY.md)** 🔒 - Protect NAS, USB and network destinations (English/Español)
- **[FORK.md](FORK.md)** - About this fork and improvements over original

### 🤝 Community
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - How to contribute
- **[CHANGELOG.md](CHANGELOG.md)** - Version history and release notes
- **[DESIGN_CONSTRAINTS.md](DESIGN_CONSTRAINTS.md)** - Design principles and architecture

---

## 🔄 Filename Creation vs Other TIDAL Downloaders

The main difference between tiddl and other TIDAL downloaders is how filenames are created when artist or album names contain special characters.

Most tools use aggressive sanitization — they replace any character that is invalid on Windows (`/ : * ? " < > |`) with an underscore or remove it entirely:

```
Bad Bunny / Kendrick Lamar  →  Bad Bunny _ Kendrick Lamar.flac   ❌ information lost
A$AP Rocky: Peso            →  A_AP Rocky_ Peso.flac              ❌ information lost
```

tiddl substitutes those characters with **visually identical Unicode fullwidth equivalents** that are valid on every filesystem (Windows, Linux, macOS, NAS):

```
Bad Bunny ／ Kendrick Lamar  →  Bad Bunny ／ Kendrick Lamar.flac  ✅ preserved
A$AP Rocky： Peso             →  A$AP Rocky： Peso.flac             ✅ preserved
```

All 9 Windows-forbidden characters are covered — nothing is lost:

| Character | Other tools | tiddl | Unicode |
|---|---|---|---|
| `/` slash | `_` | `／` | U+FF0F FULLWIDTH SOLIDUS |
| `\` backslash | `_` | `＼` | U+FF3C FULLWIDTH REVERSE SOLIDUS |
| `:` colon | `_` | `：` | U+FF1A FULLWIDTH COLON |
| `*` asterisk | `_` | `＊` | U+FF0A FULLWIDTH ASTERISK |
| `?` question mark | `_` | `？` | U+FF1F FULLWIDTH QUESTION MARK |
| `"` quotation mark | `_` | `＂` | U+FF02 FULLWIDTH QUOTATION MARK |
| `<` less-than | `_` | `＜` | U+FF1C FULLWIDTH LESS-THAN SIGN |
| `>` greater-than | `_` | `＞` | U+FF1E FULLWIDTH GREATER-THAN SIGN |
| `\|` pipe | `_` | `｜` | U+FF5C FULLWIDTH VERTICAL LINE |

This is controlled by the `artist_separator` config option, which defaults to `／` and applies to all collaborations (`Artist A ／ Artist B`). The result is a library where every filename is faithful to the original TIDAL metadata — especially important at scale with tens of thousands of albums.

---

## 🤝 Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

Quick start:
```bash
# Fork on GitHub, then clone your fork
git clone https://github.com/<your-username>/tiddl-elvigilante.git
cd tiddl-elvigilante

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

- **This Fork:** https://github.com/np3ir/tiddl-elvigilante
- **Original Project:** https://github.com/oskvr37/tiddl
- **TIDAL:** https://tidal.com
- **Python:** https://python.org
- **FFmpeg:** https://ffmpeg.org

---

## 🙏 Credits

Fork of [oskvr37/tiddl](https://github.com/oskvr37/tiddl)

This fork extends the original with:
- ✅ Python 3.10-3.14+ support (original requires 3.13+)
- ✅ Pydantic v1 compatibility
- ✅ Configurable `artist_separator` for filenames and metadata tags
- ✅ Correct pip packaging (`tiddl.cli` / `tiddl.core` namespace)
- ✅ Enhanced documentation
- ✅ Modular architecture
- ✅ Production-grade quality

---

## ⚠️ Legal Notice

This tool respects TIDAL's ToS and copyright laws. Users are responsible for ensuring their use is legal in their jurisdiction. The developer assumes no responsibility for misuse of this tool.

---

**Version:** 1.2.1
**Status:** Production Ready ✅
**Last Updated:** August 19, 2026
