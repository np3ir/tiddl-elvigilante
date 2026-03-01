# 🤝 Contributing to tiddl-elvigilante

Thank you for your interest in contributing! This document explains how to get involved.

---

## 📋 Code of Conduct

- Be respectful and constructive
- Assume good intentions
- Focus on the code, not the person
- Help others learn and grow
- Report inappropriate behavior

---

## 🚀 Getting Started

### 1. Fork the Repository
```bash
# Go to GitHub and click "Fork"
# Then clone your fork
git clone https://github.com/yourusername/tiddl-elvigilante.git
cd tiddl-elvigilante
```

### 2. Set Up Development Environment
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install in development mode
pip install -e .

# Install development tools
pip install -e ".[dev]"
```

### 3. Create a Feature Branch
```bash
git checkout -b feature/my-feature
# or
git checkout -b fix/my-bug
# or
git checkout -b docs/improvements
```

---

## 🎯 Types of Contributions

### 🐛 Bug Reports
Found a bug? Report it!

1. **Check existing issues** first
2. **Create detailed report** with:
   - Python version
   - Error message/traceback
   - Steps to reproduce
   - Expected behavior
   - Actual behavior

Example:
```
Title: Download fails with network timeout

Python Version: 3.12
Error: ConnectionError: Connection timeout

Steps:
1. Run: tiddl download "https://..."
2. Wait 30 seconds
3. Get timeout error

Expected: Should retry or show better error
Actual: Crashes with traceback
```

### ✨ Feature Requests
Have a great idea?

1. **Check if it exists** in issues/discussions
2. **Explain the use case**
3. **Show how it would work**

Example:
```
Title: Add support for offline mode

Use Case: I want to check what's downloaded without internet

Proposal:
tiddl status  # Show downloaded tracks
tiddl sync    # Update metadata without re-downloading
```

### 📝 Documentation
Help improve documentation!

1. **Fix typos**
2. **Add examples**
3. **Clarify instructions**
4. **Improve formatting**

### 🧪 Tests
Add test coverage!

```bash
# Run tests
pytest

# Check coverage
pytest --cov=tiddl
```

### 🛠️ Code Improvements
Optimize, refactor, improve code quality!

---

## 💻 Development Workflow

### 1. Make Your Changes
```bash
# Edit files
# Add tests if needed
# Update documentation if needed

# Check your code
python -m pytest
black tiddl/           # Format
ruff check tiddl/      # Lint
mypy tiddl/            # Type check
```

### 2. Commit Your Changes
```bash
# Good commit message format:
git commit -m "feat: add new download feature"
git commit -m "fix: handle network timeouts"
git commit -m "docs: improve README examples"
git commit -m "test: add tests for config parsing"

# Conventional commit types:
# feat:  New feature
# fix:   Bug fix
# docs:  Documentation
# test:  Tests
# refactor: Code refactoring
# perf:  Performance improvements
# chore: Maintenance
```

### 3. Push and Create Pull Request
```bash
# Push to your fork
git push origin feature/my-feature

# Go to GitHub and click "New Pull Request"
```

### 4. Describe Your PR
```
Title: Add exponential backoff for network retries

Description:
Improves reliability by implementing exponential backoff
for network timeouts and failures.

Fixes: #123
Related: #456

Changes:
- Add retry logic with exponential backoff
- Add config options for max retries
- Add tests for retry behavior

Testing:
- Tested with slow network
- Verified existing tests pass
- Added 3 new test cases
```

### 5. Review Process
- Maintainers will review your code
- Address any feedback
- Once approved, we'll merge it!

---

## 📐 Code Style

### Python Style
- Follow **PEP 8**
- Use **type hints**
- Write **docstrings**
- Keep functions **small and focused**

```python
def download_track(track_id: str, quality: str = "high") -> Path:
    """
    Download a single track from TIDAL.
    
    Args:
        track_id: TIDAL track ID
        quality: Audio quality (low, normal, high, max)
    
    Returns:
        Path to downloaded file
    
    Raises:
        ValueError: If quality is invalid
        DownloadError: If download fails
    """
    if quality not in ["low", "normal", "high", "max"]:
        raise ValueError(f"Invalid quality: {quality}")
    
    # Implementation here
    return Path("...")
