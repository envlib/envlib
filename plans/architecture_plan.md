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
| method | str | yes | envlib-defined (see method vocabulary) |
| product_code | str | yes | free-form (e.g., 'ERA5', 'VCSN') |
| owner | str | yes | free-form |
| aggregation_statistic | str | yes | CF cell_methods statistical subset |
| frequency_interval | str \| None | yes | pandas offset alias (e.g. 1H, 15min, D, M, MS, Y, 7D) or None for irregular |
| utc_offset | str | yes | canonical form `±HH:MM` (see utc_offset rules below) |
| spatial_resolution | str \| None | yes | `<number><unit>` with unit in `{m, km, deg}`, OR the literal `point` (for ts_ortho), OR `None` for irregular. See spatial_resolution rules below. |
| version | str | yes | format validation (e.g., 1, 1.1, 2026-03) |

**dataset_id**: A deterministic `blake2b(digest_size=12)` hash of these 10 Identity fields, hex-encoded. Computed internally. It strictly enforces uniqueness. Changing any of these fields fundamentally changes what the dataset represents, which requires generating a new dataset rather than updating an existing one.

**Canonical hash serialization**: Each identity field is serialized as its string value. `None` values (e.g., `frequency_interval=None` for irregular time series) are serialized as the literal string `"None"`. Fields are joined in the order listed in the table above using a single `\x1f` (ASCII unit separator) as the delimiter, then hashed. This rule is stable across implementations and must not change.

**Note**: "parameter" from tethysts is renamed to "variable" to align with ODM2 variablename. `spatial_resolution` captures the *nominal* resolution to provide stable identity grouping, mitigating floating-point inconsistencies from raw coordinate arrays. Explicit versioning allows the `product_code` to remain semantically clean while supporting distinct iterations of a dataset.

**owner semantics**: `owner` is the entity responsible for producing this specific dataset. Mirroring or redistributing unmodified data from another party does not confer ownership — the originator (e.g., ECMWF for ERA5) remains the owner. Transforming the data (bias correction, regridding, unit conversion, QC, etc.) produces a derivative dataset with a new owner; use `derived_from` (General Metadata) to link back to the source. The `license` and `attribution` values are defined by the owner and must reflect the owner's terms for this dataset — consumers and mirrors may not override them. This convention is social/governance, not technically enforced; future envlib moderation (if any) would address violations.

**utc_offset rules**:
- **Canonical form**: `±HH:MM`, always sign-prefixed, always with colon, always two-digit hour and minute (e.g., `+00:00`, `+12:00`, `-05:30`, `+12:45`). This is the form stored and hashed.
- **Accepted input shorthand**: `±HH` (e.g., `+12`) is accepted as user input and auto-expanded to `±HH:00` before storage and hashing.
- **Rejected**: `Z`, timezone names like `Pacific/Auckland`, any form with whitespace or without a sign.
- **Fixed offset only** — not a timezone. For DST-observing regions, providers should use standard time year-round (e.g., NZ = `+12:00`, not `+13:00`). Shifting aggregation boundaries with DST cannot be expressed as a single offset and is out of scope.
- **Semantics**: `utc_offset` defines the aggregation boundary for aggregated cadences (e.g., a `24H` mean aligns to midnight at the given offset). When `frequency_interval` is sub-daily or `None`, the offset is representational only — use `+00:00` unless there is a specific reason to do otherwise, to avoid spurious duplicate `dataset_id`s for semantically identical data.

**spatial_resolution rules**:
- **Canonical form**: `<number><unit>` with no separator between number and unit; units limited to `{m, km, deg}`. Numbers in standard decimal form (e.g., `0.25`, `1`, `500`). Examples: `0.25deg`, `1km`, `500m`, `30m`.
- **Special values**:
  - `point` — used for `ts_ortho` datasets where stations are single points rather than gridded.
  - `None` — used for datasets with irregular spatial resolution (adaptive-mesh grids, variable-density station networks, etc.). Hashed as the literal string `"None"` per the canonical hash serialization rule.
- **Rejected**: mixed separators (`0.25 deg`, `0.25_deg`), scientific notation (`25e-2deg`), unsupported units (`mm`, `cm`, `mile`, `nmi`), missing sign for negative numbers (none of the accepted units take negative values anyway).
- **Normalization**: post `.strip().lower()` (per Field normalization rules), values become compact and case-normalized (`0.25DEG` → `0.25deg`).

