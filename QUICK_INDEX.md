# 📚 Quick Index - Command & Placeholder Reference

## 📄 File: `COMPLETE_COMMAND_REFERENCE.md`

**Size**: 17 KB | **Lines**: 734 | **Format**: 100% Markdown

---

## 🎯 Document Contents

### 1️⃣ MAIN COMMANDS (Explained for Everyone)

```
✅ tiddl auth          - Authentication
   ├── login           - Sign in
   └── logout          - Sign out

✅ tiddl download      - Download
   ├── url             - Download by link
   └── fav             - Download favorites

✅ tiddl info          - Get information

✅ tiddl export        - Export to M3U8
```

**Each command includes:**
- Exact syntax
- What it does (simple words)
- Real usage examples
- Requirements

---

### 2️⃣ SUPPORTED URLS

```bash
tiddl download url https://tidal.com/track/123456789      ✓
tiddl download url https://tidal.com/album/497662013      ✓
tiddl download url https://tidal.com/playlist/abc123xyz   ✓
tiddl download url https://tidal.com/artist/789123456     ✓
tiddl download url https://tidal.com/mix/mixed123xyz      ✓
```

---

### 3️⃣ ALL OPTIONS (16 Options Documented)

| Option | Short | Example | Explanation |
|--------|-------|---------|-------------|
| `--track-quality` | `-q` | `max`, `high`, `normal`, `low` | Audio quality |
| `--video-quality` | `-vq` | `fhd`, `hd`, `sd` | Video quality |
| `--no-skip` | `-ns` | - | Re-download files |
| `--rewrite-metadata` | `-r` | - | Update metadata |
| `--threads-count` | `-t` | `8` | Download threads |
| `--path` | `-p` | `D:/Music` | Download folder |
| `--template` | - | `{artist}/{album}/{title}` | Custom naming |
| And more... | | | |

---

### 4️⃣ PLACEHOLDERS - ALL EXPLAINED

#### **For Songs (item)**
```
{item.id}                      → 123456789
{item.title}                   → "Come Together"
{item.number}                  → 1, 2, 3...
{item.artist}                  → "The Beatles"
{item.artists_with_features}   → "Artist feat. Guest"
{item.releaseDate:%Y}          → 1969
{item.explicit}                → [E] if explicit
```

#### **For Albums (album)**
```
{album.id}                     → 497662013
{album.title}                  → "Abbey Road"
{album.artist}                 → "The Beatles"
{album.date:%Y}                → 1969
{album.release}                → "ALBUM", "SINGLE", "EP"
{album.master}                 → "Master" if master quality
```

#### **For Playlists (playlist)**
```
{playlist.title}               → "My Playlist"
{playlist.uuid}                → abc123xyz
{playlist.index}               → 1, 2, 3...
{playlist.created}             → Creation date
{playlist.updated}             → Last update
```

#### **Special**
```
{artist_initials}              → "T" (group by letter)
{now:%Y}                       → 2026 (current year)
{quality}                      → "max", "high"...
```

---

### 5️⃣ DATE FORMATS (13 Variants)

```bash
{album.date}                   # 2023-01-15 (ISO)
{album.date:%Y}                # 2023 (year)
{album.date:%Y-%m-%d}          # 2023-01-15 (complete)
{album.date:%B}                # January (full month)
{album.date:%b}                # Jan (short month)
{album.date:%d}                # 15 (day)
{album.date:%m/%d/%Y}          # 01/15/2023 (american)
{album.date:%d/%m/%Y}          # 15/01/2023 (european)
{album.date:%Y-%m-%d %H:%M}    # 2023-01-15 14:30 (with time)
```

---

### 6️⃣ PRACTICAL EXAMPLES (8 Real Examples)

