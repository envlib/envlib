# envlib Design Plan

## Context

envlib needs a well-defined API for creating, cataloguing, and accessing standardized environmental datasets. The goal is to enforce a unified metadata standard (drawing from ODM2, CF conventions, and OSM concepts) so scientists can discover and share cfdb datasets through a distributed catalogue built on ebooklet's RemoteConnGroup (RCG).

## Dataset Metadata Model

### Required fields (stored in both RCG user_meta and cfdb ds.attrs)

| Field | Type | Derives dataset_id | CV Source |
|-------|------|--------------------|-----------|
| feature | str | yes | envlib's own (OSM-inspired) |
| variable | str | yes | ODM2 variablename (underscore_style) |
| method | str | yes | ODM2 methodtype (underscore_style) |
| product_code | str | yes | free-form (with suggestions) |
| owner | str | yes | free-form |
| aggregation_statistic | str | yes | ODM2 aggregationstatistic (underscore_style) |
| frequency_interval | str | yes | format validation (e.g. 1H, 24H, T) |
| utc_offset | str | yes | format validation (e.g. 0H, -3H) |
| license | str | no | curated SPDX subset |
| attribution | str | no | free-form |

**dataset_id**: blake2b(digest_size=12) hash of the first 8 fields, hex-encoded. Computed internally — not a user-facing key. Used for duplicate detection during registration.

**Note**: "parameter" from tethysts is renamed to "variable" to align with ODM2 variablename.

### Immutability
The 8 core fields (feature through utc_offset) are immutable once a dataset is created. Changing any of them fundamentally changes what the dataset represents — the user should create a new dataset instead.

### Data variable requirements
- **units** required on the primary data variable
- Optional CF `standard_name` attribute on data variables
- CRS must be defined on every dataset

## Controlled Vocabularies

### Implementation: bundled data files + optional refresh

- Ship JSON files in `envlib/vocabularies/` for each CV
- Validate field values against bundled data at dataset creation time
- Provide a utility function to refresh from ODM2 API: `envlib.vocabularies.refresh()`
- ODM2 API base: `http://vocabulary.odm2.org/api/v1/{vocab}/?format=json`

### Vocabulary sources

| Field | Source | Entries | Bundled file |
|-------|--------|---------|--------------|
| variable | ODM2 variablename (converted to underscore_style) | ~996 | `variable.json` |
| aggregation_statistic | ODM2 aggregationstatistic (converted to underscore_style) | ~18 | `aggregation_statistic.json` |
| method | ODM2 methodtype (converted to underscore_style) | ~26 | `method.json` |
| feature | envlib-defined | ~10-15 | `feature.json` |
| license | curated SPDX subset | ~10-15 | `license.json` |
| product_code | free-form (suggestions in docs) | — | — |

### envlib-defined vocabularies

**feature** (envlib-defined, singular form):
- `atmosphere` — ambient air, weather, climate
- `waterway` — rivers, streams, canals
- `still_water` — lakes, reservoirs, ponds
- `ocean` — open ocean, seas
- `groundwater` — aquifers, subsurface water
- `glacier` — glaciers, ice sheets
- `wetland` — swamps, marshes, bogs
- `soil` — soil and subsurface earth
- `coastline` — coastal zones, estuaries
- `land` — general land surface, terrain
- (extensible — refine during implementation)

**license** (curated SPDX subset for data):
- `CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`, `CC-BY-NC-SA-4.0`
- `CC0-1.0` (public domain dedication)
- `ODbL-1.0` (Open Data Commons)
- `CC-BY-3.0`, `CC-BY-SA-3.0`
- (refine during implementation)

**product_code** (free-form, suggested values documented):
- `raw_data`, `quality_controlled`, `simulation`, `forecast`, `reanalysis`, etc.
- No validation — just documented suggestions

## Public API

### 1. Catalogue — RCG-backed dataset discovery and access

The Catalogue wraps one or more RCGs. Each dataset entry is a `DatasetRef` object that knows its metadata and how to open itself.

```python
import envlib

# Connect to one or more RCGs
cat = envlib.Catalogue(
    remotes=[remote1, remote2, ...],  # S3Connection or dict or URL
    cache='~/.envlib/cache',          # auto-managed cache dir (default: tempdir)
)

# All datasets — list of DatasetRef objects
cat.datasets
# [{'feature': 'atmosphere', 'variable': 'air_temperature', 'owner': 'NIWA', ...},
#  {'feature': 'waterway', 'variable': 'discharge', 'owner': 'NIWA', ...}]
# (DatasetRef.__repr__ displays as a metadata dict)

# Query with kwargs filtering (returns filtered list of DatasetRef)
results = cat.query(variable='air_temperature', owner='NIWA')

# Open directly from the entry — returns cfdb EDataset
ds = results[0].open()
ds = results[0].open(file_path='/custom/path.cfdb')  # override cache

# Register an existing remote dataset in an RCG (rejects duplicates via dataset_id)
cat.register(remote_conn, rcg_remote_conn)
```