**Field normalization** (applies to Identity and General Metadata):
- **All fields**: whitespace is stripped (`.strip()`) before storage.
- **Free-form user-input Identity fields** (`owner`, `product_code`, `spatial_resolution`, `version`) are additionally lowercased before storage and hashing. This prevents `dataset_id` fragmentation from trivial case differences (e.g., `ERA5` vs `era5` vs `Era5`).
- **CV-constrained fields** (`feature`, `variable`, `method`, `aggregation_statistic`, `license`) are stored as their canonical CV value — no further lowercasing, since the CV itself defines the canonical case.
- **`frequency_interval`**: canonicalized via `pd.tseries.frequencies.to_offset(val).freqstr` to produce a stable string form (avoids pandas case-sensitivity pitfalls like `'M'` month-end vs `'MS'` month-start).
- **`utc_offset`**: canonicalized per the utc_offset rules above.
- **Free-form text General Metadata** (`attribution`, `description`): whitespace stripped only; no case normalization — these are human-readable text, not identifiers.

**Query normalization**: query kwarg values for queryable fields (Identity + CV fields) are normalized via `.strip().lower()` before matching against stored values. This lets users type `cat.query(variable='Air_Temperature', owner='NIWA')` and match stored `air_temperature` / `niwa`. Case-insensitive querying is a side effect of consistent normalization, not a special flag.

### 2. General Metadata
These fields do not affect identity. `license` and `attribution` are required at registration; the rest are optional.

| Field | Type | Derives dataset_id | Status | CV Source |
|-------|------|--------------------|--------|-----------|
| license | str | no | required | curated SPDX subset |
| attribution | str | no | required | free-form |
| description | str \| None | no | optional | free-form |
| derived_from | list[str] \| None | no | optional | list of existing `dataset_id`s |
| doi | str \| None | no | optional | DOI URL (e.g., `https://doi.org/10.xxxx/xxxx`) |

