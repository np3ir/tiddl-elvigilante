# 🏗️ Design Constraints & Architecture

This document outlines the design principles and constraints that guide development of tiddl-elvigilante.

---

## 🎯 Core Principles

### 1. **Stability Over Features**
- ✅ Prefer proven, stable libraries
- ✅ Conservative dependency updates
- ✅ Backward compatibility maintained
- ❌ Don't chase latest versions blindly

### 2. **Broad Python Support**
- ✅ Support Python 3.10-3.14+
- ✅ Works on Windows, macOS, Linux
- ✅ No platform-specific code (unless necessary)
- ❌ Don't require cutting-edge Python features

### 3. **User Experience First**
- ✅ Clear error messages
- ✅ Sensible defaults
- ✅ Intuitive command interface
- ✅ Helpful documentation

### 4. **Production Ready**
- ✅ Type hints throughout
- ✅ Comprehensive testing
- ✅ Error handling
- ✅ Logging and debugging

### 5. **Maintainability**
- ✅ Modular architecture
- ✅ Clear code organization
- ✅ Well-documented code
- ✅ Easy to extend

---

## 🏛️ Architecture

### Directory Structure

```
tiddl-elvigilante/
├── cli/                    # CLI layer (user interface)
│   ├── __init__.py
│   ├── app.py             # Main Typer CLI application
│   ├── config.py          # Configuration loading
│   ├── commands/          # Command implementations
│   └── ctx.py             # CLI context
├── core/                  # Core layer (business logic)
│   ├── api/              # TIDAL API integration
│   │   ├── client.py     # API client
│   │   └── models/       # Data models
│   ├── auth/             # Authentication
│   │   ├── api.py        # Auth API
│   │   └── models.py     # Auth models
│   ├── metadata/         # Metadata processing
│   ├── utils/            # Shared utilities
│   └── ...
├── tests/                 # Test suite
│   ├── test_config.py
│   ├── test_download.py
│   └── ...
├── pyproject.toml        # Package configuration
├── requirements.txt      # Dependencies
└── README.md            # Documentation
```

### Layer Separation

```
┌─────────────────────┐
│   CLI Layer (cli/)  │  ← User interface, commands
├─────────────────────┤
│ Core Layer (core/)  │  ← Business logic, API integration
├─────────────────────┤
│  External APIs      │  ← TIDAL, filesystem, HTTP
└─────────────────────┘
```

**Benefits**:
- CLI can be easily replaced (UI, TUI, Web)
- Core logic is independent
- Easy to test
- Clear separation of concerns

---

## 📦 Dependency Constraints

### Python Version
```
requires-python = ">=3.10"
```

Minimum Python 3.10 for:
- `dict |` union syntax
- Modern type hints
- Built-in `tomllib` (3.11+, fallback tomli for 3.10)

### Package Versions

#### Pydantic
```
pydantic < 2.0  # Uses v1 API
```

**Why v1?**
- Simpler setup
- Compatible with Python 3.14
- Avoids forward reference issues
- Uses `.parse_obj()` API

**Not v2?**
- More complex configuration
- Breaking changes
- Issues with certain Python 3.14 scenarios

#### Other Dependencies
- All versions are pinned for stability
- Regular security updates
- Conservative updates (no major version bumps without testing)

### No Platform-Specific Dependencies
- Works on Windows, macOS, Linux
- Uses cross-platform paths
- No system calls (uses libraries instead)

---

## 🎯 Design Goals

### 1. **Compatibility**
- ✅ Work on Python 3.10+
- ✅ Work on all major OS
- ✅ Handle various audio formats
- ✅ Support all TIDAL content types

### 2. **Performance**
- ✅ Async downloads
- ✅ Multi-threaded operations
- ✅ Caching for API responses
- ✅ Efficient metadata handling

### 3. **Reliability**
- ✅ Comprehensive error handling
- ✅ Automatic retries
- ✅ File integrity verification
- ✅ Clear status messages

### 4. **Extensibility**
- ✅ Modular architecture
- ✅ Clear interfaces
- ✅ Easy to add new features
- ✅ Pluggable components

### 5. **Documentation**
- ✅ Code comments
- ✅ Docstrings (PEP 257)
- ✅ User guides
- ✅ API documentation

---

## 🚫 What We Don't Do

### ❌ GUI Application
- Command-line is simpler
- More portable
- Easier to maintain
- Can be scripted

### ❌ Online Platform
- Local-only tool
- Privacy-focused
- No server infrastructure
- Easier deployment

### ❌ Platform-Specific Features
- Should work everywhere
- No Windows-only features
- No macOS-only features
- Use cross-platform libraries

