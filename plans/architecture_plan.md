# envlib Design Plan

## Context

envlib needs a well-defined API for creating, cataloguing, and accessing standardized environmental datasets. The goal is to enforce a unified metadata standard (drawing from ODM2, CF conventions, and OSM concepts) so scientists can discover and share cfdb datasets through a distributed catalogue built on ebooklet's RemoteConnGroup (RCG).

## Dataset Metadata Model

The metadata model is strictly divided into two categories: **Identity Metadata** (immutable characteristics defining what the dataset is) and **State Metadata** (mutable characteristics describing the data's current extents or volume).

### 1. Identity Metadata (Required)
These 11 fields define the core nature of the dataset. They are stored in both the RCG entry and cfdb `ds.attrs` (see Metadata storage and source of truth below). **Values are normalized before storage and hashing per the Field normalization rules below** — notably, free-form user-input fields (`owner`, `product_code`, `version`) are lowercased and slug-validated, `spatial_resolution` is lowercased under its own stricter grammar, all fields are whitespace-stripped, and `frequency_interval` / `utc_offset` / `spatial_resolution` have their own canonicalization rules. CV-constrained fields (`feature`, `variable`, `method`, `processing_level`, `aggregation_statistic`) are stored as their canonical CV value.

| Field | Type | Derives dataset_id | CV Source |
|-------|------|--------------------|-----------|
| feature | str | yes | envlib's own (mapped to ENVO URIs) |
| variable | str | yes | ODM2 variablename (underscore_style) |
| method | str | yes | envlib-defined (see method vocabulary) |
| product_code | str \| None | yes | free-form slug naming the production line (e.g., 'era5-land', 'stream_depletion_method_1'), or None — see product_code rules below |
| processing_level | str | yes | envlib-defined (see processing_level vocabulary) |
| owner | str | yes | free-form slug |
| aggregation_statistic | str | yes | CF cell_methods statistical subset |
| frequency_interval | str \| None | yes | envlib-defined frequency code (see frequency_interval vocabulary) or None for irregular |
| utc_offset | str | yes | canonical form `±HH:MM` (see utc_offset rules below) |
| spatial_resolution | str \| None | yes | `<number><unit>` with unit in `{m, km, deg}`, OR the literal `point` (for ts_ortho), OR `None` for irregular. See spatial_resolution rules below. |
| version | str | yes | format validation (e.g., 1, 1.1, 2026-03) |

**dataset_id**: A deterministic `blake2b(digest_size=12)` hash of these 11 Identity fields, hex-encoded. Computed internally. It strictly enforces uniqueness. Changing any of these fields fundamentally changes what the dataset represents, which requires generating a new dataset rather than updating an existing one.

**Canonical hash serialization**: Each identity field is serialized as its string value. `None` values (`frequency_interval=None` for irregular time series, `spatial_resolution=None`, `product_code=None`) are serialized as the literal string `"None"`. Fields are joined using a single `\x1f` (ASCII unit separator) as the delimiter; the joined string is encoded as **UTF-8** and hashed with a keyless blake2b — the full construction is `blake2b('\x1f'.join(fields).encode('utf-8'), digest_size=12).hexdigest()` (no `key`, `salt`, or `person`). Note the capital-N `"None"` sentinel cannot collide with stored values: free-form fields are lowercased before hashing, `product_code='none'` is rejected outright (see product_code rules), and `frequency_interval` / `spatial_resolution` reject every casing of `none` by grammar (not a valid frequency code; not valid `<number><unit>`/`point`) — so all three nullable fields are sentinel-safe.

**Field order (MUST NOT change)**: the 11 Identity fields are concatenated in this exact order before hashing:

1. `feature`
2. `variable`
3. `method`
4. `product_code`
5. `processing_level`
6. `owner`
7. `aggregation_statistic`
8. `frequency_interval`
9. `utc_offset`
10. `spatial_resolution`
11. `version`

Changing the field order — or any other aspect of this serialization rule (the `None` literal, the `\x1f` delimiter, the UTF-8 encoding, the keyless blake2b construction, the digest size) — would produce different `dataset_id`s for the same logical dataset, breaking every existing entry in every catalogue. This rule is stable across implementations and versions and must not change. The order is hash-internal only — user-facing display order (reprs, docs, web UIs) is independent and free to differ.

**series_id**: a companion hash computed with the same serialization scheme and field order but with `version` omitted (10 fields). It identifies the dataset *series* across versions and is stored in the RCG entry and `ds.attrs` alongside `dataset_id`. It defines the grouping for the query default "latest version of each matching dataset": within a series, latest = greatest `created_at`. Known caveat: `created_at` records *first registration*, so back-filling an older version after a newer one makes the back-filled version "latest" — documented, not solved, in v1; pin `version=` explicitly in queries when this matters.

**Note**: "parameter" from tethysts is renamed to "variable" to align with ODM2 variablename. `spatial_resolution` captures the *nominal* resolution to provide stable identity grouping, mitigating floating-point inconsistencies from raw coordinate arrays. Explicit versioning allows the `product_code` to remain semantically clean while supporting distinct iterations of a dataset. `processing_level` carries the quality-control state that tethys crammed into `product_code` (see tethys → envlib migration notes below).

**owner semantics**: `owner` is the entity responsible for producing this specific dataset. Mirroring or redistributing unmodified data from another party does not confer ownership — the originator (e.g., ECMWF for ERA5) remains the owner. Transforming the data (bias correction, regridding, unit conversion, QC, etc.) produces a derivative dataset with a new owner; use `derived_from` (General Metadata) to link back to the source. The `license` and `attribution` values are defined by the owner and must reflect the owner's terms for this dataset — consumers and mirrors may not override them. This convention is social/governance, not technically enforced; future envlib moderation (if any) would address violations.

**utc_offset rules**:
- **Canonical form**: `±HH:MM`, always sign-prefixed, always with colon, always two-digit hour and minute (e.g., `+00:00`, `+12:00`, `-05:30`, `+12:45`). This is the form stored and hashed. `-00:00` is normalized to `+00:00`.
- **Accepted input shorthand**: `±HH` (e.g., `+12`) is accepted as user input and auto-expanded to `±HH:00` before storage and hashing.
- **Rejected**: `Z`, timezone names like `Pacific/Auckland`, any form with whitespace or without a sign, and out-of-range values — the offset must lie within `[-12:00, +14:00]` with minutes in `{00, 15, 30, 45}` (covers all real-world offsets; `+24:00` and `+13:60` are invalid input, not distinct identities).
- **Fixed offset only** — not a timezone. For DST-observing regions, providers should use standard time year-round (e.g., NZ = `+12:00`, not `+13:00`). Shifting aggregation boundaries with DST cannot be expressed as a single offset and is out of scope.
- **Semantics**: `utc_offset` defines the aggregation boundary for aggregated cadences (e.g., a daily mean aligns to midnight at the given offset). The offset is semantically significant whenever `offset mod frequency_interval != 0` — including sub-daily cadences with non-commensurate offsets (hourly means at `+05:30` or `+12:45` produce bins shifted relative to `+00:00`). When `offset mod frequency_interval == 0` (the binning is identical to UTC) or `frequency_interval` is `None`, the offset has no semantic effect — and the `Metadata` class **enforces** this rather than leaving it as guidance: for fixed-duration cadences it computes the modulo and automatically normalizes the offset to `+00:00` when it divides evenly (likewise when `frequency_interval` is `None`), so semantically identical data cannot mint spurious duplicate `dataset_id`s. For calendar cadences (`month`, `year`, and any future non-fixed-duration codes) `offset mod frequency_interval` is not defined and the offset is **always retained** — any nonzero offset shifts calendar boundaries.

**spatial_resolution rules**:
- **Canonical form**: `<number><unit>` with no separator between number and unit; units limited to `{m, km, deg}`. The numeric part has **exactly one spelling per value**, enforced by grammar: `(0|[1-9][0-9]*)(\.[0-9]*[1-9])?` — a leading digit is required (`0.25`, not `.25`), no redundant leading zeros (`0.25`, not `00.25`), no trailing decimal point (`1`, not `1.`), and no trailing fractional zeros (`0.25`, not `0.250`; `1`, not `1.0`). Examples: `0.25deg`, `1km`, `500m`, `30m`.
- **Special values**:
  - `point` — used for `ts_ortho` datasets where stations are single points rather than gridded. (Unrelated to `aggregation_statistic='point'`, which means instantaneous sampling — the two fields are independent, and a `ts_ortho` dataset can legitimately carry both.)
  - `None` — used for datasets with irregular spatial resolution (adaptive-mesh grids, variable-density station networks, etc.). Hashed as the literal string `"None"` per the canonical hash serialization rule.
- **Rejected**: non-canonical numeric spellings (`.25deg`, `00.25deg`, `0.250deg`, `1.0km`, `1.km`) — **rejected, not normalized**: identity inputs must be exact, and rejection carries zero canonicalization-bug risk; mixed separators (`0.25 deg`, `0.25_deg`), scientific notation (`25e-2deg`), unsupported units (`mm`, `cm`, `mile`, `nmi`), missing sign for negative numbers (none of the accepted units take negative values anyway).
- **Normalization**: only `.strip().lower()` (per Field normalization rules) — case and whitespace normalize (`0.25DEG` → `0.25deg`); the numeric part is never rewritten, only validated against the grammar above.

**product_code rules**:
- **Meaning**: a producer-chosen slug naming the *production line* — the thing that distinguishes datasets which would otherwise share an identity. For published products this is the product name (e.g., `era5-land`, `vcsn`); for in-house derivations it is an algorithm/variant slug (e.g., `stream_depletion_method_1`). Rule of thumb: if two of your datasets would otherwise get the same `dataset_id`, `product_code` is where you say how they differ.
- **Optional**: `None` is allowed (hashed as the literal `"None"`) and is the expected value for plain observational collections with no product identity (e.g., a council's station network).
- **Grammar**: `[a-z0-9._-]+` after lowercasing (per Field normalization) — no whitespace. The literal value `none` is rejected to avoid confusion with the `None` sentinel.
- **Processing/QC state does NOT belong here** — that axis is `processing_level`. (tethys overloaded `product_code` with values like `raw_data` / `quality_controlled_data`; see the migration notes.)

**version rules**: a free-form slug (lowercased, `[a-z0-9._-]+`; e.g., `1`, `1.1`, `2026-03`). **The string is the identity** — `1`, `1.0`, and `01` are three different `dataset_id`s; envlib does not numerically normalize versions. Pick one spelling convention per series and keep it: re-registering "v1" as `1.0` silently forks the series.

**Field normalization** (applies to Identity and General Metadata):
- **All fields**: whitespace is stripped (`.strip()`) before storage.
- **Free-form user-input Identity fields** (`owner`, `product_code`, `spatial_resolution`, `version`) are additionally lowercased before storage and hashing. This prevents `dataset_id` fragmentation from trivial case differences (e.g., `ERA5` vs `era5` vs `Era5`).
- **Slug grammar**: `owner`, `product_code`, and `version` must match ASCII `[a-z0-9._-]+` after lowercasing (`re.fullmatch(r'[a-z0-9._-]+', value)`, no Unicode flags) — no whitespace or control characters. **Non-ASCII input is rejected up front, before lowercasing**, so no locale- or Unicode-dependent case mapping (Turkish `İ` and friends) ever reaches the hash. (The grammar also protects the `\x1f` hash delimiter; `spatial_resolution` has its own stricter grammar above.)
- **CV-constrained fields** (`feature`, `variable`, `method`, `processing_level`, `aggregation_statistic`, `license`) are stored as their canonical CV value — no further lowercasing, since the CV itself defines the canonical case.
- **`frequency_interval`**: must be one of envlib's own frequency codes (see the frequency_interval vocabulary) — exactly one canonical spelling per cadence, with a small closed alias table mapping accepted input synonyms to canonical (e.g. `24h` → `day`; see the frequency_interval vocabulary). envlib deliberately does NOT delegate canonicalization to pandas offset aliases: pandas' canonical spellings changed across versions (`'H'`→`'h'`, `'M'`→`'ME'` in pandas 2.2), and equivalent inputs (`'60min'` vs `'1h'`) don't normalize to each other — either property would destabilize `dataset_id`. (Verified empirically 2026-07-02 against pandas 2.1.4 / 2.2.3 / 3.0.3: the old aliases hard-error in 3.x, and `'15min'` / `'Y'` canonical forms also shifted across versions.)
- **`utc_offset`**: canonicalized per the utc_offset rules above.
- **Free-form text General Metadata** (`attribution`, `description`): whitespace stripped only; no case normalization — these are human-readable text, not identifiers.

**Query normalization**: query kwarg values for queryable fields (Identity + CV fields) are normalized via `.strip().lower()` and matched against the **lowercased** stored value (`stored.lower() == query.lower()`) — lowering only the query side would silently never match CVs whose canonical case is mixed (`license='CC-BY-4.0'` → query `cc-by-4.0` vs stored `CC-BY-4.0`). CVs must therefore contain no case-insensitively colliding entries (none do). This lets users type `cat.query(variable='Air_Temperature', owner='NIWA')` and match stored `air_temperature` / `niwa`. Case-insensitive querying is a side effect of consistent normalization, not a special flag.

### 2. General Metadata
These fields do not affect identity. `license` and `attribution` are required at registration; the rest are optional.

| Field | Type | Derives dataset_id | Status | CV Source |
|-------|------|--------------------|--------|-----------|
| license | str | no | required | curated SPDX subset + envlib extensions (open-access data licenses only) |
| attribution | str | no | required | free-form |
| description | str \| None | no | optional | free-form |
| derived_from | list[str] \| None | no | optional | list of `dataset_id`s and/or DOI URLs |
| doi | str \| None | no | optional | DOI URL (e.g., `https://doi.org/10.xxxx/xxxx`) |

- **description** — free-form human-readable description of the dataset. Aids discoverability in the catalogue.
- **derived_from** — list of parent datasets this dataset was computed from (reanalyses, QC'd products, ensembles, etc.). Enables machine-traversable lineage. Each entry is either:
  - a `dataset_id` — a 24-character hex string referencing an envlib dataset (in this or another RCG); may reference a dataset not yet registered.
  - a DOI URL — e.g., `https://doi.org/10.24381/cds.adbb2d47`, for referencing externally-published datasets that never lived in an RCG (e.g., the original ECMWF ERA5 as the parent of an envlib-derived bias-corrected product).
  
  Entries are distinguished by format (DOI URLs start with `https://doi.org/`; dataset_ids are 24-char hex). Neither form is resolved or validated against any external service at registration time — no network call is made; envlib only checks format. Caveat: `series_id` and `station_id` share the same 24-hex format, so a mis-pasted id of the wrong type is format-valid and undetectable — take care that `derived_from` entries are `dataset_id`s specifically.
- **doi** — citation DOI as a full URL. Format-validated on assignment but not resolved (no network call).

Non-queryable processing detail (algorithm, code version, parameters, QC thresholds, etc.) should be recorded in the CF `history` attribute on the cfdb dataset via `ds.attrs['history']`, not duplicated in envlib's metadata model. Other CF dataset-level attrs (`references`, `comment`, `source`, `institution`) remain available and are not modelled by envlib.

### 3. State Metadata (Auto-Extracted)
Extents and exact grid spacing are automatically calculated by reading the fast, in-memory coordinate caches from the underlying `cfdb` dataset during the `Catalogue.register()` phase. These are stored in the RCG entry for fast spatial/temporal querying (envlib passes them explicitly at registration — see RCG keying and entry contents). Cost note: for an already-remote dataset, extraction requires pulling the attrs and all coordinate chunks (not data-variable chunks) from S3 — cheap for most datasets, noticeable for very large coordinates.

| Field | Type | CRS | Description |
|-------|------|-----|-------------|
| bbox | list[float] | EPSG:4326 | `[min_lon, min_lat, max_lon, max_lat]` in WGS84 degrees. Reprojected from the dataset's native CRS on registration if needed. |
| time_start | str (ISO8601 UTC) | — | The first value of the `time` coordinate array, serialized as UTC ISO8601 (e.g., `2020-01-01T00:00:00Z`). |
| time_end | str (ISO8601 UTC) | — | The last value of the `time` coordinate array, serialized as UTC ISO8601. |
| dataset_type | str | — | `grid` or `ts_ortho` (auto-detected from cfdb metadata) |
| x_step | float | native | Automatically extracted from the x coordinate `step` value; stays in the dataset's native CRS units. Absent from State Metadata for `ts_ortho` datasets (no regular grid step). |
| y_step | float | native | Automatically extracted from the y coordinate `step` value; stays in the dataset's native CRS units. Absent from State Metadata for `ts_ortho` datasets. |

**bbox CRS**: the stored `bbox` is always in EPSG:4326 (WGS84 lat/lon), regardless of the dataset's native CRS. On registration, envlib reprojects the native extent to EPSG:4326 using `pyproj.Transformer.transform_bounds(..., densify_pts=21)` — NOT a four-corner reprojection, which under-covers for curved-edge projections (polar stereographic, wide Lambert conformal) and would make the coarse filter *miss* datasets. The bbox is a coarse catalogue-level filter — it does not have to be a perfectly tight bound, but it must never be smaller than the true extent. Consumers performing precise spatial filtering do so after opening the cfdb file, against the dataset's native coordinates.

**Antimeridian and longitude convention**: stored longitudes are normalized to `[-180, 180]` (datasets with native 0–360 grids, e.g. ERA5, are normalized on registration). Bboxes crossing the antimeridian use the GeoJSON convention: `min_lon > max_lon` means the box crosses 180° (e.g., a domain spanning 166E–172W is `[166, lat0, -172, lat1]`, not a near-global box). Query-side `intersects` logic must implement this convention. `transform_bounds` emits it when reprojecting from a genuinely different (projected) CRS — but for **native-geographic sources it is an identity no-op**: a native 0–360 grid (ERA5) passes through unchanged, neither wrapped to `[-180, 180]` nor converted to the convention. envlib therefore applies its own longitude normalization after extent extraction: wrap longitudes into `[-180, 180]` **preserving the crossing structure** — a regional 170°E–190°E grid stores `[170, lat0, -170, lat1]` (`min_lon > max_lon`), NOT the naive min/max of the wrapped corners (which would yield a wrong near-global box); a full-globe 0–360 source stores `[-180, lat0, 180, lat1]`.

**Step CRS**: `x_step` and `y_step` remain in the dataset's native CRS units (degrees for geographic, metres for projected, etc.) because they describe the physical grid spacing, which is meaningful only in the native projection.

**Irregular grids**: a `grid` dataset whose x/y coordinate has no regular cfdb `step` (`step=None` — irregular spacing) stores `x_step`/`y_step` as absent, consistent with `spatial_resolution=None` for the same datasets.

**Time coordinate convention**: cfdb `time` coord values are `datetime64` (timezone-naive) and are interpreted as UTC instants by convention. Producers should always store time values in UTC regardless of the dataset's `utc_offset`. The `utc_offset` Identity field describes how to interpret aggregation boundaries (e.g., "daily mean aligned to local midnight") — it does NOT shift the stored time values. envlib serializes `time_start` / `time_end` as UTC ISO8601 with an explicit `Z` suffix so consumers can treat them unambiguously as absolute instants — at whole-second precision when the value has no sub-second component (the normal case), otherwise with a fractional-second suffix, trailing zeros stripped (e.g., `2020-01-01T00:00:00.5Z`). Not hashed; the format only needs to be deterministic for query stability.

**Timestamp convention (interval start)**: for aggregated data (`aggregation_statistic` other than `point`), each `time` value marks the **start** of its aggregation interval. For `point` (instantaneous) data, the value is simply the instant of measurement. This convention is global and unconditional — it is also why envlib's frequency codes need no start/end anchoring variants (pandas `M` vs `MS`). Closed-edge semantics (whether the boundary sample belongs to the earlier or later bin — tethys used right-closed bins for cumulative statistics, left-closed otherwise) are NOT modelled by envlib metadata.

**Every dataset has a time coordinate**: all envlib datasets MUST have a `time` coord with at least one value — enforced by `cat.validate()` / `cat.register()`. Quasi-static data (DEMs, land-cover maps, soil maps) is represented as a time series with one (or few) timestamps: the timestamp marks the start of the data's validity (e.g., survey or reference date), and successive revisions are appended as new time slices. There is no separate "static" dataset concept.

**Temporal query caveat**: temporal filters match recorded timestamps, not validity periods. A single-timestamp DEM registered at 2013 is a zero-width interval — a `start_date='2020-01-01'` overlaps query will not return it even though the terrain may still be current. Do not temporally filter quasi-static features; "valid until superseded" semantics are deliberately not modelled in v1.

**Empty datasets**: Registration of empty datasets (datasets with no data arrays populated or zero-length time/geometry coordinates) is not permitted. `cat.register()` and `cat.publish()` will fail if they cannot extract valid State Metadata extents from the dataset. A missing `time` coord is likewise a registration failure (see above).

### 4. Provenance Metadata (Auto-Set)
These fields are set automatically by the catalogue on registration. Some are immutable (set once at first insert); some are auto-updated by `cat.register()`. They are stored in the RCG entry but are NOT part of the `dataset_id` hash.

| Field | Type | Mutability | Description |
|-------|------|------------|-------------|
| created_at | str (ISO8601 UTC) | immutable | Timestamp of first successful `cat.register()` for this `dataset_id`. Used to determine the "latest" version when multiple versions match a query. |
| modified_at | str (ISO8601 UTC) | auto-updated | Timestamp of the most recent `cat.register()` call **that changed the stored entry** (State Metadata, General Metadata, or connection details). No-op re-registrations do not bump it, so it remains a meaningful recency signal. (Not queryable in v1 — see Query semantics.) |
| data_url | str \| None | auto-updated | Public HTTP(S) URL pointing to the cfdb file on the remote, if the `remote_conn.db_url` is set on the `S3Connection` at registration. Intended to let users view dataset metadata directly in a browser and to support a future catalogue web app layered on envlib. Absent if the remote is not configured for public HTTP access. Not queryable; not in the `dataset_id` hash. |

`created_at` is set once at first insert and preserved thereafter. `modified_at` and `data_url` are refreshed by the catalogue on `cat.register()` calls that change the stored entry — `data_url` is auto-derived from `remote_conn.db_url` only (no explicit kwarg override), and is validated as a **plain public http(s) URL — no userinfo (`user:pass@`) and no query string** (a presigned URL's signature would otherwise ride into the public catalogue entry) — but not network-resolved at registration time.

### Metadata storage and source of truth

Identity and General Metadata live in two places: the cfdb file's `ds.attrs` and the RCG entry. **The cfdb file is authoritative; the RCG entry is a derived index.** `cat.register()` always reads metadata from the cfdb file, re-validates what changed, and rewrites the RCG entry — never the reverse. To update mutable General Metadata (license, attribution, description, ...), edit `ds.attrs` in the cfdb file and re-register.

- **Attr key namespacing**: envlib's keys are stored in `ds.attrs` with an `envlib_` prefix (`envlib_owner`, `envlib_version`, ...) to avoid collisions with CF and user attrs (`version` especially). Flat prefixed keys survive netCDF export, unlike a nested dict. `Metadata.to_dict()` emits the prefixed keys.
- **Self-identification**: the computed `dataset_id` and `series_id` are also written into `ds.attrs`. On every `cat.register()`, envlib re-derives the hash from the identity attrs and fails on mismatch — catching attrs hand-edited after first registration.

### Immutability
The 11 Identity fields (feature through version) are immutable once a dataset is created. `created_at` (Provenance) is also immutable — set once at first registration. The State Metadata fields, `modified_at`, and `data_url` (Provenance) are mutable and are refreshed by `cat.register()` as data is appended or the remote configuration changes.

### Dataset lifecycle

envlib v1 deliberately omits explicit lifecycle states (`deprecated`, `sunset`, etc.) — these are redundant with other mechanisms already in the model:
- **Superseded versions** are handled by the version field and the `latest-by-created_at` query default. Older versions remain accessible via explicit `version=...` kwargs.
- **Staleness** is inferable from `modified_at` — consumers can judge whether a dataset is still being updated without a dedicated "sunset" status.

**Retraction** (removal of a dataset known to contain incorrect data) is handled in v1 by `cat.deregister(dataset_id, delete_data=True)` — deleting the catalogue entry and the underlying cfdb file from its remote. Plain `deregister()` (default `delete_data=False`) merely delists: the entry is removed but the hosted data stays up for existing consumers. Deregistration is also the correction path for a typo'd identity field (identity fields can never be edited in place): deregister, fix the attrs, re-register under the new `dataset_id`. There is no tombstone.

**Shared-target guard**: `delete_data=True` first verifies that no *other* catalogue entry references the same remote target (`endpoint_url`, `bucket`, `db_key`); if one does, deregistration hard-fails without deleting anything. This closes a destruction trap in the typo-correction path: re-publishing the fixed dataset to the *same* S3 path leaves the old entry pointing at the new data — deleting the old entry's "data" would destroy the new dataset and orphan its entry.

**Deleting data after a plain delist**: once an entry is deregistered without `delete_data=True`, envlib no longer tracks the dataset, so removing the hosted data later happens one of two ways: (1) **re-register, then retract** — `cat.register()` the still-live remote back into the RCG, then `cat.deregister(dataset_id, delete_data=True)`; this is the recommended path because the shared-target guard stays in force; or (2) **direct storage deletion** — the data owner opens the remote with their own credentials and calls ebooklet's `delete_remote()` (or deletes the objects at the bucket level); envlib is not involved and the shared-target guard does not apply. The user docs must spell out both paths.

**Possible future addition — retraction tombstone**: for datasets that have been externally cited (e.g., DOI-bearing published datasets), outright deletion leaves dead references. A future option would be to preserve the catalogue entry with a `status='retracted'` field and a `retraction_reason` in General Metadata, while still removing the underlying cfdb data. This is acknowledged as a future possibility if needed. Not committed for v1.

### Data variable requirements
- **Exactly one primary data variable per dataset.** The primary variable's name in the cfdb file must equal the `Metadata.variable` value (e.g., if `variable='air_temperature'`, the cfdb file must contain `ds['air_temperature']`). This makes the primary variable self-identifying — no separate `primary_variable` attribute is needed. Registration via `cat.register()` will fail if `meta.variable` is not present as a data variable in the cfdb file.
- **Ancillary variables** (QC flags, uncertainty estimates, counts, etc.) are permitted alongside the primary variable. They must be declared via the CF `ancillary_variables` attribute on the primary variable. Ancillary variable names are unconstrained (e.g., `air_temperature_qc`, `air_temperature_stderr`).
- **units** required on the primary data variable
- **standard_name** (CF convention) — **derived by envlib, not required from the user**. envlib maintains the `(variable, feature)` → CF standard_name mapping, so the user supplies only the envlib `variable`; at `cat.validate()`/`register()` envlib looks up the mapping and, if the primary variable has no `standard_name` set, **auto-populates the curated default** (the first entry of the ordered candidate list for that `(variable, feature)`). Rules:
  - If the user *has* set `standard_name`, envlib validates it against the bundled CF list and keeps it (the override path — for multi-candidate variables where the default isn't the right one, or for extra specificity like "at 2m"). An invalid CF term still fails.
  - If the mapping is **empty** for that `(variable, feature)` ("none applicable" — e.g. freshwater water-quality, `air_ventilation_index`), `standard_name` is simply **absent**; this is valid (CF itself makes `standard_name` optional) and never blocks registration.
  - If the variable is **not yet curated** (distinct from curated-empty), envlib emits a warning and leaves `standard_name` as the user set it (or absent) — it does not block.
  - This requirement change exists because CF does not comprehensively cover envlib's variable set — even with ocean names it could never guarantee a valid term (see `plans/variable_inventory.md`), so a hard requirement was unsatisfiable.
  - Only `standard_name` is derived — **`units` is never auto-populated** (it describes the actual stored data, often a UDUNITS-variant of CF's canonical units; overwriting it would corrupt the data description). envlib does not enforce semantic consistency between `standard_name` and `feature` beyond the mapping's own per-feature keying.
- CRS must be defined on every dataset
- A `time` coordinate with at least one value is required on every dataset (see Time coordinate convention; quasi-static data carries a single validity-start timestamp). `cat.validate()` / `cat.register()` fail without it.
- **Acknowledged trade-off**: one primary variable per dataset means an N-variable product (e.g., ERA5's many fields) becomes N cfdb files, each carrying its own copy of the coordinates, and vector pairs (wind u/v) are two datasets consumers re-join. Deliberate (tethys-proven) for identity and query simplicity.

### Station conventions for `ts_ortho` datasets

For `dataset_type='ts_ortho'`, each entry in the `geometry` point coord represents a physical station (or, more generally, an x/y location where observations or model outputs are recorded). **v1 restricts the geometry coord to 2D Points** — tethys applied the same `station_id` derivation to polygon/box extents too (`tethys_utils/processing.py` calls `assign_station_id` on polygon geometries), but line/polygon geometries are not supported in envlib v1 and such tethys datasets are not migratable as `ts_ortho` yet; geometry-type extension is a future addition expected to build on the same derivation without changing Point ids. envlib does not introduce a first-class "station" entity — stations are represented entirely within each cfdb file via **station attribute variables** aligned with the geometry coord. Cross-dataset station matching is enabled by a deterministic `station_id`.

**Terminology note**: "station attribute variables" (shape `(geometry,)`, describing each station) are distinct from CF **ancillary variables** (shape matching the primary data variable, describing QC / uncertainty / counts of each measurement; declared via the CF `ancillary_variables` attribute). Both use cfdb's `data_var` mechanism, but they serve different roles and are referred to separately throughout this document.

**Required station attribute variable:**

| Ancillary var | Type | Shape | Description |
|---------------|------|-------|-------------|
| `station_id` | str | `(geometry,)` | Deterministic hash of the station's 2D location. See derivation rule below. |

**station_id derivation rule** (ported from tethys for migration compatibility):

```python
import shapely
from shapely import wkt
from hashlib import blake2b

# `geometry` is a 2D shapely Point in EPSG:4326 (z stripped if present)
rounded = wkt.loads(wkt.dumps(geometry, rounding_precision=5))
# + 0.0 collapses IEEE-754 signed zero: a coordinate that rounds to -0.0
# (reachable after reprojection) must hash identically to 0.0
canonical = shapely.Point(rounded.x + 0.0, rounded.y + 0.0)
station_id = blake2b(shapely.to_wkb(canonical, byte_order=1), digest_size=12).hexdigest()
```

The round-trip (WKT with `rounding_precision=5` → parsed back → WKB → hashed) exists because shapely's `wkb` has no built-in rounding option; WKT does. Rounding to 5 decimal places in EPSG:4326 is approximately 1m at the equator (smaller at higher latitudes), which is fine for station identity. If the geometry coord contains 3D points `(x, y, z)`, the z coordinate is stripped before the round-trip. Same-x/y-different-z points therefore share a `station_id` — vertical separation at a single physical location is expressed via other mechanisms (see below), not via station identity.

Two rules pin byte-level determinism that tethys left to machine defaults: (1) **WKB byte order is explicitly little-endian** (`byte_order=1`) — shapely's bare `.wkb` uses native order, which would fork `station_id`s on a big-endian host; tethys ran exclusively on little-endian x86, so the pin preserves parity. (2) **Signed zero is normalized** (`+ 0.0` maps `-0.0` → `0.0`) — a coordinate a hair below zero rounds to `-0.00000` in WKT, parses back as IEEE-754 `-0.0`, and changes the WKB bytes; envlib's reprojection step makes such values reachable near the prime meridian/equator. Golden vectors must lock both (including an input whose coordinate rounds to `-0.0`).

This derivation matches tethys byte-for-byte for all real tethys data (no known station sits exactly on a zero coordinate, and tethys ran only on little-endian hosts), so datasets migrated from tethys to envlib will keep the same `station_id`s for the same physical stations.

This derivation guarantees that the same physical station receives the same `station_id` across every dataset that records it, enabling users to match stations across datasets.

Two implementation notes: (1) **envlib performs the reprojection** — if the dataset's native CRS is not EPSG:4326, station points are reprojected to EPSG:4326 (pyproj) before rounding/hashing, inside `cat.validate()` / `cat.register()`. Coordinate shifts near a rounding boundary (e.g., across PROJ versions) can in principle flip a `station_id`; accepted as an edge case. (2) tethys's `assign_station_id` did **not** strip z — envlib adds the z-strip rule; any tethys dataset with 3D points would not migrate with identical ids (none known to exist).

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

## tethys → envlib migration notes

- **product_code decomposition**: tethys overloaded `product_code`; observed values map onto the 11-field model as follows:

| tethys product_code | envlib decomposition |
|---|---|
| `raw_data` | `processing_level='raw'`, `product_code=None` |
| `quality_controlled_data` | `processing_level='quality_controlled'`, `product_code=None` |
| `reanalysis-era5-land` | `product_code='era5-land'` (`method='simulation'` carries the reanalysis-ness) |
| `nz station extension v01` | `product_code='nz_station_extension'`, `version='0.1'` |
| `UC WRF NZ South Island Marlborough Nelson 1km` | `owner='uc'`, `product_code='wrf_marlborough_nelson'`, `spatial_resolution='1km'` |
| `last_value` | drop in migration unless something depends on it (cfdb partial reads make a materialized latest-snapshot dataset unnecessary); if kept: `product_code='last_value'`, `processing_level='raw'` |
| `log-log linear regression`, `estimation method 1`, ... | slugified `product_code` discriminators (e.g., `stream_depletion_method_1`) |

- **station_id**: derivation is tethys-identical (verified against `tethys_utils.processing.assign_station_id`), with the z-strip addition noted above.
- **Timestamp convention (verified 2026-07-02; justification narrowed 2026-07-05)**: tethys production code never sets `label=`, and every frequency in tethys production configs is sub-daily or daily (`10min`, `1H`, `24H`, `T`) — for which pandas defaults to `label='left'` — so tethys timestamps are interval-start (`tethys_utils/time_series.py:83-166`, `misc.py:250-365`); live public datasets confirm the alignment (24H `utc_offset='12H'` data stamped 12:00 UTC = start of the NZ local day). Migrated data at these cadences needs no timestamp shifting. **Caution**: pandas' `label` default is frequency-dependent — period-end-anchored frequencies (`M`/`ME`, `Q`, `W`, `Y`) default to `label='right'` even with `closed='left'`, so any future migration source at such a cadence must be explicitly checked and shifted, never assumed interval-start. Nuance: tethys `cumulative` aggregations are right-closed (`(t, t+freq]`) though still start-labeled.
- **frequency_interval conversion**: tethys pandas freq strings map onto envlib codes as `T` → `1min`, `10min` → `10min`, `1H` → `1h`, `24H` → `day`, `None` → `None` — all tethys production cadences are covered.
- **feature rename**: tethys `pedosphere` → envlib `soil`; tethys `still_waters` → envlib `still_water`.
- **variable renames (from the curation table)**: tethys `snow_depth` → `snowfall` (tethys misnamed WRF `SNOWNC` accumulated snowfall as depth), `potential_et` → `evapotranspiration_potential`, `naturalised_streamflow` → `streamflow` (naturalisation carried in `product_code`/`method`), `nitrogen_ammonia_+_ammonium` merged into `nitrogen_ammonia`, `e-coli` → `e_coli`. Full parameter→variable + CF standard_name curation in `plans/variable_inventory.md`.
- **utc_offset conversion**: tethys stores offsets as pandas-style hour strings (`'12H'`, `'-3H'`, `'0H'`; tethys-data-models constrains them to align the day with UTC), envlib as `±HH:MM`. Migration maps `'12H'` → `'+12:00'`, `'-3H'` → `'-03:00'`, `'0H'` → `'+00:00'`, then applies envlib's enforced reduction (a fixed-duration cadence whose offset divides evenly normalizes to `+00:00`).
- **dataset_id values do NOT carry over** — envlib's hash has different fields and serialization than tethys's ids. `station_id` values DO carry over.

## Controlled Vocabularies

### Implementation: bundled data files + optional refresh

- Ship JSON files in `envlib/vocabularies/` for each CV
- Validate field values against bundled data at dataset creation time
- Provide a utility function to refresh from external APIs (ODM2 API and NERC Vocabulary Server P07 endpoint): `envlib.vocabularies.refresh()`
- The `variable` mapping utility will return a filtered list of valid CF `standard_name` options based on the provided ODM2 `variable` and ENVO `feature`, acknowledging that CF standard names are pre-coordinated and semantically dense.
- **Refresh never writes into the installed package**: `vocabularies.refresh()` writes to a user data dir (`~/.envlib/vocabularies/`) that overlays the bundled files (user copy takes precedence when present). Writing into site-packages would break on permissions, be wiped by reinstalls, and diverge across venvs.
- **Refreshable lists vs curated mappings are separate files**: upstream term lists (ODM2 variablenames, CF standard names) are refreshable; the `variable` → CF standard_name mapping is envlib-curated by hand and is NEVER regenerated by refresh — refresh only *reports* new/removed upstream terms for manual curation.
- **The mapping is scoped, not exhaustive**: v1 curates the mapping only for the variables actually needed (starting with the tethys migration set) and is explicitly incomplete-by-design; `get_cf_standard_names()` distinguishes "no mapping curated yet" from "no applicable standard name".
- **The `variable` CV = ODM2 ∪ flagged envlib extensions**: several real quantities have no ODM2 variablename (model/grid fields — `specific_humidity`, `runoff`, `snow_cover`, `surface_emissivity`, `particulate_matter_10`/`2.5`, `snowfall`, `air_ventilation_index`, `allocation`, `water_use`). These are added as **envlib extensions**, flagged in `variable.json` (`source: "envlib"`) exactly as the `license` CV carries non-SPDX extensions. `vocabularies.refresh()` updates only the ODM2-sourced entries and never adds, edits, or removes extensions — it reports upstream diffs for manual curation. Each extension records its rationale; promote to a plain ODM2 entry if ODM2 later adds the term.
- **"No applicable standard name" is common and legitimate**: the CF standard-name table targets ocean/atmosphere model quantities, so many freshwater variables have no applicable CF name and curate to an explicit empty list. Two reasons: (1) **ocean-only scope** — CF water-body property names (temperature, electrical conductivity, turbidity, dissolved oxygen, phosphate) exist *only* as `sea_water_*`; envlib uses those only when `feature=ocean` and never stamps them on a river/lake/aquifer (a false assertion that would contradict the dataset's own `feature`); (2) an **additional dimensional wall** for the nutrient species (nitrate, nitrite, ammonium, total N/P) — CF has them only as mole concentration (`mol m-3`) while monitoring data is mg/l, which is not UDUNITS-convertible, so even the ocean name is invalid. See `plans/variable_inventory.md` for the full v1 curation table and per-species rationale.

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
| variable | ODM2 variablename (993 as of 2026-07-06) ∪ flagged envlib extensions, each mapped to CF standard_names | ~1000 | `variable.json` |
| aggregation_statistic | CF cell_methods statistical values (underscore_style) | ~10 | `aggregation_statistic.json` |
| method | envlib-defined (ported from tethys) | 7 | `method.json` |
| processing_level | envlib-defined | 3 | `processing_level.json` |
| frequency_interval | envlib-defined frequency codes | 12 | `frequency_interval.json` |
| feature | envlib-defined (mapped to ENVO URIs) | ~10-15 | `feature.json` |
| license | curated SPDX subset + envlib extensions for common non-SPDX open-access data licenses | ~10-20 | `license.json` |
| standard_name | CF Conventions (via NVS P07 SKOS collection) | ~4000+ | `standard_name.json` |
| product_code | free-form slug (see product_code rules) | — | — |

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

**processing_level** (envlib-defined):

| Value | Definition |
|-------|------------|
| `raw` | As collected or generated; no quality control applied. |
| `preliminary` | Automatically screened or near-real-time; subject to revision (e.g., ERA5T, USGS provisional, telemetered data with automated checks). |
| `quality_controlled` | Vetted and considered settled (e.g., consolidated ERA5, USGS approved, a council's validated archive). |

- Applies to both measured and modeled data — the axis is "how settled is the data", not "was it measured".
- Required; `None` is not allowed. Model output with no preliminary stream is simply `quality_controlled`.
- **Per-observation quality codes are a different layer**: NEMS-style per-record QC codes belong in an ancillary QC-flag variable, not here. Both patterns are supported — one `raw` dataset carrying per-record QC flags, or separate `raw` and `quality_controlled` datasets linked via `derived_from`. Producer's choice.
- Like `method`, envlib-maintained and deliberately small; `vocabularies.refresh()` does not touch it.

**frequency_interval** (envlib-defined frequency codes):
- envlib owns the canonical cadence grammar — NOT delegated to pandas offset aliases (whose canonical spellings changed across pandas versions and would destabilize `dataset_id`).
- Design rules: exactly **one canonical spelling per cadence** — only canonical codes are stored, hashed, displayed, and query-matched. A small **closed input-alias table** maps accepted synonyms to canonical before validation (`24h` → `day`, `60min` → `1h`), mirroring the `±HH` → `±HH:00` utc_offset input shorthand. Aliases are input convenience only — never hashed, so adding one later is non-breaking; the one permanent commitment is that an alias can never later become a distinct cadence. **No anchoring variants** (pandas `M` vs `MS` collapses — the global interval-start timestamp convention fixes anchoring); a **closed initial set**, extended deliberately as genuine needs emerge.
- **The v1 canonical table (final, decided 2026-07-05)** — 12 codes:

| Code | Kind | Duration | Notes |
|---|---|---|---|
| `1min` | fixed | 60 s | tethys `T` |
| `5min` | fixed | 300 s | council/telemetry rate |
| `10min` | fixed | 600 s | tethys `10min` |
| `15min` | fixed | 900 s | council/telemetry rate |
| `30min` | fixed | 1800 s | |
| `1h` | fixed | 3600 s | tethys `1H`; ERA5 hourly. Input alias: `60min` |
| `3h` | fixed | 10 800 s | synoptic / forecast step |
| `6h` | fixed | 21 600 s | synoptic / forecast step |
| `12h` | fixed | 43 200 s | |
| `day` | fixed | 86 400 s | tethys `24H`; always exactly 24 h in the fixed-offset model. Input alias: `24h` |
| `month` | calendar | — | e.g. ERA5 monthly; utc_offset always retained |
| `year` | calendar | — | utc_offset always retained |

- **Admission rule for future fixed codes**: the duration must divide 24 h evenly, so bins anchor unambiguously to the (offset-shifted) day boundary and no anchoring variants can arise. This is why `week`, `season`, and multi-day composite cadences (e.g., MODIS-style `8day`) are excluded from v1 — none has a self-evident global anchor (which weekday? which month triple? which epoch?); datasets at those cadences use `frequency_interval=None` until a design exists. Calendar codes are limited to true calendar units.
- **Considered and rejected (2026-07-05) — generalizing `utc_offset` into a per-dataset anchor/phase field**: a generic "bin phase" (an anchor instant reduced mod the cadence duration; bins = `anchor + k·D`) would mathematically cover sub-daily offsets, weekly start-days, and multi-day epochs in one field. Rejected because: (1) it still can't cover calendar cadences (`month`/`year` aren't epoch-tileable), so the field would carry two different semantics; (2) it explodes the canonical value space of a hash-affecting field (a week has 672 quarter-hour phases, each a distinct permanent `dataset_id`) where `utc_offset` has ~a hundred validated values and an enforced reduction rule; (3) the use-cases are rare in environmental data. **The retained path if `week`/multi-day codes are ever needed**: pin the anchor as a constant in the code's vocabulary definition (e.g., `week` = ISO Monday start; an `8day` composite names its epoch), with `utc_offset` still supplying the time-of-day component exactly as for `day`; variants (e.g., Sunday-start weeks) become distinct codes added deliberately. This keeps `utc_offset` the single per-dataset phase knob forever, moves anchoring to a frozen per-code constant, and is non-breaking to add later since new codes only mint new ids.
- Validation is a closed-enum lookup (alias map → canonical → table) — no parsing, no pandas dependency. `frequency_interval.json` carries `{code, kind, seconds, aliases}` per entry.
- `None` remains the value for irregular cadences.

**product_code** (free-form slug — see product_code rules under Identity Metadata):
- Slug-grammar validation only (`[a-z0-9._-]+`); content is not vocabulary-constrained.
- The tethys-era suggested values (`raw_data`, `quality_controlled`, etc.) are gone — that axis is now `processing_level`.

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

# Default — connects to the envlib public RCG (read-only, no credentials needed).
# Zero-config entry point for browsing the public dataset commons.
cat = envlib.Catalogue()

# Explicit remotes — replaces the default public RCG entirely.
cat = envlib.Catalogue(
    remotes=[remote1, remote2, ...],  # S3Connection or dict or URL
    cache='~/.envlib/cache',          # cache dir passed through to the cfdb/ebooklet layer
)

# Merge personal / private remotes with the public RCG.
cat = envlib.Catalogue(remotes=[my_remote], include_public=True)

# Re-pull the RCG index from all configured remotes. Use this after a new dataset
# is registered upstream (by you or another producer) and you want to see it
# without re-instantiating the Catalogue.
cat.refresh()

# All datasets — list of DatasetRef objects
cat.datasets
# [{'feature': 'atmosphere', 'variable': 'air_temperature', 'owner': 'niwa', ...},
#  {'feature': 'waterway', 'variable': 'discharge', 'owner': 'niwa', ...}]
# (DatasetRef.__repr__ displays as a metadata dict; values are stored in normalized form)

# Query with kwargs filtering (returns filtered list of DatasetRef).
# All kwargs are AND'd together; a list value means "any of these" (OR within the field).
# Query values for queryable fields are normalized (.strip().lower()) before matching.
# By default, if version is not provided, the catalogue returns the latest version
# of each matching dataset series (grouped by series_id) — "latest" is the greatest
# `created_at` within the series. An explicit version=... kwarg overrides this and
# pins the query to that exact version.
results = cat.query(
    variable='air_temperature',
    owner=['NIWA', 'CSIRO'],             # list means "any of these"
    product_code='ERA5',
    processing_level='quality_controlled',
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
# Catalogue entries never store credentials (S3Connection.to_dict() strips them) —
# for datasets on private buckets, inject your own:
ds = results[0].open(access_key_id='...', access_key='...')

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

# Remove a dataset from the catalogue. By default only the RCG entry is deleted —
# the hosted data stays up for existing consumers; the dataset is just no longer
# discoverable. Retraction of bad data passes delete_data=True, which additionally
# deletes the remote cfdb (ebooklet delete_remote()) after verifying no other
# entry references the same remote target (see Dataset lifecycle). No tombstone in v1.
cat.deregister(
    dataset_id,
    rcg_remote_conn=rcg_conn,
    delete_data=False,
)
```

**Public default RCG**: envlib ships with a hardcoded default public RCG URL — a read-only, public HTTPS-addressable RCG hosted by the envlib maintainer that serves as a shared commons of registered datasets. Behaviour:

- `envlib.Catalogue()` with no `remotes=` → connects only to the public RCG (read-only, no credentials required).
- `envlib.Catalogue(remotes=[...])` → the default public RCG is **not** included unless explicitly opted in. Explicit `remotes=` fully replaces the default.
- `envlib.Catalogue(remotes=[...], include_public=True)` → merges the user-provided remotes with the public RCG.
- **Env-var override**: `ENVLIB_PUBLIC_RCG_URL` overrides the hardcoded default, useful for testing, alternative mirrors, or if the canonical public RCG moves.
- **Write access**: for v1, only the envlib maintainer has write access to the public RCG; external registrations happen via a separate vetted process (out of scope for this plan). Writes by arbitrary users to the public RCG are not supported.
- **License sub-policy**: the public RCG accepts any of envlib's supported open-access licenses (all values in the `license` CV — CC-BY variants, CC0, ODbL, envlib extensions like `Copernicus-1.0`, etc.). No stricter sub-policy is applied. Consumers who need only the most-open subset (e.g., CC0 / CC-BY only) can filter on the `license` field via `cat.query()`.
- **Hosting**: the public RCG is hosted on public-HTTPS-accessible S3-compatible object storage (planned on Backblaze), configured so that `S3Connection(db_url=...)` works read-only without AWS credentials. **The RCG is a catalogue index only, not a data mirror** — individual dataset cfdb files are hosted by their respective data owners (e.g., ECMWF for ERA5, NIWA for river flow). Registering a dataset in the public RCG implies the owner has made the underlying cfdb file publicly HTTPS-accessible at the URL captured in `data_url`.

**RCG keying and entry contents (DONE — ebooklet 0.9.0, released 2026-07-02)**: envlib keys RCG entries directly by `dataset_id`, not by the cfdb's internal UUID. This makes uniqueness enforcement a property of the storage layer (can't have two entries with the same `dataset_id` key), enables direct lookup (`rcg[dataset_id]`) instead of scan-and-filter, and makes S3 object keys human-identifiable. The pinned **entry schema v1** (never-change surface):

```python
{'entry_version': 1,
 'type': <member ebooklet type>,             # e.g. 'EDataset'
 'timestamp': <member remote's timestamp>,   # payload only; entries are stamped with write time
 'remote_meta': <snapshot of the member's metadata slot — cfdb's SysMeta for cfdb remotes>,
 'user_meta': <envlib's Identity/General/State/Provenance dict, passed explicitly to add()>,
 'remote_conn': <S3Connection.to_dict() — access keys are never serialized; db_url passes through verbatim, hence the plain-public-URL validation (no userinfo / query string)>}
```

Key facts envlib builds on: `add(conn, key=dataset_id, user_meta=meta)` upserts (same key overwrites, and metadata-only upserts DO push — entries are stamped with write time, not the member's timestamp); keys must match `[A-Za-z0-9._-]+` (hex dataset_ids trivially comply); `rcg[key] = conn` and `del rcg[key]` round-trip; `dataset_type`/`crs` are cross-checkable from `remote_meta` for free. Verified end-to-end 2026-07-02 with a registration→query→member-open→metadata-upsert→deregister dry run. **envlib must pin `ebooklet>=0.9.0`.**

**Publish failure handling**: if `cat.publish()` fails after the cfdb push succeeds but before the RCG push completes, the data is on remote S3 but not yet advertised in the remote catalogue. Re-running `cat.publish()` is safe — the cfdb push is idempotent (same data), and the RCG entry write is an upsert on `dataset_id`.

**Upstream defect FIXED — grouped-mode push clobber (fixed in ebooklet ≥0.8.4, verified 2026-07-02)**: pre-0.8.4, ebooklet's push rebuilt each affected S3 group object from locally-present keys only, silently destroying non-materialized group members (live repro: silent wrong-value reads, `InvalidRange`, dangling index entries). 0.8.4 repacks the FULL group membership, pulling missing/stale members first (one ranged read per affected group) — verified by regression tests plus a cfdb-level append-from-fresh-copy smoke with byte-exact readback. **envlib must require `ebooklet>=0.9.1` and `cfdb>=0.9.0`** (floors as of 2026-07-05; transitively brings s3func>=0.9.1 and booklet>=0.12.5 once the staged pins release). Surviving notes: (a) **the RCG stays per-key (never `num_groups`)** — writer-private entry objects are desirable independent of the bug; (b) appends from a fresh/partial local copy now download the affected groups' missing members before pushing (a correctness cost, logged by ebooklet); (c) the two cfdb-layer publish footguns are **FIXED in cfdb 0.9.0** (released 2026-07-05): mid-session `push()` now flushes all in-memory state first (new public `Dataset.sync()`), and `'w'`/`'c'` opens attach to an existing remote even with a fresh local file — `cat.publish()`/`cat.register()` need NO hydrate-first or close→reopen→push workarounds; push mid-session freely (pushing remains explicit-only, never on close).

**Cache management**: envlib does not implement its own cache layer. The `cache=` path is passed through to the underlying `cfdb` / `ebooklet` / `booklet` stack, which already handles chunk-level pulling, local-vs-remote synchronisation, and staleness detection. Eviction policy, size limits, pinning, and cache inspection (if any) are the lower layer's concern — envlib does not duplicate these APIs. Users who need to reclaim disk can manage the cache directory manually.

**Offline behavior**: `envlib.Catalogue()` construction and `cat.query()` degrade gracefully when the remote is unreachable — if a previously-pulled local copy of the RCG index exists, the catalogue operates read-only from it (possibly stale) rather than hard-failing. Only first-ever use with no local index requires connectivity.

**Concurrent writers (verified 2026-07-02, live two-writer tests)**: registration by multiple producers to a shared *existing* RCG is **safe under default flags** — ebooklet holds an exclusive S3 lock from open through push to close, so a second writer's open blocks (up to `lock_timeout`, default 300 s, then `TimeoutError`) and re-pulls the current index on acquisition; both writers' entries survive (verified live). Two verified caveats:

1. `force_lock=True` bypasses serialization and WILL destroy the other writer's entries (verified live) — never use it against a shared RCG unless certain the competing lock is dead.
2. **Bootstrap race — FIXED in ebooklet ≥0.8.4** (verified 2026-07-02): pre-0.8.4, session metadata (uuid/timestamp/init bytes) was cached at session creation and never refreshed after the lock wait, so a writer whose session predated the remote's creation skipped the index pull and clobbered the first creator (+ UUID fork). 0.8.4 re-reads the metadata after lock acquisition, and additionally materializes brand-new *empty* databases on push — so the operational rule simplifies to: create the RCG and push once (even empty) before advertising it to producers.
3. **Residual window (s3func, open)**: the bakery lock itself can fail to serialize two writers whose lock acquisitions land within the S3 LIST-propagation window (observed live; tracked in `OPEN_WORK.md` under s3func, alongside a 3+-writer accumulation bug). ebooklet's fixes protect every case where the lock serializes; until s3func is fixed, truly-simultaneous first-contact registrations retain a small race window.

**Query semantics (v1)**:
- **Spatial**: `bbox`, `within_radius`, and `geometry` are mutually exclusive — pass at most one. All use *intersects* semantics against the dataset's stored `bbox` State Metadata. All query geometries must be in EPSG:4326. Intersects logic implements the antimeridian convention (stored `min_lon > max_lon` means the bbox crosses 180°).
- **Temporal**: `start_date` and `end_date` use *overlaps* semantics against the dataset's `[time_start, time_end]` range. Either kwarg is optional (open-bounded queries are supported).
- **Set membership**: a list value matches any of the listed values (OR within the field); scalars are exact match. Kwargs across fields are AND'd together.
- **Case**: matching lowercases both the query value and the stored value, so it is genuinely case-insensitive for all queryable fields — including CVs whose canonical case is mixed (`license='cc-by-4.0'` matches stored `CC-BY-4.0`).
- **Pattern matching**: exact match only. No glob, substring, or regex filtering.
- **`modified_at` queries**: not supported.
- **Pagination / ordering**: `cat.query()` returns all matching entries as a list with no guaranteed ordering and no result limit. Callers sort or paginate client-side if needed.

**Possible future extension — regex pattern matching in queries**: explicit regex predicates for fields like `product_code` (e.g., to match all `ERA*` variants with a single query). Deferred from v1 for API simplicity. If added, regex is the preferred syntax over glob or substring because it is explicit and unambiguous. Not committed for v1.

**Possible future extension — `modified_at` queries**: recency-based filtering on the `modified_at` Provenance field (e.g., `modified_from` / `modified_to` kwargs, or a `modified_since=timedelta(days=7)` form) to answer queries like "datasets updated in the last week." Straightforward additive change if needed. Not committed for v1.

**DatasetRef** wraps an RCG entry:
- `__repr__` displays metadata as a dict
- `.open(file_path=None, access_key_id=None, access_key=None)` opens the cfdb EDataset using the stored connection details. Entries never contain credentials (`S3Connection.to_dict()` stores only `db_key`/`bucket`/`endpoint_url`/`db_url`), so credentials for private buckets are injected here; public-HTTPS datasets need none. **Only inject credentials for entries whose `endpoint_url`/`bucket` you trust** — injected keys SigV4-sign requests against the entry's stored endpoint, so supplying them for a third party's entry sends signed requests to that party's server
- `.metadata` returns the full metadata dict
- Attribute access for individual fields: `ref.variable`, `ref.owner`, etc.

### 2. Metadata class — structured metadata construction

No `create_dataset` wrapper. Users create cfdb datasets directly and assign metadata via `ds.attrs.update()`. The `Metadata` class validates CV fields on construction and provides a dict for cfdb.

```python
# Build metadata — validates CV fields and normalizes values on construction.
# Free-form user-input fields (owner, product_code, spatial_resolution, version) are
# lowercased, whitespace-stripped, and slug-validated on assignment. CV-constrained
# fields (including license) preserve their canonical case. Attribution is free-form
# text, not normalized.
meta = envlib.Metadata(
    feature='atmosphere',
    variable='air_temperature',
    method='simulation',
    product_code='era5',
    processing_level='quality_controlled',
    owner='ecmwf',                        # ERA5 is ECMWF's product — mirroring never confers ownership
    aggregation_statistic='point',
    frequency_interval='1h',              # envlib frequency code
    utc_offset='+00:00',
    spatial_resolution='0.25deg',
    version='2',
    license='Copernicus-1.0',
    attribution='Generated using Copernicus Climate Change Service information',
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

# Create coords and data vars.
# The primary data variable's name must match meta.variable; envlib derives its
# standard_name from the (variable, feature) mapping at validate/register time, so
# you normally set only units. (To override the curated default — e.g. pick a
# non-default candidate or add "at 2m" specificity — set standard_name yourself and
# envlib validates + keeps it. Inspect candidates with the helper below.)
dv = ds.create.data_var.generic('air_temperature', ('latitude', 'longitude', 'time'), dtype='float32')
dv.attrs['units'] = 'degC'
# Optional — see what envlib would populate, or choose among multiple candidates:
# cf_names = envlib.vocabularies.get_cf_standard_names('air_temperature', feature='atmosphere')

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
- Properties for each field with CV validation and enforced normalization on set (whitespace strip, lowercasing + ASCII slug check, `utc_offset` canonicalization including the reduction rule, `spatial_resolution` grammar)
- `.to_dict()` returns a plain dict suitable for `ds.attrs.update()`
- `.dataset_id` computed property (blake2b hash of the 11 Identity fields, only available when all 11 are set); `.series_id` likewise (version omitted)
- Incremental or all-at-once construction

### 3. Vocabulary utilities

```python
from envlib import vocabularies

# List valid values for a field
vocabularies.list('variable')       # -> ['air_temperature', 'precipitation', ...]
vocabularies.list('feature')        # -> ['atmosphere', 'waterway', ...]
vocabularies.list('standard_name')  # -> ['air_temperature', 'precipitation_flux', ...]
vocabularies.list('processing_level')  # -> ['raw', 'preliminary', 'quality_controlled']

# Check if a value is valid
vocabularies.is_valid('variable', 'air_temperature')  # -> True
vocabularies.is_valid('standard_name', 'air_temperature')  # -> True

# Get the ordered CF standard_name candidates envlib would consider for a
# (variable, feature). envlib auto-populates the FIRST (curated default) at register
# time; this helper is for inspecting/overriding. Empty list = "none applicable"
# (curated, no valid CF name — common for freshwater water-quality); None = not yet curated.
vocabularies.get_cf_standard_names('temperature', feature='ocean')     # -> ['sea_water_temperature']
vocabularies.get_cf_standard_names('temperature', feature='waterway')  # -> []  (freshwater: CF has only sea_water_*)
vocabularies.get_cf_standard_names('electrical_conductivity', feature='waterway')  # -> []

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
│   ├── processing_level.json # envlib-defined
│   ├── frequency_interval.json # envlib-defined frequency codes
│   ├── feature.json         # envlib-defined (mapped to ENVO)
│   ├── standard_name.json   # CF Conventions (from NVS P07)
│   └── license.json         # curated SPDX subset + envlib open-access extensions
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
- `pyproj` — bbox reprojection (`transform_bounds`) and station reprojection; used directly by envlib, so declared directly (not inherited via cfdb)
- `shapely` — station_id hashing and `geometry=` query filters; used directly, so declared directly
- `httpx` or `requests` — for fetching/refreshing vocabulary updates (e.g., ODM2 APIs, NVS P07 SKOS endpoints)
- NOT `pandas` — envlib's own frequency codes remove the only need for it

## Implementation Order

0. **ebooklet enhancement (prerequisite) — DONE (ebooklet 0.9.0, released 2026-07-02)**: `RemoteConnGroup.add(conn, key=, user_meta=)` with entry schema v1 (see RCG keying and entry contents), `__setitem__`/`set` delegation, keyed upserts that push on metadata-only changes, and key-charset validation. envlib pins `ebooklet>=0.9.0`.
1. **Vocabularies module** — bundled JSON files (including mapped variables and CF standard names via NVS P07, the `processing_level` CV, and the finalized `frequency_interval` code table), validation functions (incl. slug grammar), mapping utility, refresh utility (user-dir overlay)
2. **Metadata module** — `Metadata` class with CV validation, dataset_id hashing, `.to_dict()`
3. **Catalogue module** — `Catalogue` class (RCG-backed, keyed by `dataset_id`), `DatasetRef` class with .open(), .datasets, .query(), .refresh(), .register(), .publish(), .validate(), .deregister() with full validation, extent extraction, and upsert logic
4. **Tests** for each module
5. **Update `__init__.py`** with public API exports

## Verification

- `uv run pytest` — unit tests for:
  - **Golden-vector hash tests**: fixed inputs → exact expected hex digests for `dataset_id`, `series_id`, and `station_id`, committed permanently — these are what actually lock the serialization rules. Must include: an input locking the UTF-8 encoding (bytes that differ across codecs), a station whose coordinate rounds to `-0.0` (locks signed-zero normalization), the explicit little-endian WKB bytes, rejection vectors for non-canonical `spatial_resolution` spellings (`.25deg`, `00.25deg`, `0.250deg`, `1.0km`) and out-of-range `utc_offset`s (`+24:00`, `+13:60`), and the `-00:00` → `+00:00` and offset-reduction (`1h` at `+12:00` → `+00:00`) normalizations
  - dataset_id hashing is deterministic and consistent
  - Slug grammar and normalization: accepted/rejected forms for owner/product_code/version, utc_offset, spatial_resolution, frequency codes — including the frequency input-alias map (`24h` → `day`, `60min` → `1h` accepted; stored and hashed only as canonical)
  - bbox: antimeridian-crossing extents round-trip through registration and match `intersects` queries correctly; 0–360-longitude sources are normalized — including a full-globe ERA5-style grid (→ `[-180, lat0, 180, lat1]`) and a regional 170°E–190°E grid (→ `min_lon > max_lon`, not a near-global box; `transform_bounds` is a no-op for native-geographic sources, so this exercises envlib's own wrap)
  - Latest-version query grouping by `series_id`, including the documented back-fill caveat behaviour
  - Metadata validation rejects missing/invalid fields
  - Vocabulary validation accepts valid terms, rejects invalid
  - Vocabulary accurately filters applicable CF standard names based on variable and feature
  - Catalogue lists/queries/filters correctly
  - Catalogue properly extracts time/bbox extents and updates them on re-registration
  - Catalogue validation rejects datasets missing **units** on the primary variable; `standard_name` is NOT required — envlib auto-populates the curated default `(variable, feature)` CF name, keeps a user-set override (validated as real CF), leaves it absent when the mapping is empty, and warns when the variable is uncurated
  - standard_name derivation: auto-populate default for a mapped `(variable, feature)`; empty mapping → absent + registers OK; user override validated and preserved; ocean-only names never applied to non-ocean features
  - Case-insensitive query matching for mixed-case CVs (`license='cc-by-4.0'` matches stored `CC-BY-4.0`)
  - `deregister(delete_data=True)` shared-target guard: refuses when another entry references the same (`endpoint_url`, `bucket`, `db_key`)
- Integration test: `Metadata.to_dict()` → `ds.attrs.update()` → verify metadata round-trips through cfdb .attrs
- Integration test: vocabulary refresh from ODM2 API / NVS P07 (network test, can be marked skip-if-offline)
