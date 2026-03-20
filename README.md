# envlib

<p align="center">
    <em>The environmental library</em>
</p>

[![build](https://github.com/envlib/workflows/Build/badge.svg)](https://github.com/envlib/actions)
[![codecov](https://codecov.io/gh/mullenkamp/envlib/branch/main/graph/badge.svg)](https://codecov.io/gh/mullenkamp/envlib)
[![PyPI version](https://badge.fury.io/py/envlib.svg)](https://badge.fury.io/py/envlib)

---

**Source Code**: <a href="https://github.com/envlib" target="_blank">https://github.com/envlib</a>

---
## Overview
envlib is a distributed database and catalogue for environmental data. It uses controlled vocabulary and standarized metadata to make it easy for users to query and access data. It uses cfdb as the backend. The metadata structure is based on tethysts.


## Development

### Setup environment

We use [UV](https://docs.astral.sh/uv/) to manage the development environment and production build. 

```bash
uv sync
```

### Run unit tests

You can run all the tests with:

```bash
uv run pytest
```

### Format the code

Execute the following commands to apply linting and check typing:

```bash
uv run ruff check .
uv run black --check --diff .
uv run mypy --install-types --non-interactive envlib
```

To auto-format:

```bash
uv run black .
uv run ruff check --fix .
```

## License

This project is licensed under the terms of the Apache Software License 2.0.
