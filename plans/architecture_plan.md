# envlib Design Plan

## Context

envlib needs a well-defined API for creating, cataloguing, and accessing standardized environmental datasets. The goal is to enforce a unified metadata standard (drawing from ODM2, CF conventions, and OSM concepts) so scientists can discover and share cfdb datasets through a distributed catalogue built on ebooklet's RemoteConnGroup (RCG).

## Dataset Metadata Model

The metadata model is strictly divided into two categories: **Identity Metadata** (immutable characteristics defining what the dataset is) and **State Metadata** (mutable characteristics describing the data's current extents or volume).

### 1. Identity Metadata (Required)
These 10 fields define the core nature of the dataset. They are stored in both RCG `user_meta` and cfdb `ds.attrs`.

| Field | Type | Derives dataset_id | CV Source |
|-------|------|--------------------|-----------|
| feature | str | yes | envlib's own (mapped to ENVO URIs) |
| variable | str | yes | ODM2 variablename (underscore_style) |
| method | str | yes | ODM2 methodtype (underscore_style) |
| product_code | str | yes | free-form (e.g., 'ERA5', 'VCSN') |
| owner | str | yes | free-form |
| aggregation_statistic | str | yes | ODM2 aggregationstatistic (underscore_style) |
| frequency_interval | str | yes | format validation (e.g. 1H, 24H, T) |
| utc_offset | str | yes | ISO 8601 offset (e.g. +00:00, +12:00, Z) |
| spatial_resolution | str | yes | format validation (e.g. 1km, 0.25deg, point) |
| version | str | yes | format validation (e.g., 1, 1.1, 2026-03) |

**dataset_id**: A deterministic `blake2b(digest_size=12)` hash of these 10 Identity fields, hex-encoded. Computed internally. It strictly enforces uniqueness. Changing any of these fields fundamentally changes what the dataset represents, which requires generating a new dataset rather than updating an existing one.

**Note**: "parameter" from tethysts is renamed to "variable" to align with ODM2 variablename. `spatial_resolution` captures the *nominal* resolution to provide stable identity grouping, mitigating floating-point inconsistencies from raw coordinate arrays. Explicit versioning allows the `product_code` to remain semantically clean while supporting distinct iterations of a dataset.

### 2. General Metadata (Optional/Descriptive)
These fields do not affect identity but are required by policy.

| Field | Type | Derives dataset_id | CV Source |
|-------|------|--------------------|-----------|
| license | str | no | curated SPDX subset |
| attribution | str | no | free-form |

### 3. State Metadata (Auto-Extracted)
Extents and exact grid spacing are automatically calculated by reading the fast, in-memory coordinate caches from the underlying `cfdb` dataset during the `Catalogue.register()` phase. These are stored in the RCG `user_meta` for fast spatial/temporal querying.

| Field | Type | Description |
|-------|------|-------------|
| bbox | list[float] | `[min_lon, min_lat, max_lon, max_lat]` derived from coordinates |
| time_start | str (ISO8601) | The first value of the `time` coordinate array |
| time_end | str (ISO8601) | The last value of the `time` coordinate array |
| dataset_type | str | `grid` or `ts_ortho` (auto-detected from cfdb metadata) |
| x_step | float | Automatically extracted from the x coordinate `step` value |
| y_step | float | Automatically extracted from the y coordinate `step` value |

### Immutability
The 10 Identity fields (feature through version) are immutable once a dataset is created. The State Metadata fields, however, are mutable and are updated via `cat.register()` as new data is appended to the underlying `cfdb` file.

### Data variable requirements
- **units** required on the primary data variable
- **standard_name** (CF convention) required on the primary data variable. The user must provide a valid CF standard name. Registration via `cat.register()` will fail if a valid standard name is missing or logically contradicts the `feature` class.
- CRS must be defined on every dataset

## Controlled Vocabularies

### Implementation: bundled data files + optional refresh

- Ship JSON files in `envlib/vocabularies/` for each CV
- Validate field values against bundled data at dataset creation time
- Provide a utility function to refresh from external APIs (ODM2 API and NERC Vocabulary Server P07 endpoint): `envlib.vocabularies.refresh()`
- The `variable` mapping utility will return a filtered list of valid CF `standard_name` options based on the provided ODM2 `variable` and ENVO `feature`, acknowledging that CF standard names are pre-coordinated and semantically dense.

### Vocabulary sources

| Field | Source | Entries | Bundled file |
|-------|--------|---------|--------------|
| variable | ODM2 variablename mapped to CF standard_names | ~996 | `variable.json` |
| aggregation_statistic | ODM2 aggregationstatistic (underscore_style) | ~18 | `aggregation_statistic.json` |
| method | ODM2 methodtype (underscore_style) | ~26 | `method.json` |
| feature | envlib-defined (mapped to ENVO URIs) | ~10-15 | `feature.json` |
| license | curated SPDX subset | ~10-15 | `license.json` |
| standard_name | CF Conventions (via NVS P07 SKOS collection) | ~4000+ | `standard_name.json` |
| product_code | free-form (suggestions in docs) | — | — |

### envlib-defined vocabularies

**feature** (envlib-defined, mapped to ENVO URIs for semantic interoperability):
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
# By default, if version is not provided, the catalogue should return the latest version
# of the dataset matching the other parameters.
results = cat.query(
    variable='air_temperature', 
    owner='NIWA',
    product_code='ERA5',
    spatial_resolution='1km',
    dataset_type='grid',
    bbox=[166, -47, 178, -34]
    # version='1' # Can be explicitly provided to get an older version
)

# Open directly from the entry — returns cfdb EDataset
ds = results[0].open()
ds = results[0].open(file_path='/custom/path.cfdb')  # override cache

# Register an existing remote dataset in an RCG.
# This computes the dataset_id from the 10 Identity fields.
# If it's a new dataset_id, it inserts it.
# If the dataset_id already exists, it acts as an UPSERT: it recalculates 
# the State Metadata (extents) and updates the RCG entry if the dataset has grown.
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
    product_code='ERA5',
    owner='NIWA',
    aggregation_statistic='average',
    frequency_interval='1H',
    utc_offset='+00:00',
    spatial_resolution='1km',
    version='2',
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

# Create coords and data vars
# Users can query the bundled mapping to find corresponding CF standard names
cf_names = envlib.vocabularies.get_cf_standard_names('air_temperature', feature='atmosphere') 

dv = ds.create.data_var.generic('temp', ('latitude', 'longitude', 'time'), dtype='float32')
dv.attrs['units'] = 'degC'
dv.attrs['standard_name'] = cf_names[0] # explicitly setting the mapped CF name

# ... write data via cfdb API ...
ds.close()

# Register — validates ALL requirements (metadata complete, CRS set, units/standard_name on primary var)
# Acts as insert or upsert based on dataset_id. Auto-extracts extents and exact grid spacing.
cat.register(remote_conn, rcg_remote_conn)
```

**Metadata class**:
- Properties for each field with CV validation on set
- `.to_dict()` returns a plain dict suitable for `ds.attrs.update()`
- `.dataset_id` computed property (blake2b hash of 10 core fields, only available when all 10 are set)
- Incremental or all-at-once construction

### 3. Vocabulary utilities

```python
from envlib import vocabularies

# List valid values for a field
vocabularies.list('variable')       # -> ['air_temperature', 'precipitation', ...]
vocabularies.list('feature')        # -> ['atmosphere', 'waterway', ...]
vocabularies.list('standard_name')  # -> ['air_temperature', 'precipitation_flux', ...]

# Check if a value is valid
vocabularies.is_valid('variable', 'air_temperature')  # -> True
vocabularies.is_valid('standard_name', 'air_temperature')  # -> True

# Get mapping from ODM2 variable & feature to a list of applicable CF standard names
vocabularies.get_cf_standard_names('temperature', feature='ocean') # -> ['sea_water_temperature', ...]

# Refresh from external APIs (ODM2 and NVS P07)
vocabularies.refresh()              # updates all ODM2-sourced and CF bundled files
vocabularies.refresh('variable')    # update just one
```

## Module Structure

```
envlib/
├── __init__.py              # public API: Catalogue, Metadata, version
├── catalogue.py             # Catalogue class, DatasetRef class
├── metadata.py              # Metadata class, dataset_id hashing, validation
├── vocabularies/
│   ├── __init__.py          # list(), is_valid(), refresh(), get_cf_standard_names()
│   ├── variable.json        # ODM2 variablename mapped to CF standard_names
│   ├── aggregation_statistic.json  # from ODM2 aggregationstatistic
│   ├── method.json          # from ODM2 methodtype
│   ├── feature.json         # envlib-defined (mapped to ENVO)
│   ├── standard_name.json   # CF Conventions (from NVS P07)
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
- `httpx` or `requests` — for fetching/refreshing vocabulary updates (e.g., ODM2 APIs, NVS P07 SKOS endpoints)

## Implementation Order

1. **Vocabularies module** — bundled JSON files (including mapped variables and CF standard names via NVS P07), validation functions, mapping utility, refresh utility
2. **Metadata module** — `Metadata` class with CV validation, dataset_id hashing, `.to_dict()`
3. **Catalogue module** — `Catalogue` class (RCG-backed), `DatasetRef` class with .open(), .datasets, .query(), .register() with full validation, extent extraction, and Upsert logic
4. **Tests** for each module
5. **Update `__init__.py`** with public API exports

## Verification

- `uv run pytest` — unit tests for:
  - dataset_id hashing is deterministic and consistent
  - Metadata validation rejects missing/invalid fields
  - Vocabulary validation accepts valid terms, rejects invalid
  - Vocabulary accurately filters applicable CF standard names based on variable and feature
  - Catalogue lists/queries/filters correctly
  - Catalogue properly extracts time/bbox extents and updates them on re-registration
  - Catalogue validation rejects datasets missing CF standard names or units on primary variables, or logically contradicting feature metadata
- Integration test: `Metadata.to_dict()` → `ds.attrs.update()` → verify metadata round-trips through cfdb .attrs
- Integration test: vocabulary refresh from ODM2 API / NVS P07 (network test, can be marked skip-if-offline)
