# A read-only data API for envlib: feasibility and the OGC API – EDR mapping

_Assessment, 2026-10-07. Not a plan: nothing here is decided beyond what the Backlog item in
`OPEN_WORK.md` records._

## Core

**Question.** Can an efficient REST API that *retrieves* envlib data run as a service on the Docker
Swarm cluster, and in what language? Writing to envlib through the API is out of scope.

**Answer.** Yes, and it should be written in Python on top of envlib/cfdb. A Rust reader is
technically possible, because every format on the read path is plain binary or JSON. It is the wrong
trade for three reasons. Latency is set by B2 round trips and not by decoding, so Rust would only
speed up the part that is already fast. The ebooklet remote format is changing now (format 3), so a
second reader would be obsolete on its first release. A second decoder would also be a second copy of
cfdb's encoding rules, which breaks the metadata single-source-of-truth principle.

**Interface.** OGC API – Environmental Data Retrieval (EDR) fits envlib closely. Collections map to
`dataset_id`, instances to `dataset_version_id`, `/locations` to ts_ortho stations, and
`/position`/`/area`/`/cube` to grids. CoverageJSON is the default output, with CSV and netCDF4 beside
it. Every envlib metadata field can be carried in the collection object.

**Top risks.** (1) Each process needs its own cache directory: even a read-only session holds an
exclusive lock on its cache file. (2) A cold read of a whole grid map is expensive (one WRF hour pulls
322 chunks and about 35 MB), so requests need a size budget, and EDR has a place for one (HTTP 413).
(3) Hourly datasets need an explicit freshness mechanism, because a long-lived session does not
re-check its remote on its own.

---

## 1. Measured baseline (Python stack, live commons)

Run 2026-10-07 from this repo's environment: envlib 0.1.7, cfdb 0.10.0, ebooklet 0.10.5,
booklet 0.12.10. Each run started from an empty cache directory, and "warm" repeats the same read in
the same session.

| Operation | Cold | Warm |
|---|---|---|
| `Catalogue()` (16 entries) | 2.48 s | 0.21 s (`refresh()`) |
| Open one dataset (`DatasetRef.open()`; downloads the remote index) | 2.3–2.9 s | — |
| ECan streamflow, 1 station, full history (183,561 h = 8 chunks) | 1.52 s | < 0.01 s |
| ECan streamflow, all 144 stations, last 48 h (144 tail chunks) | 3.59 s | 0.01 s |
| WRF 3 km precipitation, 1 cell, last 8,760 h | 1.67 s | 0.01 s |
| WRF 3 km precipitation, 1 cell, 24 h in an unread chunk band | 0.51 s | — |
| WRF 3 km precipitation, full map at one hour (534 × 315) | 13.0 s | 0.18 s |

The full-map read grew the local cache from 6.0 MB to 40.5 MB. The variable is chunked
`(840, 24, 24)`, so one map touches ⌈534/24⌉ × ⌈315/24⌉ = 23 × 14 = 322 chunks, each holding 840
hours. That is the price of chunking for time-series reads, and it is a property of the dataset, not of
the API.

Live dataset layouts at the time of measurement:

| Dataset | Shape | Chunk shape | Compression |
|---|---|---|---|
| ECan streamflow (ts_ortho) | (144, 183561) | (1, 25000) | zstd |
| WRF 3 km precipitation (grid) | (306816, 534, 315) | (840, 24, 24) | zstd_shuffle |
| ESA SST temperature (grid) | (16650, 1000, 1600) | (120, 60, 60) | zstd |

**These cold numbers predate ebooklet format 3.** The WRF and SST datasets were read from
hash-grouped format 2 remotes. Format 3 regroups them in write order (32 MB groups by default), which
changes how many bytes a grouped ranged read pulls. Re-measure the grouped rows on the republished
remotes before sizing the chunk budget. The ECan rows are per-key and should not change.

