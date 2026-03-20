# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

envlib is a distributed database and catalogue for environmental data using controlled vocabulary and standardized metadata. Backend is cfdb (CF-compliant database) and metadata structure is based on tethysts. Currently in early development (0.1.0).

## Development Commands

This project uses **uv** as its package manager.

```bash
# Install dependencies
uv sync

# Run all tests with coverage
uv run pytest

# Run a single test file
uv run pytest envlib/tests/test_foo.py

# Run a single test
uv run pytest envlib/tests/test_foo.py::test_name

# Lint
uv run ruff check .
uv run black --check --diff .

# Auto-format
uv run black .
uv run ruff check --fix .

# Type check
uv run mypy --install-types --non-interactive envlib
```

## Code Style

- **Formatter**: black (line-length 120, skip-string-normalization, target py310)
- **Linter**: ruff (line-length 120, target py310)
- **Type checker**: mypy
- Python 3.10+ required; CI tests against 3.10, 3.11, 3.12

## Architecture

- `envlib/` — main package; version defined in `envlib/__init__.py`
- `envlib/tests/` — tests live inside the package (pytest discovers from here)
- `docs/` — mkdocs-material documentation with mkdocstrings (Google-style docstrings)
- `conda/` — conda-forge recipe
- Build system: hatchling