- **description** — free-form human-readable description of the dataset. Aids discoverability in the catalogue.
- **derived_from** — list of `dataset_id`s this dataset was computed from (reanalyses, QC'd products, ensembles, etc.). Enables machine-traversable lineage. Values are not validated against the catalogue at registration time — a `derived_from` entry may reference a dataset hosted in a different RCG or not yet registered.
- **doi** — citation DOI as a full URL. Format-validated on assignment but not resolved (no network call).

Non-queryable processing detail (algorithm, code version, parameters, QC thresholds, etc.) should be recorded in the CF `history` attribute on the cfdb dataset via `ds.attrs['history']`, not duplicated in envlib's metadata model. Other CF dataset-level attrs (`references`, `comment`, `source`, `institution`) remain available and are not modelled by envlib.

### 3. State Metadata (Auto-Extracted)
Extents and exact grid spacing are automatically calculated by reading the fast, in-memory coordinate caches from the underlying `cfdb` dataset during the `Catalogue.register()` phase. These are stored in the RCG `user_meta` for fast spatial/temporal querying.

| Field | Type | CRS | Description |
|-------|------|-----|-------------|
| bbox | list[float] | EPSG:4326 | `[min_lon, min_lat, max_lon, max_lat]` in WGS84 degrees. Reprojected from the dataset's native CRS on registration if needed. |
| time_start | str (ISO8601 UTC) | — | The first value of the `time` coordinate array, serialized as UTC ISO8601 (e.g., `2020-01-01T00:00:00Z`). |
| time_end | str (ISO8601 UTC) | — | The last value of the `time` coordinate array, serialized as UTC ISO8601. |
| dataset_type | str | — | `grid` or `ts_ortho` (auto-detected from cfdb metadata) |
| x_step | float | native | Automatically extracted from the x coordinate `step` value; stays in the dataset's native CRS units. Absent from State Metadata for `ts_ortho` datasets (no regular grid step). |
| y_step | float | native | Automatically extracted from the y coordinate `step` value; stays in the dataset's native CRS units. Absent from State Metadata for `ts_ortho` datasets. |

**bbox CRS**: the stored `bbox` is always in EPSG:4326 (WGS84 lat/lon), regardless of the dataset's native CRS. On registration, envlib reads the dataset's native CRS and coordinate extents and reprojects the bounding envelope to EPSG:4326 via `pyproj`. This is a coarse catalogue-level filter — it does not have to be a perfectly tight bound. Reprojecting the four corners of the native extent is sufficient; edge densification is not required. Consumers performing precise spatial filtering do so after opening the cfdb file, against the dataset's native coordinates.

**Step CRS**: `x_step` and `y_step` remain in the dataset's native CRS units (degrees for geographic, metres for projected, etc.) because they describe the physical grid spacing, which is meaningful only in the native projection.

**Time coordinate convention**: cfdb `time` coord values are `datetime64` (timezone-naive) and are interpreted as UTC instants by convention. Producers should always store time values in UTC regardless of the dataset's `utc_offset`. The `utc_offset` Identity field describes how to interpret aggregation boundaries (e.g., "daily mean aligned to local midnight") — it does NOT shift the stored time values. envlib serializes `time_start` / `time_end` as UTC ISO8601 with an explicit `Z` suffix so consumers can treat them unambiguously as absolute instants.

**Empty datasets**: Registration of empty datasets (datasets with no data arrays populated or zero-length time/geometry coordinates) is not permitted. `cat.register()` and `cat.publish()` will fail if they cannot extract valid State Metadata extents from the dataset.

### 4. Provenance Metadata (Auto-Set)
These fields are set automatically by the catalogue on registration. Some are immutable (set once at first insert); some are auto-updated on every `cat.register()` call. They are stored in the RCG `user_meta` but are NOT part of the `dataset_id` hash.

| Field | Type | Mutability | Description |
|-------|------|------------|-------------|
| created_at | str (ISO8601 UTC) | immutable | Timestamp of first successful `cat.register()` for this `dataset_id`. Used to determine the "latest" version when multiple versions match a query. |
| modified_at | str (ISO8601 UTC) | auto-updated | Timestamp of the most recent `cat.register()` call for this `dataset_id`. Updated on every register call (including re-registrations that recalculate State Metadata). Queryable via the catalogue for recency-based queries (e.g., "datasets updated in the last 7 days"). |

`created_at` is set once at first insert and preserved thereafter. `modified_at` is refreshed by the catalogue on each `cat.register()` call.

### Immutability
The 10 Identity fields (feature through version) are immutable once a dataset is created. `created_at` (Provenance) is also immutable — set once at first registration. The State Metadata fields and `modified_at` (Provenance) are mutable and are updated via `cat.register()` as new data is appended to the underlying `cfdb` file.

### Dataset lifecycle

envlib v1 deliberately omits explicit lifecycle states (`deprecated`, `sunset`, etc.) — these are redundant with other mechanisms already in the model:
- **Superseded versions** are handled by the version field and the `latest-by-created_at` query default. Older versions remain accessible via explicit `version=...` kwargs.
- **Staleness** is inferable from `modified_at` — consumers can judge whether a dataset is still being updated without a dedicated "sunset" status.

**Retraction** (removal of a dataset known to contain incorrect data) is handled in v1 by deleting the dataset entry from the catalogue and the underlying cfdb file from its remote. There is no tombstone.

**Possible future addition — retraction tombstone**: for datasets that have been externally cited (e.g., DOI-bearing published datasets), outright deletion leaves dead references. A future option would be to preserve the catalogue entry with a `status='retracted'` field and a `retraction_reason` in General Metadata, while still removing the underlying cfdb data. This is acknowledged as a future possibility if needed. Not committed for v1.

### Data variable requirements
- **Exactly one primary data variable per dataset.** The primary variable's name in the cfdb file must equal the `Metadata.variable` value (e.g., if `variable='air_temperature'`, the cfdb file must contain `ds['air_temperature']`). This makes the primary variable self-identifying — no separate `primary_variable` attribute is needed. Registration via `cat.register()` will fail if `meta.variable` is not present as a data variable in the cfdb file.
- **Ancillary variables** (QC flags, uncertainty estimates, counts, etc.) are permitted alongside the primary variable. They must be declared via the CF `ancillary_variables` attribute on the primary variable. Ancillary variable names are unconstrained (e.g., `air_temperature_qc`, `air_temperature_stderr`).
- **units** required on the primary data variable
- **standard_name** (CF convention) required on the primary data variable. The user must provide a valid CF standard name (validated against the bundled CF standard name list). Registration via `cat.register()` will fail if the standard_name is missing or not a valid CF term. envlib does not attempt to enforce semantic consistency between `standard_name` and `feature` (e.g., it will not reject `standard_name='sea_water_temperature'` paired with `feature='atmosphere'`) — the combinatorial space is too large to enforce reliably. Users who need to express detail beyond the ODM2 `variable` name (e.g., "at 2m") should encode that in the CF `standard_name`, not in the cfdb variable name.
- CRS must be defined on every dataset

### Station conventions for `ts_ortho` datasets

For `dataset_type='ts_ortho'`, each entry in the `geometry` point coord represents a physical station (or, more generally, an x/y location where observations or model outputs are recorded). envlib does not introduce a first-class "station" entity — stations are represented entirely within each cfdb file via **station attribute variables** aligned with the geometry coord. Cross-dataset station matching is enabled by a deterministic `station_id`.

**Terminology note**: "station attribute variables" (shape `(geometry,)`, describing each station) are distinct from CF **ancillary variables** (shape matching the primary data variable, describing QC / uncertainty / counts of each measurement; declared via the CF `ancillary_variables` attribute). Both use cfdb's `data_var` mechanism, but they serve different roles and are referred to separately throughout this document.

**Required station attribute variable:**

| Ancillary var | Type | Shape | Description |
|---------------|------|-------|-------------|
| `station_id` | str | `(geometry,)` | Deterministic hash of the station's 2D location. See derivation rule below. |

**station_id derivation rule**: `blake2b(WKB, digest_size=12).hex()`, where WKB is the 2D representation of the point geometry (x, y only) rounded to 5 decimal places in EPSG:4326 (to be roughly 1m). If the geometry coord contains 3D points `(x, y, z)`, the z coordinate is stripped for hashing. Same-x/y-different-z points therefore share a `station_id` — vertical separation at a single physical location is expressed via other mechanisms (see below), not via station identity.

This derivation guarantees that the same physical station receives the same `station_id` across every dataset that records it, enabling users to match stations across datasets.

**Optional envlib-recognized station attribute variables:**

| Ancillary var | Type | Shape | Description |
|---------------|------|-------|-------------|
| `station_name` | str | `(geometry,)` | Human-readable station name. |
| `surface_altitude` | float | `(geometry,)` | Height of the ground surface at each station above a reference datum (e.g., geoid, ellipsoid). CF `standard_name = surface_altitude`. Distinct from the measurement-axis coord below. |
| `operator` | str | `(geometry,)` | Station operator, when it differs from the dataset `owner`. |

Users may add any additional station attribute variables they need — envlib does not manage or validate them.

**Vertical measurement axis vs. per-station altitude**:
- When the *data itself* is resolved vertically (e.g., multi-depth borehole temperature, radiosonde profile, vertical thermistor chain), use a cfdb coord named `altitude`, `height`, or `depth` as appropriate. The coord name takes priority — it is the axis along which the data varies, and the data variable's shape includes this coord.
- For the per-station ground-level altitude (static metadata about where the station sits), use the `surface_altitude` station attribute variable described above. It is shaped `(geometry,)` and is NOT a coord.

This separation prevents name collisions between the measurement axis and the station metadata.

**Cross-dataset station correlation**: there is no first-class station registry and envlib does not provide catalogue-level station search. Because the `station_id` derivation is deterministic (same x/y → same hash), consumers can correlate stations across datasets by matching `station_id` values directly — e.g., open two datasets known to include the same station and align records by `station_id`. Spatial filtering within a dataset (bbox, nearest-point, within-radius, within-polygon) is handled via cfdb's native APIs on the opened dataset, not via envlib.

**Possible future extension — non-orthogonal (ragged) time series dataset type**: the current `ts_ortho` layout is orthogonal `(point, time)` — every station has a value (or fill) at every timestamp. For sampling campaigns where each station is visited on different days (truly ragged per-station time series), this produces mostly-empty arrays. The visual/conceptual clarity cost is real even though the space cost is usually trivial. A future addition could introduce a `ts_ragged` (or similarly named) `dataset_type` modeled as a 1D observation array with `(station, time)` indexing, matching CF's "indexed ragged array" Discrete Sampling Geometries convention. Gated on cfdb support for ragged array layouts. Not committed for v1.

## Controlled Vocabularies

### Implementation: bundled data files + optional refresh

- Ship JSON files in `envlib/vocabularies/` for each CV
- Validate field values against bundled data at dataset creation time
- Provide a utility function to refresh from external APIs (ODM2 API and NERC Vocabulary Server P07 endpoint): `envlib.vocabularies.refresh()`
- The `variable` mapping utility will return a filtered list of valid CF `standard_name` options based on the provided ODM2 `variable` and ENVO `feature`, acknowledging that CF standard names are pre-coordinated and semantically dense.

### Validation on change only (vocabulary evolution handling)

To avoid orphaning existing datasets when `vocabularies.refresh()` pulls an updated upstream vocabulary that has dropped or renamed terms, envlib validates CV-constrained metadata values only when they are being set or changed:

- **Identity Metadata** is validated at `Metadata` construction (first creation of a dataset). Because Identity fields cannot change for a given `dataset_id` (they derive the hash), they are never re-validated on subsequent `cat.register()` calls.
- **General Metadata** (e.g., `license`) is validated at construction. On re-registration, `cat.register()` reads current metadata from the cfdb file, compares field-by-field to the values already stored in the RCG, and validates only fields whose values differ.
- **On read** (`DatasetRef.metadata`, `cat.query(...)`, etc.) no CV validation is performed. Stored values are surfaced as-is. Queries match literal strings against stored values, not against the current bundled CV.

This means a dataset created in 2026 with `method='total_count'` (valid at that time) remains queryable and re-registerable indefinitely, even if ODM2 later removes or renames the term.

**Known limitation — query fragmentation**: if an upstream vocabulary renames a term (e.g., `total_count` → `count`), datasets created before and after the rename will use different strings for the same concept. A query on either term will miss datasets registered under the other. envlib does not address this in v1.

**Possible future mitigation — alias table**: a maintained alias map within envlib's bundled CV data could allow queries on either the old or new term to match both. This is acknowledged as a future implementation option if the fragmentation problem becomes painful in practice. Not committed for v1.

### Vocabulary sources

| Field | Source | Entries | Bundled file |
|-------|--------|---------|--------------|
| variable | ODM2 variablename mapped to CF standard_names | ~996 | `variable.json` |
| aggregation_statistic | CF cell_methods statistical values (underscore_style) | ~10 | `aggregation_statistic.json` |
| method | envlib-defined (ported from tethys) | 7 | `method.json` |
| feature | envlib-defined (mapped to ENVO URIs) | ~10-15 | `feature.json` |
| license | curated SPDX subset + envlib extensions for common non-SPDX open-access data licenses | ~10-20 | `license.json` |
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

**license** (curated SPDX subset + envlib extensions, restricted to open-access data licenses):
- `CC-BY-4.0`, `CC-BY-SA-4.0`, `CC-BY-NC-4.0`, `CC-BY-NC-SA-4.0`
- `CC0-1.0` (public domain dedication)
- `ODbL-1.0` (Open Data Commons)
- `CC-BY-3.0`, `CC-BY-SA-3.0`
- **envlib extensions** — non-SPDX open-access data licenses commonly required by data owners (e.g., `Copernicus-1.0` for ECMWF/Copernicus products). Added as needed to accommodate real-world licensing that does not map cleanly to SPDX. Only open-access licenses are accepted — proprietary or non-open licenses are rejected.
- (refine during implementation)

**product_code** (free-form, suggested values documented):
- `raw_data`, `quality_controlled`, `simulation`, `forecast`, `reanalysis`, etc.
- No validation — just documented suggestions

**aggregation_statistic** (CF cell_methods statistical subset):
- Values are drawn from the statistical subset of the CF Conventions `cell_methods` vocabulary. Although CF applies `cell_methods` at the coordinate level (e.g., `time: mean`) and supports non-statistical qualifiers (e.g., `where sea`), envlib uses only the dataset-level statistical terms.
- Accepted values: `point` (instantaneous, no aggregation), `mean`, `sum`, `maximum`, `minimum`, `median`, `mode`, `mid_range`, `variance`, `standard_deviation`, `range`.
- No envlib extensions needed — CF's vocabulary covers all expected cases, including instantaneous snapshots (via `point`).

**method** (envlib-defined, ported from tethys for migration continuity):

| Value | Definition |
|-------|------------|
| `derivation` | A method for creating results by simple calculations from field activities, sample analyses, or sensor recordings. |
| `estimation` | A method for creating results by rough approximation or professional judgement. Does not use an analytical or numerical model. |
| `field_activity` | A method for creating results by performing an activity in the field at or on a sampling feature. Includes manually-operated instruments (e.g., handheld probes, manual gauging, field surveys) — anything requiring a human at the measurement location. |
| `simulation` | A method for creating results by running an analytical or numerical model. Generally more complex and/or more uncertain than derivations. Used for climate model runs, reanalyses (e.g., ERA5), and other model outputs. |
| `sample_analysis` | A method for ex situ analysis of a sample using an instrument, typically in a laboratory, for the purpose of measuring properties of a sample. |
| `sensor_recording` | A method for creating results by independent, automated sensor measurements without direct human interaction at the sensor during the measurement. Includes in-situ data loggers and remote sensing. |
| `forecast` | A type of simulation to predict the future. Kept distinct from `simulation` so consumers can filter forecasts from historical model runs. |

This vocabulary is not sourced from an external standard — envlib maintains it directly. It is deliberately small; additions are made only when a genuine gap emerges. The `vocabularies.refresh()` utility has no effect on this field (no upstream source to refresh from).

## Public API

### 1. Catalogue — RCG-backed dataset discovery and access

The Catalogue wraps one or more RCGs. Each dataset entry is a `DatasetRef` object that knows its metadata and how to open itself.

```python
import envlib

# Connect to one or more RCGs
cat = envlib.Catalogue(
    remotes=[remote1, remote2, ...],  # S3Connection or dict or URL
    cache='~/.envlib/cache',          # cache dir passed through to the cfdb/ebooklet layer
)

# All datasets — list of DatasetRef objects
cat.datasets
# [{'feature': 'atmosphere', 'variable': 'air_temperature', 'owner': 'NIWA', ...},
#  {'feature': 'waterway', 'variable': 'discharge', 'owner': 'NIWA', ...}]
# (DatasetRef.__repr__ displays as a metadata dict)

# Query with kwargs filtering (returns filtered list of DatasetRef).
# All kwargs are AND'd together; a list value means "any of these" (OR within the field).
# Query values for queryable fields are normalized (.strip().lower()) before matching.
# By default, if version is not provided, the catalogue returns the latest version
# of each matching dataset — "latest" is determined by the `created_at` Provenance
# Metadata field (most recently registered wins). An explicit version=... kwarg
# overrides the latest-by-default behaviour and pins the query to that exact version.
results = cat.query(
    variable='air_temperature',
    owner=['NIWA', 'CSIRO'],             # list means "any of these"
    product_code='ERA5',
    spatial_resolution='1km',
    dataset_type='grid',

    # Spatial filter (mutually exclusive; all in EPSG:4326):
    bbox=[166, -47, 178, -34],           # [lon_min, lat_min, lon_max, lat_max]; intersects
    # within_radius=((174.0, -41.0), 50), # ((lon, lat), km); great-circle distance
    # geometry=shapely.Polygon(...),       # shapely geometry; intersects

    # Temporal filter (overlaps semantics; either kwarg is optional):
    start_date='2020-01-01',
    end_date='2021-01-01',

    # version='1',                       # pin to a specific version; default = latest by created_at
)

# Open directly from the entry — returns cfdb EDataset
ds = results[0].open()
ds = results[0].open(file_path='/custom/path.cfdb')  # override cache

# Validate a local cfdb file against envlib's metadata and data variable requirements.
# Inspects the dataset's ds.attrs (Metadata), primary data variable, CRS, ancillary
# variables (QC/uncertainty), and station attribute variables (for ts_ortho: station_id).
# Extracts State Metadata. No RCG or S3 changes — suitable for dry runs and CI checks.
# Raises on invalid input.
cat.validate(local_cfdb_path='data.cfdb')

# Publish a local cfdb file to remote S3 and register it in the catalogue.
# This is the primary flow for producing new datasets or appending new data.
# Internally:
#   1. validate the local cfdb
#   2. compute dataset_id and extract State Metadata
#   3. write the entry to the local RCG (insert or upsert on dataset_id)
#   4. push the cfdb data to its remote S3 location
#   5. push the RCG to its remote
# The cfdb data is pushed BEFORE the RCG commit so the catalogue never references
# incomplete remote data.
cat.publish(
    local_cfdb_path='data.cfdb',
    remote_conn=s3_conn,                # where the cfdb data lives on S3
    rcg_remote_conn=rcg_conn,           # the RCG's remote
    num_groups=100,                     # passed through to open_edataset
    # ... any other open_edataset kwargs ...
)

# Register an already-remote cfdb file with the catalogue.
# Use this when the cfdb was pushed to S3 outside of cat.publish() — e.g., legacy
# data being added to the catalogue for the first time, or data pushed by a pipeline
# that manages the S3 side separately. Same validation and insert/upsert logic as
# publish, but skips the cfdb push step.
cat.register(
    remote_conn=s3_conn,
    rcg_remote_conn=rcg_conn,
    num_groups=100,                     # passed through to open_edataset
)
```

**Publish failure handling**: if `cat.publish()` fails after the cfdb push succeeds but before the RCG push completes, the data is on remote S3 but not yet advertised in the remote catalogue. Re-running `cat.publish()` is safe — the cfdb push is idempotent (same data), and the RCG entry write is an upsert on `dataset_id`.

**Cache management**: envlib does not implement its own cache layer. The `cache=` path is passed through to the underlying `cfdb` / `ebooklet` / `booklet` stack, which already handles chunk-level pulling, local-vs-remote synchronisation, and staleness detection. Eviction policy, size limits, pinning, and cache inspection (if any) are the lower layer's concern — envlib does not duplicate these APIs. Users who need to reclaim disk can manage the cache directory manually.

**Query semantics (v1)**:
- **Spatial**: `bbox`, `within_radius`, and `geometry` are mutually exclusive — pass at most one. All use *intersects* semantics against the dataset's stored `bbox` State Metadata. All query geometries must be in EPSG:4326.
- **Temporal**: `start_date` and `end_date` use *overlaps* semantics against the dataset's `[time_start, time_end]` range. Either kwarg is optional (open-bounded queries are supported).
- **Set membership**: a list value matches any of the listed values (OR within the field); scalars are exact match. Kwargs across fields are AND'd together.
- **Case**: query values are normalized per the Field normalization rules before matching. Matching is effectively case-insensitive for queryable fields.
- **Pattern matching**: exact match only. No glob, substring, or regex filtering.
- **`modified_at` queries**: not supported.
- **Pagination / ordering**: `cat.query()` returns all matching entries as a list with no guaranteed ordering and no result limit. Callers sort or paginate client-side if needed.

**Possible future extension — regex pattern matching in queries**: explicit regex predicates for fields like `product_code` (e.g., to match all `ERA*` variants with a single query). Deferred from v1 for API simplicity. If added, regex is the preferred syntax over glob or substring because it is explicit and unambiguous. Not committed for v1.

**Possible future extension — `modified_at` queries**: recency-based filtering on the `modified_at` Provenance field (e.g., `modified_from` / `modified_to` kwargs, or a `modified_since=timedelta(days=7)` form) to answer queries like "datasets updated in the last week." Straightforward additive change if needed. Not committed for v1.

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
    method='simulation',
    product_code='ERA5',
    owner='NIWA',
    aggregation_statistic='point',
    frequency_interval='1H',
    utc_offset='+00:00',
    spatial_resolution='0.25deg',
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

# The primary data variable's name must match meta.variable
dv = ds.create.data_var.generic('air_temperature', ('latitude', 'longitude', 'time'), dtype='float32')
dv.attrs['units'] = 'degC'
dv.attrs['standard_name'] = cf_names[0]  # explicitly setting the mapped CF name

# Optional ancillary variables — declared via CF ancillary_variables attribute on the primary
qc = ds.create.data_var.generic('air_temperature_qc', ('latitude', 'longitude', 'time'), dtype='int8')
dv.attrs['ancillary_variables'] = 'air_temperature_qc'

# ... write data via cfdb API ...
ds.close()

# Publish the local cfdb to its remote S3 location and register it in the catalogue.
# Validates all requirements, computes dataset_id, extracts State Metadata (bbox in
# EPSG:4326, time range, grid steps), writes the catalogue entry, then pushes the
# cfdb data and the RCG (in that order).
cat.publish(
    local_cfdb_path='data.cfdb',
    remote_conn=remote_conn,
    rcg_remote_conn=rcg_remote_conn,
)
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
│   ├── aggregation_statistic.json  # CF cell_methods statistical subset
│   ├── method.json          # envlib-defined (ported from tethys)
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
  - Catalogue validation rejects datasets missing CF standard names or units on primary variables
- Integration test: `Metadata.to_dict()` → `ds.attrs.update()` → verify metadata round-trips through cfdb .attrs
- Integration test: vocabulary refresh from ODM2 API / NVS P07 (network test, can be marked skip-if-offline)