**What the numbers say.** Cold costs are network round trips to B2, and warm costs are near zero. The
efficiency levers are therefore: keep dataset handles open (an open costs 2–3 s), keep the cache warm,
and refuse requests whose cold cost is unbounded. The implementation language is not one of them.

## 2. Language: what a non-Python reader would have to reimplement

Reading a dataset straight from the remote without the Python stack means reimplementing four layers.
None of them uses pickle.

- **ebooklet remote.**
  - **db object:** a 40-byte header (magic `ebooklet-db\0`, big-endian lengths), a manifest
    (JSON), a metadata section (JSON) and a fixed-length booklet index.
  - **object metadata:** required headers (`init_bytes`, `timestamp`, `format_version`,
    `num_groups`) are read from a HEAD request, so any proxy in front must pass `x-amz-meta-*` /
    `x-bz-info-*` through.
  - **values:** per-key mode stores one object per chunk. Grouped mode uses ranged GETs into group
    objects, whose entry framing mixes big- and little-endian fields.
- **booklet index.**
  - **header:** 200 bytes, little-endian.
  - **lookup:** the key hash is BLAKE2s with a native 13-byte digest, the bucket is the hash modulo
    `n_buckets`, and chain lookup compares hashes only.
  - **legacy values:** the `index_offset` field has legacy sentinel values a reader must honour.
- **cfdb.**
  - **dataset metadata:** JSON in booklet's metadata slot (`SysMeta` with tagged variable structs).
  - **chunk keys:** `{var}!{start0}.{start1}…`, where the numbers are element start offsets. They can
    be negative after a prepend, so the reader needs floor division.
  - **codecs:** zstd frames or LZ4 *frames*, optionally byte-plane shuffled by encoded item size.
  - **packed decode:** `encoded / 10**precision + offset`, with code 0 meaning missing.
  - **non-numeric types:** str is a msgpack array, and geometry is WKT.
- **envlib catalogue.**
  - **storage:** an ebooklet RemoteConnGroup whose entries are JSON keyed by `dataset_version_id`.
  - **query:** a linear in-memory filter.

The estimated size of a Rust reader is about 2.5–3k lines (agent estimate, not built). Point 1 of the
Core is the deciding factor: the ebooklet working tree has an uncommitted format 3 (write-order
groups) that changes the index entry and refuses hash-grouped format 2 remotes. The live WRF, SST and
catalogue remotes will be republished under it. A Python service gets that change by upgrading its
lock.

**When to revisit:** only if the formats freeze *and* profiling of a deployed service shows decode CPU
dominating. Neither is true today.

## 3. Constraints the stack places on a server

| Constraint | Evidence | Consequence |
|---|---|---|
| A read-only session opens its local cache in write mode and holds an exclusive OS lock | **Ran**: two processes on one cache dir; the second logged "waiting on a file lock" and blocked until the first closed (14.8 s) | One cache directory per process. Within a process, share one handle per dataset across threads; booklet locks each `get`. |
| Opening a dataset costs 2–3 s | Measured, §1 | Open handles once at startup and keep them. Never open per request. |
| A long-lived session does not re-check the remote | **Read** (agent report on ebooklet 0.10.5); not re-checked | A timer must `changes().pull()` or reopen the hourly ts_ortho datasets, and call `Catalogue.refresh()`. Confirm the claim before relying on it. |
| The local cache only grows | Measured: one map read added 34.5 MB | Cap the cache size; evict by closing the handle, deleting the cache file and reopening. |
| Point-geometry coordinates have no `.loc` lookup | **Read** (agent report on cfdb indexers) | Resolve stations by scanning `station_ref`/`point` once per dataset and caching the map (144 stations). |
| Grid map reads amplify by the time-chunk depth (840×) | Measured, §1 | Budget requests by chunk count and refuse oversize ones with 413. |
| WRF grids are in a projected CRS | cfdb skill (`GridInterp` vs column read) | `position` queries project lon/lat with pyproj, take the nearest cell and read its column in one call. |

The thread-safety of cfdb objects shared within one process was not checked.

## 4. OGC API – Environmental Data Retrieval

