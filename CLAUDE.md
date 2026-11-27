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

## Docs examples are tests

Every Python block in `README.md` and `docs/` runs, page by page, top to bottom in one namespace (Sybil;
`uv run pytest README.md docs`; machinery in `envlib/tests/docs_support.py`, wired from the root `conftest.py`).
Blocks that read the live public commons sit under `<!-- skip: start if(not docs_live, reason="...") -->` and run
with `--docs-live` (CI: every push to `dev`, and weekly on `main`); their outputs are dated snapshots of the commons.
Each page runs in a scratch directory with a scratch `HOME`; S3 examples hit a local moto server (the
placeholder endpoint `https://s3.example.com` and keys like `'...'` are rewritten); any other network use fails the
page; a dataset left open fails the page. `envlib/tests/test_docs_inventory.py` (in the unit suite) fails if a fence
or directive is not parsed by Sybil, a fence's label is not exactly `python`/`bash`/`mermaid`/`text`, a skip has no
reason or is unbalanced, a shown value sits unchecked in a comment, a `>>>` block uses a doctest option other
than ELLIPSIS/NORMALIZE_WHITESPACE (e.g. `+SKIP`) or has text after a blank line (never run), or the skips (and
how many examples each covers) differ from
`envlib/tests/docs_skips.txt`. CI runs these plus `mkdocs build --strict` (broken anchors fail it too).

Writing examples:
- Show values as `>>>` doctests with the real output (run it). No global ELLIPSIS/NUMBER; opt in per example
  (`# doctest: +ELLIPSIS`) only for genuinely elided output. Lines meant to raise are `>>>` examples with the
  `Traceback` and the qualified exception.
- Make each page runnable top to bottom: define every name the page uses, give creation examples their own file
  names, and close every dataset (including what `combine`/`merge_into` return).
- Fix visibly what a reader would also trip on. Use a hidden `<!-- invisible-code-block: python ... -->` (column 0)
  only for state the reader is assumed to have (their own file, credentials, an existing remote, the dataset a
  reference-page fragment assumes is open); it only imports, calls a builder from `docs_support`, assigns names,
  or opens and closes that assumed dataset.
- Skip only with a reason, and add the skip to `docs_skips.txt`. Pseudo-code and output listings get the label
  `text`.

Known limits of the docs tests (accepted as rare, 2026-11-14 code review `docs-tests-code-1`):
- Not checked: `>>>` examples in source docstrings rendered by mkdocstrings, pages pulled in by `--8<--` snippets
  from outside `docs/`, the output of `print()` the page does not state, and a relabel of a fence to `text`.
- The open-dataset check scans the whole process, so in a combined run (`pytest .`) it would close, and blame on a
  docs page, a dataset a unit test still holds. Run the docs tests on their own.
- The per-page module that lets `map(n_workers=...)` pickle page functions needs the `fork` start method (the Linux
  default to Python 3.13); with forkserver or spawn (Python 3.14, macOS) those examples hang until the timeout.
- A loopback HTTP proxy in the environment (`http_proxy`) bypasses the offline guard, and a dead one stops the
  moto server's health check: unset proxies for loopback, or set `no_proxy=127.0.0.1,localhost`.
- A SIGKILL of pytest leaves the page's scratch directories in the temp dir (the moto server itself exits with it).

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
