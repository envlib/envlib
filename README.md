# envlib

<p align="center">
    <em>A distributed catalogue for environmental data</em>
</p>

[![build](https://github.com/envlib/envlib/workflows/Build/badge.svg)](https://github.com/envlib/envlib/actions)
[![codecov](https://codecov.io/gh/envlib/envlib/branch/main/graph/badge.svg)](https://codecov.io/gh/envlib/envlib)
[![PyPI version](https://badge.fury.io/py/envlib.svg)](https://badge.fury.io/py/envlib)

---

**Documentation**: <a href="https://envlib.github.io/envlib/" target="_blank">https://envlib.github.io/envlib/</a>

**Source Code**: <a href="https://github.com/envlib/envlib" target="_blank">https://github.com/envlib/envlib</a>

---

## Overview

envlib is a distributed database and catalogue for environmental datasets — gridded model output and station time series alike. Datasets are stored as [cfdb](https://github.com/mullenkamp/cfdb) files on S3-compatible object storage, hosted by whoever owns the data; envlib provides the shared layer on top: standardized metadata, controlled vocabularies, deterministic identifiers, and a catalogue you can query to discover and open any registered dataset.

## Key features

- **Distributed by design** — the catalogue is an index, not a data silo: each dataset stays on its owner's storage, and one catalogue can span many owners.
- **Standardized metadata** — eleven identity fields (drawing on [ODM2](http://vocabulary.odm2.org/), [CF conventions](https://cfconventions.org/), and lessons from tethys) describe what every dataset *is*, validated against controlled vocabularies at creation time.
- **Deterministic, permanent identifiers** — a dataset's identity metadata hashes to stable ids (`dataset_id`, `dataset_version_id`, `station_id`), so the same data gets the same id everywhere, forever.
- **Queryable catalogue** — filter by any identity field, spatial extent (including across the antimeridian), and time range; browse what a catalogue holds with `cat.variables`, `cat.owners`, and friends.
- **CF standard names derived for you** — envlib curates the mapping from its variables to CF `standard_name`s and applies it automatically at registration.
- **cfdb storage** — every dataset version is a [cfdb](https://github.com/mullenkamp/cfdb) file: chunked, compressed, partially readable, S3-syncable.

## Installation

```bash
pip install envlib
```

## Quick example

```python
import envlib

# The public envlib catalogue — zero config, no credentials
# (until it's hosted: Catalogue(remotes=['https://.../catalogue.rcg']))
cat = envlib.Catalogue()

# What's in it?
cat.variables       # ['precipitation', 'streamflow', 'temperature']
cat.owners          # ['ecan', 'ecmwf', 'niwa']

# Find the latest version of each matching dataset
results = cat.query(
    variable='temperature',
    feature='atmosphere',
    bbox=[166, -47, 179, -34],
    start_date='2020-01-01',
)

# Open one as a cfdb dataset and read it
ds = results[0].open()
temp = ds['temperature']
```

Producing data is the same library in the other direction: build a cfdb file, attach `envlib.Metadata`, and `cat.publish(...)` it — see the [documentation](https://envlib.github.io/envlib/) for the full guide.

Changes between releases are tracked in the [changelog](https://envlib.github.io/envlib/changelog/).

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