### History and status

EDR is mature, not new. The UK Met Office and the US National Weather Service developed it together
from 2018. Version 1.0 became an OGC Standard on 2021-09-22. Version 1.1 (19-086r6) was approved in
2023. Part 2, Publish-Subscribe (23-057r1), was approved 2024-05-07 and published 2024-09-23.
Version 1.2 (19-086r9) was published 2026-09-08 and is a minor revision that is fully compatible
with 1.1.

Deployments include the UK Met Office, NWS (built on pygeoapi) and IBL Software. WMO names EDR
as a foundation technology of WIS 2.0.

### Structure

The **Core** and **Collections** conformance classes are mandatory, and a server must implement at
least one query type. Every output encoding is optional. A server claims exactly what it implements,
so a partial EDR server is conformant.

```
/                                    landing page
/api                                 OpenAPI definition
/conformance
/collections
/collections/{id}
/collections/{id}/{queryType}        position | radius | area | cube | trajectory | corridor
/collections/{id}/locations[/{locId}]
/collections/{id}/items[/{itemId}]
/collections/{id}/instances[/{instanceId}/{queryType}]
```

**Common parameters:**
- `coords`: a WKT geometry.
- `datetime`: an ISO 8601 instant, `start/end` range or list.
- `z`, `parameter-name` (a comma-separated list) and `crs`.
- `f`: the output format.
- `limit`: paging.

**Query-specific parameters:**
- `radius`: `within` and `within-units`.
- `cube`: `bbox` and `resolution-x/y/z`.

**Collection metadata.** `extent` holds spatial, temporal and vertical parts plus optional custom
dimensions. `data_queries` lists the query types per collection. `parameter_names` holds one entry per
variable. `output_formats` and `crs` complete the required set.

**Instances** are "different views of the same collection": versions, reprocessings or model runs.
Each supports the same query types.

**Custom dimensions** have an `id`, `interval`, `values` and `reference`. The `id` becomes a query
parameter with the same single/list/range grammar as `datetime` (the spec's example is
`realisations=9/15`).

**Oversized requests:** the spec says a server should return a message "explaining the query limits
imposed by the server implementation", and names HTTP 413.

## 5. Mapping envlib onto EDR

### Queries

| EDR query | envlib use |
|---|---|
| `locations` and `locations/{station_ref}` | ts_ortho stations. One station's history is exactly what the `(1, 25000)` chunking is built for. Several ids can be comma-separated. |
| `position` (WKT `POINT`) | A grid cell's time series (WRF, SST). |
| `area` (WKT `POLYGON`) | Grid subsets, or the stations inside a polygon. |
| `radius` | Stations near a point. envlib already does great-circle radius tests on catalogue bboxes. |
| `cube` | Grid subsets, under the chunk budget. This is the expensive query. |
| `items` | Optional: stations as features. |
| `trajectory`, `corridor` | Not offered. |

`data_queries` differs per collection: ts_ortho collections offer `locations`/`radius`/`area`, and
grid collections offer `position`/`area`/`cube`.

### Metadata fields

The 1.2 collection schema (`core/standard/openapi/oas31/schemas/collections/collection.yaml` in the
EDR repository) requires `links`, `id`, `extent`, `data_queries`, `parameter_names`,
`output_formats` and `crs`. It does not set `additionalProperties: false`, so the object accepts
extra properties.

| envlib field | EDR location |
|---|---|
| `dataset_id` | collection `id` |
| `dataset_version_id` | instance id; the default (no instance) is the latest version, as `Catalogue.query()` returns |
| `description` | `description` |
| `bbox`, `time_start`/`time_end` | `extent.spatial`, `extent.temporal` |
| `variable`, `standard_name` | a `parameter_names` entry; `observedProperty.id` can be the CF standard-name URI on the NERC vocabulary server, as the schema's own example does |
| cfdb `units` attr | the parameter's `unit` |
| `aggregation_statistic` + `frequency_interval` | the parameter's `measurementType: {method, duration}`, e.g. `{method: "mean", duration: "PT1H"}`; `day` → `P1D`, `month` → `P1M`; irregular series carry `method` only |
| `license` | a `links` entry with `rel: licence` |
| `dataset_type` | not exposed directly; it selects the collection's `data_queries` |
| `feature`, `method`, `owner`, `product_code`, `processing_level`, `utc_offset`, `spatial_resolution`, `version` | no standard slot; the searchable ones are copied into `keywords` |

