# Contributing to tiddl

Thank you for your interest in contributing to tiddl! We welcome contributions of all kinds.

## Code of Conduct

Please be respectful and inclusive. We don't tolerate harassment or discrimination.

## How to Contribute

### Reporting Bugs

1. Check if the issue already exists
2. Provide a clear description of the bug
3. Include steps to reproduce
4. Share your environment (OS, Python version, tiddl version)

### Suggesting Features

1. Check if the feature was already suggested
2. Explain the use case and benefits
3. Provide examples if possible

### Code Contributions

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Install development dependencies: `pip install -r requirements.txt`
4. Make your changes
5. Run tests: `pytest tests/`
6. Run type checker: `mypy . --strict`
7. Format code: `black cli/ core/ tests/`
8. Commit: `git commit -m "Add your feature"`
9. Push: `git push origin feature/your-feature`
10. Open a Pull Request

## Development Setup

```bash
# Clone your fork
git clone https://github.com/yourusername/tiddl.git
cd tiddl

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install dev tools
pip install pytest mypy black ruff pytest-asyncio
```

## Running Tests

```bash
# All tests
pytest tests/

# Specific test
pytest tests/test_cultural_regression.py

# Verbose output
pytest -v tests/

# With coverage
pip install pytest-cov
pytest --cov=core tests/
```

## Code Style

- Use Black for formatting: `black cli/ core/ tests/`
- Use Ruff for linting: `ruff check cli/ core/ tests/`
- Use MyPy for type checking: `mypy . --strict`
- Follow PEP 8
- Write docstrings for public functions
- Add type hints to all functions

## Commit Messages

- Use clear, descriptive messages
- Start with a verb: "Add", "Fix", "Improve", "Refactor"
- Keep lines under 72 characters
- Example: `Add support for HI_RES_LOSSLESS audio quality`

## Pull Request Process

1. Update documentation if needed
2. Add tests for new features
3. Ensure all tests pass: `pytest tests/`
4. Ensure type checking passes: `mypy . --strict`
5. Ensure code is formatted: `black cli/ core/ tests/`
6. Fill out the PR template
7. Link related issues

## Areas for Contribution

- 🐛 Bug fixes (always welcome!)
- ✨ New features (discuss first in Issues)
- 📖 Documentation improvements
- 🧪 Tests (especially edge cases)
- 🌍 Language support
- 🚀 Performance improvements
- ♿ Accessibility improvements

## Questions?

- Create an Issue for discussion
- Check existing Issues and Discussions
- Email or contact maintainers

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing! 🙏