**DatasetRef** wraps an RCG entry:
- `__repr__` displays metadata as a dict
- `.open(file_path=None)` opens the cfdb EDataset using the stored S3Connection
- `.metadata` returns the full metadata dict
- Attribute access for individual fields: `ref.variable`, `ref.owner`, etc.

### 2. Metadata class — structured metadata construction

No `create_dataset` wrapper. Users create cfdb datasets directly and assign metadata via `ds.attrs.update()`. The `Metadata` class validates CV fields on construction and provides a dict for cfdb.

```python
# Build metadata — validates CV fields on construction
meta = envlib.Metadata(
    feature='atmosphere',
    variable='air_temperature',
    method='observation',
    product_code='raw_data',
    owner='NIWA',
    aggregation_statistic='average',
    frequency_interval='1H',
    utc_offset='0H',
    license='CC-BY-4.0',
    attribution='Data provided by NIWA',
)

# Or build incrementally — validates each field as it's set
meta = envlib.Metadata()
meta.feature = 'atmosphere'
meta.variable = 'air_temperature'
# ...

# Create cfdb dataset directly, assign metadata
from cfdb import open_dataset
ds = open_dataset('data.cfdb', flag='n')
ds.attrs.update(meta.to_dict())
ds.create.crs.from_user_input(4326, x_coord='longitude', y_coord='latitude')
# ... create coords, data vars, write data via cfdb API ...
ds.close()

# Register — validates ALL requirements (metadata complete, CRS set, units on primary var)
# Rejects duplicates via computed dataset_id
cat.register(remote_conn, rcg_remote_conn)
```

**Metadata class**:
- Properties for each field with CV validation on set
- `.to_dict()` returns a plain dict suitable for `ds.attrs.update()`
- `.dataset_id` computed property (blake2b hash of 8 core fields, only available when all 8 are set)
- Incremental or all-at-once construction

### 3. Vocabulary utilities

```python
from envlib import vocabularies

# List valid values for a field
vocabularies.list('variable')       # -> ['air_temperature', 'precipitation', ...]
vocabularies.list('feature')        # -> ['atmosphere', 'waterway', ...]

# Check if a value is valid
vocabularies.is_valid('variable', 'air_temperature')  # -> True

# Refresh from ODM2 API
vocabularies.refresh()              # updates all ODM2-sourced bundled files
vocabularies.refresh('variable')    # update just one
```

## Module Structure

```
envlib/
├── __init__.py              # public API: Catalogue, Metadata, version
├── catalogue.py             # Catalogue class, DatasetRef class
├── metadata.py              # Metadata class, dataset_id hashing, validation
├── vocabularies/
│   ├── __init__.py          # list(), is_valid(), refresh()
│   ├── variable.json        # from ODM2 variablename
│   ├── aggregation_statistic.json  # from ODM2 aggregationstatistic
│   ├── method.json          # from ODM2 methodtype
│   ├── feature.json         # envlib-defined
│   └── license.json         # curated SPDX subset
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_catalogue.py
    ├── test_metadata.py
    └── test_vocabularies.py
```

## Key Dependencies to Add

- `cfdb` — storage backend
- `ebooklet` — remote/S3 support (optional, for Catalogue remote features)

## Implementation Order

1. **Vocabularies module** — bundled JSON files, validation functions, refresh utility
2. **Metadata module** — `Metadata` class with CV validation, dataset_id hashing, `.to_dict()`
3. **Catalogue module** — `Catalogue` class (RCG-backed), `DatasetRef` class with .open(), .datasets, .query(), .register() with full validation
4. **Tests** for each module
5. **Update `__init__.py`** with public API exports

## Verification

- `uv run pytest` — unit tests for:
  - dataset_id hashing is deterministic and consistent
  - Metadata validation rejects missing/invalid fields
  - Vocabulary validation accepts valid terms, rejects invalid
  - Catalogue lists/queries/filters correctly
- Integration test: `Metadata.to_dict()` → `ds.attrs.update()` → verify metadata round-trips through cfdb .attrs
- Integration test: vocabulary refresh from ODM2 API (network test, can be marked skip-if-offline)