**The full identity-hashed metadata goes in one namespaced extension object**, exactly as the
catalogue stores it:

```json
"envlib": {"dataset_id": "...", "dataset_version_id": "...", "feature": "...", "owner": "...", ...}
```

The standard slots are derived from it and never edited separately. That keeps the API consistent
with the metadata single-source-of-truth principle. The namespace avoids collisions with keys a future
EDR revision might add. Generic EDR clients ignore the block, so anything a user should see without
envlib-aware tooling (owner, licence, cadence) also goes in a standard slot.

## 6. Output formats

**CoverageJSON** (OGC Community Standard, 2022) is EDR's recommended encoding:
- **domain:** named axes plus a CRS.
- **parameters:** each with `observedProperty` and `unit`.
- **ranges:** `NdArray`s (a flat `values` array, `shape` and `axisNames`), with `null` for missing.
  That maps directly from cfdb's NaN-on-read.

| Domain type | envlib data |
|---|---|
| `PointSeries` | one station, or one grid cell, over time |
| `MultiPointSeries` | several stations |
| `Grid` | a cube subset |

`TiledNdArray` ranges split an array into tiles fetched by URL template. That mirrors cfdb's chunking
and could later expose chunks as tiles. It is not needed for a first version.

JSON is verbose. One station's full 183,561-hour history is an estimated 6 MB before gzip
(timestamps dominate; not measured). So `f=CSV` should ship from the start, and `f=netCDF4` for
large cube requests, since cfdb already exports netCDF. (The ts_ortho netCDF export currently fails
on the geometry coordinate; see the `[cfdb]` Backlog item.)

## 7. What EDR does not cover

- **Temporal aggregation.** There is no "daily means of hourly data" parameter, because
  `resolution-x/y/z` resample space only. cfdb's `groupby` would need a server extension or a
  separate endpoint.
- **Faceted catalogue search.** `/collections` lists collections with their extents but has no
  filter. `variable=`/`owner=` filtering would be an extension. STAC (OGC Community Standard since
  October 2025) or OGC API – Records could be added later for external harvesting.
- **Forecasts (deferred).** EDR's forecast model is one *instance* per model run with `datetime` as
  valid time. It has no dense lead-time axis like cfdb's `forecast_period`. When forecasts are taken
  up, runs map to instances (or a custom `forecast_reference_time` dimension) and the lead can be a
  custom dimension.
- **Change notifications.** These are Part 2 (Publish-Subscribe, described with AsyncAPI) and a
  natural second phase for the hourly ts_ortho datasets.

## 8. Implementation shape

**Recommended:** a small FastAPI service implementing the EDR subset of §5. The hard part is the
lifecycle of cache handles, which is easier to own in our own code. The catalogue is also dynamic,
whereas pygeoapi is configured with static YAML.

**Alternative worth a short spike:** a custom pygeoapi EDR provider. pygeoapi supplies conformance
pages, OpenAPI and HTML browsing. Its built-in `xarray-edr` provider supports only `position` and
`cube`, and whether pygeoapi can add collections at runtime was not checked.

**Swarm layout:**
- **Concurrency:** one uvicorn worker per replica with a thread pool, and dataset handles opened at
  startup and shared across threads. Scale with replicas. Never point two processes at one cache
  directory.
- **Cache:** a node-local volume per replica with a size cap and eviction (§3).
- **Freshness:** a refresh timer for the catalogue and the hourly datasets.
- **HTTP caching:** `Cache-Control`/`ETag` derived from `dataset_version_id` plus the remote
  timestamp. Frozen datasets can be cached by a CDN for a long time.