```bash
# Example 1: Simple
{album.artist}/{album.title}/{item.title}
→ The Beatles/Abbey Road/Come Together.flac

# Example 2: With numbers
{album.artist}/{album.title}/{item.number}. {item.title}
→ The Beatles/Abbey Road/01. Come Together.flac

# Example 3: With year
{album.artist}/({album.date:%Y}) {album.title}/{item.number}. {item.title}
→ The Beatles/(1969) Abbey Road/01. Come Together.flac

# Example 4: Group by letter
{artist_initials}/{album.artist}/{album.title}/{item.title}
→ T/The Beatles/Abbey Road/Come Together.flac

# Example 5: With featuring artists
{album.artist}/{album.title}/{item.number}. {item.artists_with_features}
→ Drake/Certified Lover Boy/01. Drake feat. 21 Savage.flac

# Example 6: With version
{album.artist}/{album.title}/{item.number}. {item.title} {item.version}
→ The Weeknd/Dawn FM/01. Gasoline (Remix).flac

# Example 7: Artist only
{album.artist}/{item.title}
→ The Beatles/Come Together.flac

# Example 8: All artists
{album.artists}/{album.title}/{item.number}. {item.title}
→ The Beatles, Yoko Ono/Abbey Road/01. Come Together.flac
```

---

### 7️⃣ COMMON USE CASES (8 Cases)

```bash
1. "Limited space"
   → --track-quality normal --threads-count 2

2. "Maximum quality"
   → --track-quality max --path "D:/HighQuality"

3. "Organize by year"
   → Config: {album.date:%Y}/{album.artist}/{album.title}/{item.title}

4. "Change folder quickly"
   → --path "E:/Backup"

5. "Don't re-download"
   → Use skip_existing = true (default)

6. "Download fast"
   → --track-quality high --threads-count 8

7. "Update metadata"
   → --rewrite-metadata --no-skip

8. "Custom naming"
   → --template "{artist}/{title}"
```

---

### 8️⃣ TROUBLESHOOTING

- What is --debug?
- Why don't some placeholders work?
- How do I use network paths?

---

### 9️⃣ QUICK REFERENCE (Copy & Paste)

```bash
# AUTHENTICATION
tiddl auth login
tiddl auth logout

# DOWNLOAD
tiddl download url https://tidal.com/album/123
tiddl download fav

# INFORMATION
tiddl info url https://tidal.com/album/123

# EXPORT
tiddl export url https://tidal.com/playlist/xyz -o file.m3u8

# OPTIONS
--track-quality max
--path "D:/Music"
--threads-count 8
--template "{artist}/{album}/{title}"

# VARIABLES
{item.title}
{album.artist}
{album.date:%Y}
{item.number}
```

---

## 📊 Document Statistics

| Metric | Value |
|--------|-------|
| Lines | 734 |
| Size | 17 KB |
| Commands explained | 4 main |
| Subcommands | 2 |
| Options documented | 16 |
| Item placeholders | 15 |
| Album placeholders | 10 |
| Playlist placeholders | 5 |
| Date formats | 13 |
| Practical examples | 8 |
| Use cases | 8 |
| URL types | 5 |

---

## 🎯 When to Use Each Section

| Section | Use when... |
|---------|------------|
| Commands | Need to know WHAT commands exist |
| Options | Need to adjust behavior |
| Placeholders | Want custom folder structure |
| Date formats | Want specific dates in names |
| Examples | Need to copy a pattern |
| Use cases | Have a specific situation |
| Quick reference | Need to copy and paste |

---

## 💡 Usage Tips

1. **Start simple**: Use basic examples first
2. **Check use cases**: Your situation is probably there
3. **Copy and adapt**: No need to memorize
4. **Use --debug**: If something fails, enable debug
5. **Use quick reference**: For frequent commands

---

## 📚 Related Files

```
├── COMPLETE_COMMAND_REFERENCE.md ← This (complete)
├── README.md
├── USAGE.md
├── CONFIG.md
├── FORK.md
├── CONTRIBUTING.md
├── CHANGELOG.md
└── DESIGN_CONSTRAINTS.md
```

---

## 🚀 How to Use This Document

### On Your Computer
```bash
# Download the file
# Open in your text editor
# Use Ctrl+F to search keywords
```

### On GitHub
```bash
# Upload to your repo
# GitHub renders Markdown automatically
# Users can read it easily
```

### In Your Wiki
```bash
# Copy content to your platform
# Works in Notion, Confluence, etc
```

---

## ✅ Reading Checklist

- [ ] Read Main Commands
- [ ] Know the 5 supported URL types
- [ ] Understand the 16 main options
- [ ] Know how to use placeholders
- [ ] Understand date formatting
- [ ] Review practical examples
- [ ] My use case is in "Common Use Cases"
- [ ] Saved the quick reference

---

**Ready to use tiddl!** 🎵
