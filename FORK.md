# 🍴 About This Fork

## 📌 Overview

**tiddl** is an independent fork of the excellent [oskvr37/tiddl](https://github.com/oskvr37/tiddl) project with significant improvements focused on **Python 3.10+ compatibility, production-grade quality, and comprehensive documentation**.

---

## 🎯 Why This Fork Exists

### Original Project Status
The original `tiddl` project by @oskvr37 is excellent, but had specific limitations:

1. **Python 3.13+ Only**
   - Requires Python 3.13 or higher
   - Excludes users on Python 3.10, 3.11, 3.12

2. **Pydantic v2 Dependency**
   - Uses `pydantic>=2.12.4`
   - Conflicts with certain Python 3.14 scenarios
   - More complex setup

3. **Limited Documentation**
   - Basic README
   - Minimal examples
   - No contribution guidelines

4. **Monolithic Structure**
   - 47 files in single `tiddl/` directory
   - Harder to navigate and extend
   - Not optimized for team collaboration

### Our Solution
This fork addresses these limitations while maintaining compatibility with the original.

---

## ✨ What We Improved

### 1. **Python 3.10+ Support** (CRITICAL)
```python
# Original (requires 3.13+):
requires-python = ">=3.13"

# Our Fork (supports 3.10+):
requires-python = ">=3.10"
```

Now works on:
- ✅ Python 3.10
- ✅ Python 3.11
- ✅ Python 3.12
- ✅ Python 3.13
- ✅ Python 3.14+

### 2. **Pydantic v1 Compatibility**
```python
# Original:
pydantic >= 2.12.4  # Uses .model_validate()

# Our Fork:
pydantic < 2.0      # Uses .parse_obj()
```

Benefits:
- ✅ Tested with Python 3.14
- ✅ Simpler setup
- ✅ No forward reference issues
- ✅ Stable and reliable

### 3. **Professional Architecture**
```
Original (39 flat files):
├── api.py
├── auth.py
├── downloader.py
└── ... (all mixed)

Our Fork (52 organized files):
├── cli/           # User interface layer
├── core/          # Business logic
│   ├── api/       # TIDAL API integration
│   ├── auth/      # Authentication
│   ├── metadata/  # Metadata processing
│   └── utils/     # Utilities
├── tests/         # Test suite
└── docs/          # Documentation
```

Benefits:
- Clear separation of concerns
- Easier to extend and maintain
- Better for team collaboration
- Scales to larger projects

### 4. **Production-Grade Documentation**
```
README.md         - Overview and quick start
USAGE.md          - Detailed command examples
CONFIG.md         - Configuration reference
FORK.md           - This file (fork information)
CONTRIBUTING.md   - How to contribute
CHANGELOG.md      - Version history
DESIGN_CONSTRAINTS.md - Design principles
```

### 5. **Modern Python Standards**
- ✅ PEP 517/518 packaging (`pyproject.toml`)
- ✅ Type hints throughout
- ✅ `.editorconfig` for consistency
- ✅ Comprehensive error handling
- ✅ Professional `.gitignore`

### 6. **Complete Test Suite**
- ✅ Unit tests included
- ✅ Regression tests
- ✅ CI/CD ready

### 7. **Search Command with Top Hit Display**
```bash
tiddl download search "Pink Floyd" --limit 5
```
- Searches tracks, albums, and artists in one command
- Prominently displays the Top Hit with a ready-to-use download command
- Result IDs are shown in tables for direct use with `tiddl download url`

### 8. **x-tidal-token Fallback for Public Endpoints**
- When a Bearer token returns 401 on non-playback endpoints (search, metadata), the client automatically retries using the `x-tidal-token` header with the client_id
- Resilient when the access token expires between the proactive refresh window and actual expiry
- Playback endpoints (stream, logout, token) are excluded from this fallback

### 9. **streamReady Pre-check Before Download Attempts**
- Before attempting to fetch stream URLs, checks the `streamReady` boolean on Track objects
- Avoids wasting API quota and retry cycles on tracks that are not yet available for streaming
- Produces a clear yellow warning instead of cryptic API errors

---

## 📊 Feature Comparison

| Feature | Original | This Fork |
|---------|----------|-----------|
| **Python 3.10** | ❌ NO | ✅ YES |
| **Python 3.11** | ❌ NO | ✅ YES |
| **Python 3.12** | ❌ NO | ✅ YES |
| **Python 3.13+** | ✅ YES | ✅ YES |
| **Pydantic v2** | ✅ YES | ❌ NO |
| **Pydantic v1** | ❌ NO | ✅ YES |
| **TIDAL Downloads** | ✅ YES | ✅ YES |
| **Metadata** | ✅ YES | ✅ YES |
| **Unicode Support** | ✅ YES | ✅ YES |
| **Search Command** | ❌ NO | ✅ YES |
| **x-tidal-token Fallback** | ❌ NO | ✅ YES |
| **streamReady Pre-check** | ❌ NO | ✅ YES |
| **Architecture** | Flat | Modular |
| **Documentation** | Basic | Comprehensive |
| **Type Hints** | Partial | Complete |
| **Test Suite** | Minimal | Included |
| **Contributing Guide** | ❌ NO | ✅ YES |

---

## 🔄 How This Fork Works

### Installation Independence
```bash
# Install directly from this fork
pip install git+https://github.com/Np3ir/tiddl-elvigilante.git

# No need to install original
# This fork is completely standalone
```

### Separate Maintenance
- ✅ Separate repository
- ✅ Independent issue tracking
- ✅ Own release cycle
- ✅ Can coexist with original if needed

### Contributing Back
If you find improvements that benefit the original:
1. Notify @oskvr37
2. Open PR on original repository
3. We'll also maintain in our fork

---

## 🤝 Relationship with Original

### Acknowledgments
We deeply respect the original work by @oskvr37. This fork:
- ✅ Maintains the core functionality
- ✅ Preserves the spirit of the original
- ✅ Credits the original author
- ✅ Links back to original repository
- ✅ Licensed under the same MIT license

### Differences
- More conservative approach to dependencies
- Focus on broader Python version support
- Enhanced documentation and examples
- Modular architecture for maintainability

### Compatibility
- ✅ Same core commands: `tiddl download url https://...`
- ✅ Same TIDAL features
- ✅ Compatible download formats
- ✅ Can migrate between versions

---

## 📈 When to Use Each

### Use Original (oskvr37/tiddl)
- You have Python 3.13+
- You want latest Pydantic v2
- You prefer minimal dependencies
- You want upstream development

### Use This Fork (tiddl)
- You need Python 3.10-3.12 support
- You have Python 3.14 with dependency issues
- You want comprehensive documentation
- You need modular codebase
- You want stable, tested version
- You plan to contribute improvements

---

## 🚀 Getting Started

### Installation
```bash
pip install git+https://github.com/Np3ir/tiddl-elvigilante.git
```

### First Steps
```bash
# Authenticate
tiddl auth

# Download something
tiddl download url https://tidal.com/album/497662013
```

### Configuration
```bash
# Edit your config
nano ~/.tiddl/config.toml
```

See [CONFIG.md](CONFIG.md) for all options.

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for:
- How to report issues
- How to submit pull requests
- Development setup
- Code style guidelines

---

## 📜 License

MIT License - Same as original project

See [LICENSE](LICENSE) file for details.

---

## 🔗 Links

- **This Fork**: https://github.com/Np3ir/tiddl-elvigilante
- **Original Project**: https://github.com/oskvr37/tiddl
- **Original Author**: @oskvr37
- **TIDAL**: https://tidal.com

---

## 📝 Version History

- **v1.0.0** (March 2026) - Initial production release
  - Python 3.10+ support
  - Pydantic v1 compatibility
  - Production-grade documentation
  - Modular architecture

See [CHANGELOG.md](CHANGELOG.md) for detailed history.

---

**Thank you to @oskvr37 for the original excellent project!** 🙏

This fork stands on the shoulders of giants.
