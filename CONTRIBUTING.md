# Contributing to BuildSite

Thank you for your interest in contributing to **BuildSite**! We welcome contributions ranging from bug fixes, documentation improvements, and architectural features to 3D Blender models and shader enhancements.

---

## Code of Conduct

All contributors and participants are expected to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Development Setup

### 1. Clone the Repository
```bash
git clone https://github.com/buildsite/buildsite.git
cd buildsite
```

### 2. Set Up a Virtual Environment
```bash
python -m venv .venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\Activate.ps1
```

### 3. Install in Editable Mode with Dev Dependencies
```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 4. Verify the Installation
```bash
buildsite validate
pytest
```

---

## Running Tests

We maintain comprehensive automated test coverage across progression mechanics, GitHub API queries, Pillow compositing, and SVG standards:

```bash
# Run all tests
pytest

# Run tests with coverage
pytest --cov=buildsite
```

---

## Submitting Pull Requests

1. **Create a Topic Branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. **Commit Your Changes**: Follow standard conventional commits format (e.g. `feat: add coastal material palette`, `fix: handle edge case in micro-evolution`).
3. **Verify Tests**: Ensure all 23+ unit tests pass and code complies with formatting rules.
4. **Push and Open a PR**: Submit your PR with a clear description of the change and any visual before/after samples.