### ❌ DRM Circumvention
- Respect TIDAL ToS
- Use official APIs
- Authenticate properly
- Follow legal guidelines

### ❌ Unofficial API
- Use only official TIDAL APIs
- No reverse-engineering
- No unauthorized access
- Support TIDAL's business model

---

## 🔧 Code Quality Standards

### Type Hints
```python
# GOOD ✅
def download_track(track_id: str, quality: str = "high") -> Path:
    """Download a track from TIDAL."""
    ...

# BAD ❌
def download_track(track_id, quality="high"):
    ...
```

All functions must have:
- Parameter type hints
- Return type hints
- Docstrings

### Error Handling
```python
# GOOD ✅
try:
    result = api.fetch(track_id)
except HTTPError as e:
    log.error(f"Failed to fetch track: {e}")
    raise DownloadError(f"Network error: {e}")

# BAD ❌
result = api.fetch(track_id)  # No error handling
```

### Logging
```python
# GOOD ✅
log.debug(f"Downloading track {track_id}")
log.info(f"Downloaded: {filename}")
log.warning(f"Quality {quality} not available")
log.error(f"Download failed: {error}")

# BAD ❌
print(f"Downloading {track_id}")  # Use logging, not print
```

### Testing
- Unit tests for each module
- Integration tests for workflows
- Regression tests for bugs
- Test coverage > 80%

---

## 🔄 Dependencies Update Policy

### Security Updates
- ✅ Apply immediately
- ✅ Fast-track testing
- ✅ Release ASAP

### Bug Fixes
- ✅ Apply after testing
- ✅ Release in patch version

### New Features
- ⚠️ Evaluate need carefully
- ✅ Test thoroughly
- ✅ Release in minor version

### Major Version Updates
- ❌ Generally avoid
- ⚠️ Only if necessary
- ✅ Extensive testing
- ✅ Release in major version

---

## 📋 Before Adding Features

Ask these questions:

1. **Is it necessary?**
   - Does it solve a real problem?
   - Would users use it?

2. **Is it maintainable?**
   - Can we keep it working?
   - Will someone need to support it?

3. **Is it compatible?**
   - Works on Python 3.10+?
   - Works on all OS?

4. **Is it tested?**
   - Have we tested it?
   - Are there edge cases?

5. **Is it documented?**
   - Users know how to use it?
   - Code is commented?

If "no" to any, reconsider.

---

## 🔐 Security Considerations

### Credentials
- ✅ Stored locally only
- ✅ No transmission to external servers
- ✅ Clear user control

### API Usage
- ✅ Respect rate limits
- ✅ Authenticate properly
- ✅ Follow ToS

### File Operations
- ✅ Validate file paths
- ✅ Prevent path traversal
- ✅ Handle permissions properly

### Error Messages
- ✅ Don't expose sensitive info
- ✅ User-friendly messages
- ✅ Log details separately

---

## 🧪 Testing Strategy

### Unit Tests
- Test individual functions
- Mock external dependencies
- Fast execution

### Integration Tests
- Test workflows
- Use real (or test) data
- Slower but comprehensive

### Regression Tests
- Test fixed bugs
- Prevent re-introduction
- Important for stability

---

## 📈 Performance Constraints

### Download Speed
- Limit concurrent downloads (default: 4)
- Configurable via `threads_count`
- Respect TIDAL's rate limits

### Memory Usage
- Avoid loading entire files in memory
- Stream downloads where possible
- Clean up temporary files

### Network Usage
- Cache API responses
- Batch requests where possible
- Respect bandwidth limits

---

## 🎨 Coding Style

### Naming
```python
# Variables and functions: snake_case
track_id = "123456"
def download_track():
    ...

# Classes: PascalCase
class DownloadManager:
    ...

# Constants: UPPER_CASE
MAX_RETRIES = 3
```

### Line Length
- Maximum 88 characters (Black formatter)
- Break long lines
- Use parentheses for continuation

### Imports
```python
# Order: stdlib, third-party, local
import os
from pathlib import Path

import aiohttp
import pydantic

from tiddl.api import client
```

---

## 🚀 Release Process

### Versioning
- Semantic versioning: MAJOR.MINOR.PATCH
- MAJOR: Breaking changes
- MINOR: New features
- PATCH: Bug fixes

### Release Steps
1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create git tag: `v1.0.0`
4. Push to GitHub
5. GitHub Actions publishes to PyPI

---

## 📞 Questions?

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

---

**Last Updated**: March 1, 2026  
**Version**: 1.0.0
