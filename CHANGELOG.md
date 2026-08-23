# 📝 Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## About This Fork

**tiddl** is an independent fork of [@oskvr37/tiddl](https://github.com/oskvr37/tiddl) with enhancements for broader Python version support and production-grade quality.

See [FORK.md](FORK.md) for detailed information about improvements and differences.

---

## [Unreleased]

### Added

- **Fidelity quality cascade with Dolby Atmos as a rung.** `-q` now names the
  STARTING rung of a fixed ladder `max > high > atmos > normal > low`; each track
  is taken at the first rung from there DOWN that it actually offers. This fixes
  a real trap: TIDAL serves an AAC (`.m4a`) stream for an Atmos-flagged track at
  the LOSSLESS tier but the real FLAC only at HI_RES, so a plain `-q high` run
  used to yield degraded AAC even when a hi-res FLAC existed. **FLAC is preferred
  over Atmos:** from a FLAC start (`high`/`max`) the cascade tries BOTH FLAC rungs
  before Atmos, so `-q high` on an Atmos track (which has no 16-bit FLAC) climbs
  to the 24-bit `max` FLAC instead of dropping to Atmos — most users want any FLAC
  over Atmos. `-q atmos` takes Dolby Atmos first for those who want it. (Because a
  FLAC start may now need the HiRes client for an Atmos track's `max` FLAC,
  `hires_client="auto"` uses the HiRes client for `-q high` too; the run-wide 429
  breaker keeps that safe.) Non-Atmos tracks resolve to the same tier as before.
  The "Dolby Atmos" download label now
  reflects the stream actually delivered, so a track's FLAC is no longer
  mislabelled Atmos. New pure module `tiddl/core/quality_cascade.py`.
- `--resume`: skip resources already fully processed in a prior run of the same
  job (same links + options) **before any API call**, so a run interrupted by a
  rate-limit stop or Ctrl-C continues cheaply instead of re-enumerating every
  artist. Opt-in and off by default; a resource is recorded only on a clean,
  error-free completion, and the checkpoint is trusted over the filesystem (run
  without `--resume` for a full re-verify). Checkpoint at `TIDDL_PATH/resume/`.

### Reliability

- **Run-wide 429 circuit breaker.** A giant run that TIDAL throttles repeatedly
  now stops cleanly — with a "wait and resume" / "re-login" message and a
  non-zero exit — once 429s cross a run-wide threshold, or when the account is
  flagged (refresh-blocked 401), instead of thousands of tasks retrying
  independently until a soft rate-limit escalates into a hard account block. The
  breaker is shared by the main and fallback clients, and a stopping run now
  abandons its retry backoff at once. Benefits the CLI and the GUI's embedded
  engine alike.
- **Bounded memory on huge expanded runs.** A playlist expanded into every
  credited artist no longer creates one asyncio task per resource up front; a
  fixed worker pool keeps at most `artist_concurrency` tasks alive, so peak
  memory no longer scales with the resource count (previously an out-of-memory
  hard-kill on very large runs).

### Documentation

- Added a bilingual destination-safety guide and linked user-facing setup,
  configuration, second-machine adoption and recovery instructions from the
  README, configuration reference, usage guide and Spanish tutorial.
- Documented the stereo edition resolver, quality policies, `tiddl info
  editions` and the artist compilation/live-album filter across the README,
  configuration reference and command reference.

---

## [1.4.1] - 2026-08-20

### Added

- `--exclude-compilations` / `--exclude-live-albums` CLI flags (tri-state,
  override the config equivalents per run).

## [1.4.0] - 2026-08-20

### Added

- Exclude **compilations** and **live albums** from artist downloads.
  TIDAL types both as plain albums, so they are identified from the artist page
  (the same "Compilations" / "Live albums" sections the app shows) via the new
  `core/artist_sections` module and skipped by album id. Config:
  `[download] exclude_compilations` / `exclude_live_albums` (default off).

## [1.3.2] - 2026-08-19

### Performance

- Cache catalog reads across an artist stereo run: resolving a whole artist went
  from minutes to seconds with identical results (per-run `CatalogReadCache`).

## [1.3.1] - 2026-08-19

### Added

- `--audio-mode stereo` now works on **artist** URLs — expands the artist into
  its releases (honouring `--singles`) and resolves each album to its stereo
  edition; an album with no stereo edition keeps its original.

## [1.3.0] - 2026-08-19

### Added

- **Stereo Edition Resolver + Quality Policies.** Given an Atmos-only album URL,
  find and use a separately-published stereo edition at High/MAX, TIDAL-catalog
  only. New `--audio-mode auto|stereo`, `--edition-match ask|best`,
  `--quality-policy flexible|strict`, and the read-only `tiddl info editions`
  diagnostic. New modules `edition_resolver`, `stream_policy`, `download_policy`.

### Fixed

- A cooperative safety stop (e.g. run-wide 401) now exits the CLI non-zero.
- Strict `normal` correctly maps to TIDAL `HIGH` (not `LOSSLESS`).

---

## [1.2.1] - 2026-08-19

### Changed

- **Accurate CLI version output** — `tiddl --version` now reads the installed
  distribution metadata and reports the actual SemVer version instead of the
  fixed `elvigilante-julio-2026` label. Git-installed builds still append their
  commit and date when that provenance is available.
- **Modern package license metadata** — Packaging now uses the PEP 639 SPDX
  expression (`MIT`) and explicitly includes `LICENSE`, eliminating deprecated
  setuptools metadata before its 2027 removal deadline.

---

## [1.2.0] - 2026-08-19

### ✨ Added

- **Destination-volume identity** (`tiddl/core/utils/destination_anchor.py`, `tiddl destination trust/status/forget`, `tiddl recover --bind-root`)
  — Opt-in guard (`[download] destination_identity = "strict"`, default `"off"`) against
  writing to the wrong place when a NAS/USB/network destination is unmounted and the
  path silently falls back to a local folder that happens to share the same name.
  `tiddl destination trust <path>` writes a small marker file at the real destination
  root plus a per-machine local record; every one of the nine places a download or
  recovery writes to disk (track/video directory creation, media publication, `.lrc`,
  track/video metadata, M3U, cover, mtime update) refuses in `strict` mode unless the
  configured root's marker and local record still agree. A refusal never loses data —
  the verified local copy is retained (`tiddl recover` picks it up once the real
  destination is trusted again) and the command exits non-zero. `"off"` performs zero
  extra filesystem reads; existing installs are unaffected until this is turned on.

- **`--embed-lyrics` / `--save-lyrics` per-run overrides** (`tiddl/cli/commands/download/__init__.py`)
  — Lyrics options lived only in `[metadata]` config. The new paired flags
  (`--save-lyrics/--no-save-lyrics`, `--embed-lyrics/--no-embed-lyrics`) override the
  config for a single run: embed lyrics in tags and/or write an `.lrc` sidecar next
  to each track. Omitting them keeps the config behavior.

- **`--albums` / `--artists` / `--tracks` playlist expansion** (`tiddl/cli/commands/download/__init__.py`)
  — `tiddl download --albums url <playlist>` downloads the full albums of every track
  in the playlist (deduped by album id) instead of the playlist tracks; `--artists`
  downloads the full discographies of every credited artist (deduped by artist id);
  `--tracks` downloads each playlist track as a standalone track. In all three modes
  the downloads use the album/artist/track templates and folder layout — nothing goes
  through the playlist template, playlist folder or m3u. Same dedupe semantics as
  `tidmon playlist albums/artists --export`, without the export round-trip.
  Mutually exclusive; non-playlist URLs in the same command are unaffected.

### 🐛 Fixed

- **Download options now accepted after the subcommand** (`tiddl/cli/app.py`)
  — `tiddl download url --track-quality max <url>` (the syntax shown throughout the
  docs) failed with `No such option: --track-quality` because Click required group
  options before the subcommand. An argv-normalization shim in the entry point now
  moves download-group options written after `url`/`fav`/`search` to their correct
  position, so both orders work. Options owned by the subcommand itself
  (`fav --types/-t`, `search --limit/-l`) are left in place.

- **Clean error output on bad subcommand arguments** (`tiddl/cli/commands/download/__init__.py`)
  — When the subcommand failed to parse (e.g. an invalid option), the teardown still
  rendered empty Downloading/Total Progress panels and `Total downloads: 0` before
  the actual error message, burying it. The downloader teardown now exits early when
  no resources were queued.

- **Video ARTIST tag: multi-value list** (`tiddl/core/metadata/video.py`)
  — Video metadata now writes ARTIST as a list of individual names (sorted MAIN then
  FEATURED) instead of a single joined string. Consistent with music track behavior.
  Artist type is read via `getattr(a, 'type', None)` for safety.

- **Video DATE tag: year-only** (`tiddl/core/metadata/video.py`)
  — Date tag now stores only the year (e.g. `2025`) instead of the full datetime string
  (`2025-05-15 00:00:00`). Consistent with music track behavior and iTunes/Apple Music
  expectations.

- **Skip-existing now checks destination folder** (`cli/commands/download/__init__.py`,
  `cli/commands/download/downloader.py`)
  — A track previously downloaded to a playlist folder was being skipped when downloading
  its album, leaving the album folder incomplete. Skip now only triggers when the existing
  file is already in the correct destination folder (album/artist path match).

- **Download time window removed** (`cli/commands/download/__init__.py`, `cli/config.py`)
  — The `download_start_hour` / `download_end_hour` restriction was silently blocking
  downloads outside an 8:00–23:00 window. Both defaults changed to `0` (no restriction).
  The feature remains configurable in `config.toml` for users who want it.

---

## [1.1.7] - 2026-07-24

### 🐛 Fixed

- **`click` missing from dependencies broke every install** (`pyproject.toml`)
  — `tiddl/cli/app.py` imports `click` directly (`click.Option` in
  `_reorder_download_options`, which runs on *every* invocation). `click` was never
  declared as a dependency; it only resolved because older `typer` pulled it in
  transitively. `typer>=0.27` no longer depends on `click`, so clean installs
  (`pip install git+https://github.com/np3ir/tiddl-elvigilante`) succeeded but then
  crashed on the first command with `ModuleNotFoundError: No module named 'click'`.
  Now declared explicitly as `click>=8.0`.

### 📖 Documentation

- **Normalized all repository URLs** to lowercase `np3ir/tiddl-elvigilante`
  (README, FORK, CONTRIBUTING, CHANGELOG, `pyproject.toml`). GitHub usernames are
  case-insensitive so the old `Np3ir` links still resolved, but the canonical form
  is now consistent everywhere.
- **Added an Android / Termux installation section** to the README, since
  `pip install git+…` needs the `git` command available and Android does not ship it.

---

## [1.1.6] - 2026-03-29

### 📖 Documentation

- **Complete Unicode fullwidth table** — Both `## 🌍 Unicode-First Filenames` and
  `## 🔄 Filename Creation` sections now document all 9 Windows-forbidden characters
  with their fullwidth equivalents and Unicode code points (`／ ＼ ： ＊ ？ ＂ ＜ ＞ ｜`).

---

## [1.1.5] - 2026-03-29

### 📖 Documentation

- **Unicode-First Filenames** — Added dedicated section to README highlighting the core
  differentiator: fullwidth Unicode equivalents (`／` `：` `？` `＂`) preserve artist and
  album names exactly as TIDAL has them, across every filesystem. Most tools replace these
  with underscores, destroying the original metadata.
- **Filename comparison table** — Added `## 🔄 Filename Creation vs Other TIDAL Downloaders`
  with side-by-side examples showing the difference at scale with tens of thousands of albums.

---

## [1.1.4] - 2026-03-17

### 🐛 Fixed

- **Video filter bypass** — Tracks inside albums were incorrectly processed as video
  streams even when `videos_filter = "none"`, causing a `TypeError: cannot unpack
  non-iterable NoneType object` crash during artist downloads. `downloader.download()`
  now always returns a valid tuple, and video items are skipped cleanly when the filter
  is set to `"none"`.

---

## [1.1.3] - 2026-03-15

### ⚡ Performance

- **`threads_count` default raised 2 → 4** — Doubles concurrent download throughput out
  of the box. Albums and playlists now download ~2× faster with no configuration changes
  required. Range 2–6 recommended; higher values are faster but more detectable.
- **`requests_per_minute` documented in `config.example.toml`** — Now visible with
  `50=safe / 80=fast / 120=aggressive` guidance so users can tune API rate without
  reading source code.

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
- `pip install git+https://github.com/np3ir/tiddl-elvigilante` now works correctly

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

- **GitHub**: https://github.com/np3ir/tiddl-elvigilante
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