```

### File Organization
```
tiddl/
├── __init__.py        # Package initialization
├── __main__.py        # Entry point
├── cli/              # CLI layer
│   ├── __init__.py
│   ├── app.py        # Main CLI app
│   ├── commands/     # Command implementations
│   └── config.py     # Configuration
├── core/             # Business logic
│   ├── api/          # API integration
│   ├── auth/         # Authentication
│   ├── metadata/     # Metadata
│   └── utils/        # Utilities
└── ...
```

---

## 🧪 Testing

### Run Tests
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_config.py

# Run with coverage
pytest --cov=tiddl --cov-report=html

# Run with verbose output
pytest -v
```

### Write Tests
```python
# In tests/test_my_feature.py

def test_download_track():
    """Test downloading a single track."""
    # Setup
    track_id = "123456789"
    
    # Execute
    result = download_track(track_id)
    
    # Assert
    assert result.exists()
    assert result.suffix == ".flac"

def test_download_with_invalid_quality():
    """Test that invalid quality raises error."""
    with pytest.raises(ValueError):
        download_track("123456789", quality="invalid")
```

---

## 📚 Documentation

### Update Documentation
1. Edit relevant `.md` file
2. Keep examples current
3. Fix typos
4. Improve clarity

### Document New Features
```markdown
### New Feature

Description of what it does.

Usage:
\`\`\`bash
tiddl download --new-flag "https://..."
\`\`\`

Options:
- `--new-flag`: Description
```

---

## 🔍 Before Submitting

### Checklist
- ✅ Code follows style guidelines
- ✅ All tests pass
- ✅ New tests added (if needed)
- ✅ Documentation updated (if needed)
- ✅ No breaking changes (or documented)
- ✅ Commit messages are clear
- ✅ No console errors/warnings

```bash
# Run this before submitting
python -m pytest                  # Tests
python -m black tiddl/           # Format
python -m ruff check tiddl/      # Lint
python -m mypy tiddl/            # Types
```

---

## 🎓 Project Structure

### Understanding the Code

**CLI Layer** (`cli/`)
- Handles user commands
- Parses arguments
- Calls core functions

**Core Layer** (`core/`)
- **api/** - Communicates with TIDAL
- **auth/** - Handles authentication
- **metadata/** - Processes metadata
- **utils/** - Shared utilities

**Tests** (`tests/`)
- Unit tests for each module
- Integration tests
- Configuration tests

---

## 💬 Getting Help

### Questions?
1. Check [README.md](README.md)
2. Check [USAGE.md](USAGE.md)
3. Check [CONFIG.md](CONFIG.md)
4. Open a Discussion on GitHub
5. Ask in an Issue

### Having Issues?
1. Search existing issues
2. Check [troubleshooting](USAGE.md#troubleshooting)
3. Open a new Issue with details

---

## 🎯 Priority Areas

We especially welcome contributions in:

1. **Bug Fixes** - Always needed!
2. **Tests** - Improve coverage
3. **Documentation** - Clarify and improve
4. **Performance** - Optimize code
5. **New Features** - Discuss first in Issues
6. **Compatibility** - More Python versions

---

## 🚀 Release Process

Maintainers handle releases:
1. Review and merge PRs
2. Update version in `pyproject.toml`
3. Update `CHANGELOG.md`
4. Tag release on GitHub
5. GitHub Actions publishes to PyPI

You don't need to do anything for this!

---

## 📞 Questions?

- **GitHub Issues**: Bug reports and feature requests
- **GitHub Discussions**: Questions and ideas
- **GitHub PRs**: Code contributions

---

## 🙏 Thank You!

Thank you for contributing to tiddl-elvigilante! Your help makes this project better for everyone. 

Together, we build something great! 🚀
