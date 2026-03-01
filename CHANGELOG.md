# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## About This Fork

This is an **independent fork** of [@oskvr37/tiddl](https://github.com/oskvr37/tiddl) - the original excellent TIDAL downloader project.

**Why This Fork?**
- ✅ Python 3.10 compatibility (original requires 3.11+)
- ✅ Modern architecture (layered design)
- ✅ Production-grade quality
- ✅ Completely independent installation

See [FORK.md](FORK.md) for detailed information about this fork.

---

## [1.0.0] - 2024-03-01 (Independent Fork Release)

### What's New (Fork Improvements)

This is the first stable release of the independent fork, with major improvements.

#### ✅ Critical: Python 3.10+ Support
- **PROBLEM FIXED**: Original used `tomllib` (Python 3.11+ only) - crashes on 3.10
- **SOLUTION**: Implemented `try/except` fallback to `tomli` package
- **RESULT**: Works on Python 3.10, 3.11, 3.12, 3.13, 3.14+

#### ✅ Architecture: Complete Refactor
- Organized from flat (39 files) to modular (52 files)
- New `cli/` layer (16 files) - CLI implementation
- New `core/` layer (19 files) - Business logic
  - `core/api/` - TIDAL API integration
  - `core/auth/` - Authentication handling
  - `core/metadata/` - Metadata processing
  - `core/utils/` - Core utilities

#### ✅ Modern Python Standards
- PEP 563: `from __future__ import annotations` (all files)
- PEP 517/518: Modern `pyproject.toml`
- Complete type hints
- Proper dependency specification

#### ✅ Production-Grade Quality
- Comprehensive documentation
- Contribution guidelines
- Test suite with regression tests
- Complete error handling

#### ✅ Independent Installation
- NO need to install original `tiddl`
- Completely standalone
- Can coexist with original if needed

### Changed
- Refactored project structure to modular architecture
- Updated for Python 3.10 (fixed `tomllib` incompatibility)
- Translated to English
- Modernized dependencies (added `tomli`)
- Enhanced documentation

### Added
- `FORK.md` - About this fork
- `pyproject.toml` - Modern configuration
- `CONTRIBUTING.md` - Contribution guidelines
- `.editorconfig` - Editor configuration
- Enhanced `requirements.txt`
- Comprehensive test suite

### Removed
- `micodigo.txt` - Obsolete notes

---

## Compatibility Matrix

| Python | Status |
|--------|--------|
| 3.10 | ✅ **WORKS** |
| 3.11 | ✅ WORKS |
| 3.12 | ✅ WORKS |
| 3.13 | ✅ WORKS |
| 3.14+ | ✅ WORKS |

---

## Acknowledgments

Special thanks to [@oskvr37](https://github.com/oskvr37) and all original tiddl contributors.

This fork builds upon excellent original work with full attribution.

---

## References

- **Original Project**: https://github.com/oskvr37/tiddl
- **About This Fork**: See [FORK.md](FORK.md)
- **Setup**: See [README.md](README.md)
- **Quick Start**: See [QUICK_START.md](QUICK_START.md)
