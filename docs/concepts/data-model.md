# The Data Model

## Datasets and versions

In envlib, a **dataset** is the thing that persists: "ERA5 2 m temperature at 0.25°", "Environment Canterbury's river flow record". Datasets are living — new timestamps get appended for years. A **version** of a dataset marks a generational change (a new methodology, a reprocessing campaign), not a daily update.

Each version is stored as its own [cfdb](https://mullenkamp.github.io/cfdb/) file on its owner's S3 storage, and each version is a separate catalogue entry. When you `query()` without pinning a version, you get the **latest version of each matching dataset** — which is almost always what you want.

## Identity Metadata: the eleven fields

Eleven fields define what a dataset is. Together they must be unique; individually each is validated against a controlled vocabulary or a strict grammar (see [Vocabularies](../guide/vocabularies.md)):

| Field | Example | Constrained by |
|---|---|---|
| `feature` | `atmosphere`, `waterway` | envlib CV (mapped to ENVO) |
| `variable` | `temperature`, `streamflow` | envlib CV (ODM2 ∪ extensions) |
| `method` | `simulation`, `sensor_recording` | envlib CV |
| `product_code` | `era5`, or `None` | free-form slug |
| `processing_level` | `raw`, `quality_controlled` | envlib CV |
| `owner` | `ecmwf`, `niwa` | free-form slug |
| `aggregation_statistic` | `mean`, `point` | CF cell_methods subset |
| `frequency_interval` | `1h`, `day`, or `None` | envlib frequency codes |
| `utc_offset` | `+00:00`, `+12:00` | `±HH:MM` grammar |
| `spatial_resolution` | `0.25deg`, `point`, or `None` | strict numeric grammar |
| `version` | `1`, `2026-03` | free-form slug |

**Identity fields are immutable.** Once a dataset is registered they can never be edited in place — changing any of them makes a *different* dataset. (Typo'd an identity field? Deregister, fix the attributes, re-register under the new id.)

Two identity subtleties worth knowing:

- **`owner` means the producer, not the host.** Mirroring or redistributing unmodified data never confers ownership — ERA5 mirrored by anyone is still `owner='ecmwf'`, under ECMWF's license and attribution. Transforming the data (bias correction, regridding, QC) creates a *derivative* dataset with a new owner, linked back via `derived_from`.
- **`version` is a string, and the string is the identity** — `1`, `1.0`, and `01` are three different versions. Pick one spelling convention per dataset and keep it.

## The three identifiers

envlib derives permanent, deterministic identifiers by hashing metadata — the same inputs produce the same id on any machine, in any catalogue, forever:

| Id | Derived from | Identifies |
|---|---|---|
| `dataset_id` | 10 identity fields (all except `version`) | *the dataset*, stable across versions |
| `dataset_version_id` | all 11 identity fields | one version — the catalogue entry key, what you open, deregister, and cite in `derived_from` |
| `station_id` | a station's rounded 2D location | a physical station, identical across every dataset that records it |

All three are 24-character hex strings (take care not to paste one kind where another is expected — `derived_from` entries must be `dataset_version_id`s specifically, since lineage means "computed from *that version*").

The hash constructions are permanent public contracts, locked by golden-vector tests: they will never change, because changing them would fork every id in every catalogue.

## The other metadata categories

- **General Metadata** — mutable, non-identity: `license` and `attribution` (required; defined by the owner, mirrors may not override them), plus optional `description`, `derived_from` (machine-traversable lineage: `dataset_version_id`s and/or DOI URLs), and `doi`.
- **State Metadata** — extracted automatically at registration, never hand-set: the WGS84 `bbox`, `time_start`/`time_end`, `dataset_type` (`grid` or `ts_ortho`), and grid steps. This is what spatial/temporal queries filter on.
- **Provenance** — set by the catalogue: `created_at` (first registration; decides "latest version"), `modified_at` (bumped only when a re-registration actually changes the entry), `data_url` (the public HTTP location, when configured).

The cfdb file's attributes (`envlib_`-prefixed) are the authoritative copy of Identity and General metadata; catalogue entries are a derived index, rewritten from the file at each registration.

## Lifecycle: delisting and retraction

envlib has no `deprecated`/`sunset` states — superseded versions are handled by the latest-version query default, and staleness is inferable from `modified_at`. Removal comes in two strengths:

- **Delist** — `cat.deregister(dataset_version_id, rcg_conn)`: the catalogue entry disappears, but the hosted data stays up for existing consumers.
- **Retract** — `deregister(..., delete_data=True)`: for data known to be wrong; also deletes the hosted cfdb file (after a safety check that no *other* entry references the same storage target).

There is no tombstone in v1: a retracted dataset simply ceases to exist. See [Publishing & Registration](../guide/publishing.md) for the mechanics, including how to delete data after a plain delist.