- **Limits:** a per-request chunk budget returning 413 with the limit in the message.
- **Credentials:** read-only access to public datasets needs none (`db_url` only).

**Sequencing:** ebooklet format 3 will be finished before this work starts (Mike, 2026-10-07). The
service therefore builds on format 3 remotes only, and the grouped datasets will already have been
republished under it.

## 9. Open questions

- Public and anonymous, or authenticated? This affects rate limiting and whether private-bucket
  datasets are ever exposed.
- Which datasets first? The ECan ts_ortho stations exercise `locations`, and WRF exercises
  `position`/`cube`.
- What is the expected load? It sets replica count and cache size.
- Is temporal aggregation needed from the start?

## 10. Verification status

- **Ran:**
  - the timings and layouts of §1;
  - the cache-lock test of §3;
  - the ebooklet working-tree state (format 3 uncommitted; installed 0.10.5 still reads the
    hash-grouped esa-sst);
  - a fetch of the EDR 1.2 `collection.yaml` and `parameterNames.yaml` schemas: `additionalProperties`
    appears only under `parameter_names` and `categoryEncoding`, and `measurementType` has a required
    `method` and an optional `duration`.
- **Read (agent reports on the source, not re-checked):**
  - the byte layouts of §2 and the Rust size estimate;
  - that long-lived sessions never re-check the remote;
  - the lack of point-geometry `.loc`.
- **Read (web):** the EDR history and dates, the deployments list, the CoverageJSON structure and
  pygeoapi's EDR providers.
- **Not checked:**
  - the EDR 1.1 approval month;
  - the 1.2 changes beyond OGC's compatibility statement;
  - the spec prose on extension properties (the schema was relied on);
  - that NERC resolves every envlib `standard_name`;
  - pygeoapi runtime collections;
  - cfdb thread-safety within a process;
  - real CoverageJSON sizes;
  - behaviour under concurrent load.

## Sources

- [OGC API – EDR Part 1 v1.2 (19-086r9)](https://docs.ogc.org/is/19-086r9/19-086r9.html)
- [OGC: public comment on EDR v1.2](https://www.ogc.org/requests/ogc-seeks-public-comment-on-v1-2-of-ogc-api-environment-data-retrieval-standard-part-1/)
- [EDR v1.1 (19-086r6)](https://docs.ogc.org/is/19-086r6/19-086r6.html)
- [EDR v1.0 approval, September 2021](https://stage24.ogc.org/?p=955)
- [EDR Part 2 Publish-Subscribe approval](https://www.ogc.org/announcement/ogc-membership-approves-ogc-api-environmental-data-retrieval-part-2-publish-subscribe-workflow-as-an-official-ogc-standard/)
- [EDR Part 2 (23-057r1)](https://docs.ogc.org/is/23-057r1/23-057r1.html)
- [EDR OpenAPI schemas](https://github.com/opengeospatial/ogcapi-environmental-data-retrieval/tree/master/core/standard/openapi/oas31/schemas/collections)
- [EDR deployments list](https://github.com/opengeospatial/ogcapi-environmental-data-retrieval/blob/master/deployments.md)
- [EDR FAQ](https://github.com/opengeospatial/ogcapi-environmental-data-retrieval/wiki/FAQ)
- [NWS implementation talk](https://discourse.pangeo.io/t/september-15-2021-the-nws-implementation-of-the-ogc-api-environmental-data-retrieval/1808)
- [CoverageJSON overview (W3C)](https://www.w3.org/TR/covjson-overview/)
- [CoverageJSON OGC Community Standard (21-069r2)](https://docs.ogc.org/cs/21-069r2/21-069r2.pdf)
- [pygeoapi EDR publishing](https://docs.pygeoapi.io/en/latest/publishing/ogcapi-edr.html)
- [STAC and OGC API – Records](https://pretalx.com/fossgis2026/talk/SUTPAH/)
