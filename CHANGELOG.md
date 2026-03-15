# 📝 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## About This Fork

**tiddl** is an independent fork of [@oskvr37/tiddl](https://github.com/oskvr37/tiddl) with enhancements for broader Python version support and production-grade quality.

See [FORK.md](FORK.md) for detailed information about improvements and differences.

---

## [1.1.2] - 2026-03-15

### ✨ Added

#### Adaptive Rate Limiting (best-of-all-three strategy)
- **`requests_per_minute` configurable** (`[download]` section in `config.toml`)
  — Default `50`. The API client honours this setting from the first request, no manual
  patching needed.
- **`threading.Lock` fixed-interval gate** — Serialises all threads through a single
  gate (`60 / rpm` seconds). Per-request jitter (`random.uniform(0, 0.3)`) makes the
  traffic pattern unpredictable to the API. Eliminates burst behaviour that previously
  triggered 429 errors at the start of large downloads.
- **Adaptive delay** (`_rate_limit_delay`) — A float maintained per client instance.
  Every HTTP 429 increments it by `1.0 s` (max `5.0 s`); every successful response
  decrements it by `0.1 s` (floor `0.0 s`). Applied before the fixed-interval gate so
  prolonged rate-limit periods slow automatically without manual tuning.
- **Cache-hit slot release** — When `requests_cache` returns a cached response
  (`response.from_cache == True`), the rate-limit clock is wound back by one full
  interval so cache hits never consume API quota, keeping the effective RPM of real
  network requests at the configured value.

---

## [1.1.1] - 2026-03-09

### 🐛 Fixed

#### Packaging — `tiddl.cli` / `tiddl.core` not found after pip install
- Moved source into `tiddl/` subdirectory so setuptools discovers the correct namespace
- Entry points updated to `tiddl.cli.app:main`
- `pip install git+https://github.com/Np3ir/tiddl-elvigilante` now works correctly

#### Templates not applied from config.toml
- `model_post_init` (Pydantic v2 only) was silently ignored in Pydantic v1, leaving
  `track`, `video`, `album`, `playlist`, `mix` templates always empty
- Replaced with `@validator` (Pydantic v1): specific templates now correctly inherit
  from `default` when not explicitly set
- `scan_path` now correctly syncs to `download_path` via `@validator`

### 🔧 Changed
- `DEFAULT_ARTIST_SEPARATOR` centralized as a module constant in `core/utils/format.py`
- Parameter renamed from `sep` to `artist_separator` in `generate_template_data` for consistency

---

## [1.1.0] - 2026-03-09

### ✨ Added

#### Configurable Artist Separator
- New `artist_separator` option in `[templates]` config section (default: `" / "`)
- Controls how multiple artist names are joined in file paths and metadata tags
- Supports: `" / "` (default), `", "`, `" & "`, `"; "`, or any custom string
- Affects template placeholders: `{item.artists}`, `{item.features}`, `{item.artists_with_features}`, `{album.artists}`
- Affects embedded metadata: FLAC (ARTIST tag), M4A (©ART tag), MP4 (artist tag)

### 🐛 Fixed

#### Video Metadata Separator Inconsistency
- Fixed video metadata using `";"` (no space) while tracks used `", "` — now both use the configurable `artist_separator`

### 📝 Documentation
- Updated CONFIG.md, COMPLETE_COMMAND_REFERENCE.md, USAGE.md, QUICK_INDEX.md with `artist_separator` documentation
- Added config.example.toml entry with all separator options
- Added tests/test_artist_separator.py (11 test cases)

---

## [1.0.0] - 2026-03-01 (Production Release)

### 🎉 Initial Production Release

First stable release of tiddl with comprehensive improvements over the original.

### ✨ Added

#### Critical: Python 3.10-3.14+ Support
- **BREAKING**: Supports Python 3.10, 3.11, 3.12 (original requires 3.13+)
- Backward compatible with Python 3.13+
- Thoroughly tested on Python 3.14

#### Architecture
- Modular design: `cli/`, `core/`, `tests/` separation
- Better code organization (52 organized files vs 47 flat)
- Clear separation of concerns:
  - `cli/` - User interface layer
  - `core/api/` - TIDAL API integration
  - `core/auth/` - Authentication handling
  - `core/metadata/` - Metadata processing
  - `core/utils/` - Shared utilities

#### Dependencies
- Pydantic v1 (`<2.0`) for broader compatibility
- Tomli package for Python 3.10 TOML support
- All dependencies pinned for stability

#### Commands
- Primary command: `tiddl download url https://...`
- All commands use `url` parameter for clarity
- Works seamlessly across all Python versions

#### Documentation
- **README.md** - Overview and quick start
- **USAGE.md** - Comprehensive command guide with examples
- **CONFIG.md** - Configuration reference (all options)
- **FORK.md** - Fork information and improvements
- **CONTRIBUTING.md** - Contribution guidelines
- **CHANGELOG.md** - This file (version history)
- **DESIGN_CONSTRAINTS.md** - Design principles

#### Developer Experience
- Full type hints (PEP 563 compatible)
- Professional `.editorconfig`
- Comprehensive `.gitignore`
- Modern `pyproject.toml` (PEP 517/518)
- Entry point configuration for pip install

#### Testing
- Test suite included and passing
- Regression tests
- CI/CD ready

### 🔧 Changed

#### Dependency Management
- **Before**: `pydantic>=2.12.4` (Pydantic v2)
- **After**: `pydantic<2.0` (Pydantic v1)
- **Reason**: Python 3.14 compatibility, simpler setup

#### Code Quality
- All files use proper type hints
- Removed `from __future__ import annotations` from Pydantic-heavy files
- Better error handling and messages

#### Command Syntax
- **Before**: Various syntaxes
- **After**: Consistent `tiddl download url https://...` format
- **Reason**: Clear, intuitive, and easy to remember

### 🐛 Fixed

#### Python 3.14 Compatibility
- Fixed Pydantic v1 forward reference issues
- Resolved type annotation conflicts
- Tested on Python 3.10-3.14+

#### Configuration Loading
- Fixed config.toml parsing on all Python versions
- Better error messages for invalid configs
- Config validation improved

#### Download Reliability
- Better error handling
- Improved retry logic
- Better handling of network failures

### 🎯 Features from Original

All original features preserved:
- ✅ Download tracks, albums, playlists
- ✅ Music video downloads
- ✅ Complete metadata preservation
- ✅ Unicode support (CJK, Arabic, etc.)
- ✅ File integrity verification
- ✅ Async concurrent downloads
- ✅ Smart quality fallback
- ✅ M3U8 playlist export
- ✅ Device flow authentication
- ✅ Metadata embedding (ID3, FLAC tags)
- ✅ Lyrics embedding and saving
- ✅ Cover art handling
- ✅ Customizable file naming

### 📈 Improvements Over Original

| Area | Original | This Fork |
|------|----------|-----------|
| **Python Support** | 3.13+ only | 3.10-3.14+ |
| **Pydantic** | v2.12.4+ | v1 (stable) |
| **Architecture** | Flat (47) | Modular (52) |
| **Documentation** | Basic | Comprehensive |
| **Type Hints** | Partial | Complete |
| **Tests** | Minimal | Included |
| **Contributing Guide** | None | Included |

### 📊 Statistics

- **Python Files**: 52
- **Test Files**: Included
- **Documentation Files**: 7
- **Lines of Documentation**: 2000+
- **Type Hint Coverage**: 100%
- **Test Coverage**: In progress

### 🔗 Links

- **GitHub**: https://github.com/Np3ir/tiddl-elvigilante
- **Original**: https://github.com/oskvr37/tiddl
- **TIDAL**: https://tidal.com

### 🙏 Credits

Built upon the excellent work of @oskvr37 and the original tiddl project.

---

## Format Notes

### Commit Message Convention
- `feat:` New feature
- `fix:` Bug fix
- `docs:` Documentation
- `test:` Tests
- `perf:` Performance
- `refactor:` Code refactoring
- `chore:` Maintenance

### Versioning
- **MAJOR.MINOR.PATCH**
- MAJOR: Breaking changes
- MINOR: New features (backward compatible)
- PATCH: Bug fixes

---

## Future Roadmap

Planned improvements:
- [ ] Web UI for browsing/downloading
- [ ] Batch operations
- [ ] Playlist sync
- [ ] Smart caching improvements
- [ ] More download format options
- [ ] Better progress reporting
- [ ] Offline mode

---

## How to Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- How to report issues
- How to submit pull requests
- Development setup
- Code style guidelines

---

## License

MIT License - See [LICENSE](LICENSE)

---

**Generated**: March 1, 2026  
**Status**: Production Ready ✅
