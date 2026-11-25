# A read-only data API for envlib: feasibility and the OGC API – EDR mapping

_Assessment, 2026-10-07. Not a plan: nothing here is decided beyond what the Backlog item in
`OPEN_WORK.md` records._

_Design decided 2026-11-23: see §11, which supersedes the cache and handle rows of §3, the
instance row of §5 (corrected in place) and the Swarm layout of §8._

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
remotes before sizing the chunk budget. The ECan rows were per-key with `(1, 25000)` chunks when
measured; they move to `(1, 2520)` chunks in small write-order groups (the telemetry layout, decided
2026-10-08), so re-measure them too.

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
| `locations` and `locations/{station_ref}` | ts_ortho stations. One station's history is exactly what one-station chunks are built for (`(1, 2520)` under the 2026-10 telemetry layout; a two-week window is 1–2 chunks). Several ids can be comma-separated. |
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
| `dataset_version_id` | **not an instance** (corrected 2026-11-23, §11): instances are reserved for forecast runs. A collection serves its latest version, as `Catalogue.query()` returns. The id rides in the `envlib` object and the `ETag`, and every version is discoverable through `/catalogue`. |
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

`f=CSV` should ship from the start, and `f=netCDF4` for large cube requests, since cfdb already
exports netCDF. (The ts_ortho netCDF export currently fails on the geometry coordinate; see the
`[cfdb]` Backlog item.) EDR's `output_formats` is an open list of strings, so a binary format such as
Parquet could be added later.

### Response compression: zstd

**Decision (Mike, 2026-10-07): zstd level 1, with a gzip level 1 fallback.** EDR leaves compression
to HTTP. The 1.2 text never mentions it, and OGC API – Features Part 1 says "the standard HTTP
mechanisms can be used". So the server negotiates per request from the client's `Accept-Encoding`:

1. zstd offered → `Content-Encoding: zstd`, level 1.
2. otherwise gzip offered → `Content-Encoding: gzip`, level 1.
3. neither → an uncompressed body.

The fallback is needed because the most common Python HTTP client never offers zstd. Default
`Accept-Encoding`, checked 2026-10-07:

| Client | Offers |
|---|---|
| `requests` 2.x (urllib3 2.8.0) | `gzip, deflate`, even with `zstandard` installed |
| `httpx` 0.28.1 | `gzip, deflate`, plus `zstd` only when `zstandard` is installed |
| curl 8.5 with `--compressed` | zstd, when libcurl is built with it (this build is); curl sends no `Accept-Encoding` without the flag |

Without the fallback, a `requests` user would download 4.73 MB instead of 0.79 MB for the response
below.

Measured 2026-10-07 on one ECan streamflow station's full history (183,570 hours, 142,230 non-missing),
serialised compactly:

| Body | Raw | zstd-1 | zstd-3 | gzip-1 | gzip-6 |
|---|---|---|---|---|---|
| CoverageJSON `PointSeries` | 4.73 MB | **0.36 MB (13×), 5 ms** | 0.35 MB, 7 ms | **0.79 MB (6×), 38 ms** | 0.73 MB, 147 ms |
| CSV | 4.20 MB | 0.66 MB (6×), 6 ms | 0.68 MB, 8 ms | 0.94 MB (4×), 40 ms | 0.77 MB, 156 ms |

Level 1 costs almost nothing in size for either codec and is markedly faster: zstd-1 is within 3 % of
zstd-3, and gzip-1 is within 7 % of gzip-6 at a quarter of the CPU. Speed matters as much as size,
because a warm read of this station takes under 10 ms (§1). zstd-1 keeps compression a small fraction
of the response time, whereas gzip would dominate it. CoverageJSON is larger than CSV raw but smaller
compressed, because its repeated timestamp strings compress very well.

netCDF4 responses carry their own compression inside the file. Use zlib there for compatibility,
since zstd inside netCDF needs filter plugins on the reader's side, and do not compress them again
over HTTP.

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

**Two tiers for gridded requests.** Agencies usually serve gridded data in one of two ways. A file
or object server hands out whole files (e.g. netCDF on S3). A job queue processes requests in the
background (e.g. CDS, where much of ERA5 sits in ECMWF's MARS archive). Synchronous cube subsetting
exists (THREDDS NCSS, ERDDAP griddap, NWS's EDR deployment), but it relies on chunked files on local
disk. envlib/cfdb can serve `cube` from object storage because its chunk layouts are chosen for both
time-series and map reads and the server keeps a warm cache. That capability has a ceiling: one cold
WRF map took 13 s (§1), and ten years of one full-domain WRF variable is about 59 GB raw
(87,660 h × 534 × 315 × 4 bytes). So the API answers in two tiers and deliberately stops there:

1. **Small and interactive:** EDR `position`/`area`/`cube` within the chunk budget, served
   synchronously.
2. **Bulk: direct access.** A request over the budget gets a 413 that points the user to the envlib
   Python package and the dataset's `db_url`. Every public dataset can be opened directly
   (`Catalogue().query(...)[0].open()`, or `cfdb.open_edataset` on the `db_url`), and the client then
   pulls exactly the chunks it needs. This is envlib's chunk-level version of the "file server" path,
   and it needs nothing new on the server.
**Non-goal: a CDS-style processing service** (Mike, 2026-10-07). The API will not run job queues or
large servers that process bulk requests on the user's behalf. A user who wants more than the
synchronous budget uses envlib directly and pulls as much as they want, so the compute and transfer
for bulk work stay on the user's side. That keeps the service small enough to run as ordinary Swarm
replicas.

The 413 body names the limit that was exceeded, the request's estimated size, the collection's
`dataset_version_id` and its `db_url`, and a short snippet of envlib code that opens it. EDR asks for
exactly this kind of message ("explaining the query limits imposed by the server implementation").

**Swarm layout:**
- **Concurrency:** one uvicorn worker per replica with a thread pool, and dataset handles opened at
  startup and shared across threads. Scale with replicas. Never point two processes at one cache
  directory.
- **Cache:** a node-local volume per replica with a size cap and eviction (§3).
- **Freshness:** a refresh timer for the catalogue and the hourly datasets.
- **HTTP caching:** `Cache-Control`/`ETag` derived from `dataset_version_id` plus the remote
  timestamp. Frozen datasets can be cached by a CDN for a long time.
- **Limits:** a per-request chunk budget returning 413 that points to direct access (tier 2 above).
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
  - the §6 compression table (an isolated environment pinned to envlib 0.1.7 and ebooklet 0.10.5,
    because the project venv had moved to ebooklet 0.11.0, which refuses the format 2 commons
    catalogue);
  - a text search of EDR 1.2 and OGC API – Features Part 1 for compression terms;
  - the default `Accept-Encoding` of `requests` and `httpx` (throwaway environments, with and without
    `zstandard`) and the curl build features;
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
  - the §8 statements about THREDDS NCSS, ERDDAP griddap and ERA5 in MARS (background knowledge, not
    looked up this session);
  - the 1.2 changes beyond OGC's compatibility statement;
  - the spec prose on extension properties (the schema was relied on);
  - that NERC resolves every envlib `standard_name`;
  - pygeoapi runtime collections;
  - cfdb thread-safety within a process;
  - zstd `Content-Encoding` support in browsers, R and GIS clients (believed current in Chrome and
    Firefox);
  - whether a CDN in front would re-encode zstd responses for clients that do not offer it;
  - behaviour under concurrent load.

## 11. Decisions and spike, 2026-11-23

_Design discussion with Mike, 2026-11-23. The spike's scripts and raw results are in
`plans/spikes/edr-mongo-store/`._

**Implemented and released 2026-11-24 as ebooklet 0.13.0 (`ebooklet.mongo`) and cfdb 0.12.0
(`open_store_dataset`).** The authority for how the read path now behaves is ebooklet's `docs/ops.md`,
"The MongoDB read path"; this section is the design as discussed. Two review rounds (`edr-mongo-plan-1`
and `edr-mongo-code-1`; records in `ebooklet/planning/`) changed these points:
- **The 404 rule.** The API compares one HEAD of the db object with the `applied` pair read when the store
  was built (equal → 500, different → 503). `checked_at` no longer classifies anything: compared with
  the time of the 404, it almost never gave a 500.
- **The worker is stateless.** It diffs against MongoDB's entries, not an index held in memory.
- **The write order** gained a claim step: 0 (`rev`+1 and `applying`), then entries, the dataset document,
  deletes, and `applied` written last.
- **Requests overlapping an apply retry.** A store refuses to build while `applying` is set, and the API
  must call `store.verify()` before responding. Without that, old metadata could decode new chunks.
- **Per-key objects overwritten since the index copy** raise `StaleIndexError`.
- **Exactly one refresher is a hard requirement.** Two overlapping refreshers diverge for good.
- **The schema:** the collections use per-collection compressors (zstd for `entries` and `datasets`, none
  for `chunks`), and the remote's `ebooklet_type` is recorded.
- **The store reads public remotes only** (`object_reader` takes a `db_url`). The refresh accepts any
  `S3Connection`.

**Plan 2 (the worker and MongoDB)** is built in the repo `envlib/envlib-api`. Its README covers how it
runs and its operating rules, and its `planning/` holds the plan and the review records. It differs
from "The worker" below in these ways:
- every catalogued version is mirrored, keyed by `dataset_version_id`;
- datasets that leave the catalogue are retired by tombstone, behind guards;
- MongoDB is version 9.0, with a custom role;
- there is no lease.

**Plan 3 (the API core and station data)** is built in the same repo (`envlib_api/api/`; its README,
"The API"). Plan review `edr-api-plan-3` changed it from "The API" and "The EDR surface" below in
these ways:
- **Reads:** a request reads its data in one batched fetch (`store.load_items` of every data key),
  not chunk by chunk. Cold, all stations × 48 h took 22–112 s station by station and 0.3–10 s batched.
- **Time:** `datetime` selects by label containment, through the API's own `searchsorted`, not cfdb's
  `.loc`.
- **Output:**
  - values print at the variable's stored precision, not shortest round-trip;
  - several stations answer a CoverageJSON `CoverageCollection` of `PointSeries`, not the
    `MultiPointSeries` of §6, because `MultiPointSeries` cannot carry station ids;
  - a query that selects nothing answers 204.
- **Retries:** only a refused store build or a failed `verify()` is retried. An index that is behind
  the remote answers 503 at once.

**Plan 4 (grid queries)** is built in the same repo (`envlib_api/api/grid.py`; the README's "Grids"),
and was released as envlib-api 0.3.0 on 2026-11-25.
Plan review `edr-api-plan-4` and Mike's decisions changed it from "The EDR surface" below in these
ways:
- **The cell** is the nearest stored centre on each axis. It is not a step-based lattice, because the
  SST centres are float32 values with irregular spacing.
- **A cube** is the smallest grid rectangle holding every cell whose centre is in the bbox, unmasked.
  Longitudes are compared mod 360.
- **A WRF cube** comes back in the grid's own Lambert CRS: a documented deviation from EDR's default
  of the extent's CRS.
- **The caps** keep plan 3's defaults (Mike, 2026-11-25), so a full WRF map at one hour (322 chunks,
  623 MB decoded) answers 413.

**Plan 5 (catalogue discovery)** is built in envlib 0.1.9 (`envlib.match_entries`,
`envlib.latest_per_dataset`, `envlib.distinct_values`) and in envlib-api 0.4.0 (`envlib_api/api/catalogue.py`;
the README's "The catalogue"). Neither is released yet. Plan review `edr-api-plan-5` and Mike's decisions
changed it from "Versions and discovery" below in these ways:
- **A tie on `created_at`** goes to the greater `dataset_version_id` in envlib too, whatever the
  catalogue order.
- **The station bbox** is the shortest arc of longitude holding the stations. Before, two live ECan
  entries spanned about 350°, and a bbox search over Patagonia returned them. Entries correct on
  republish.
- **`/catalogue` pages by a cursor** (`after`), not an offset, and clamps a `limit` over the cap.
- **Each entry links** to its EDR collection with `alternate`, and an older version links to the latest
  with `latest-version` (RFC 5829).
- **CORS** headers are on every answer (moved from plan 6, Mike, 2026-11-25), so a catalogue browser
  on another site can call the API.

### Core

**Decided.** The API serves envlib datasets for real-time use. Historical and bulk work goes through
the envlib and cfdb packages. One worker process mirrors the B2 catalogue and each dataset's remote
index into MongoDB. Stateless FastAPI processes answer every request from MongoDB. On a cache miss
they fill an insert-only chunk cache in MongoDB from B2. The worker and the API never talk to each
other, and MongoDB is the API's only cache.

**Spike.** A prototype store under cfdb read three live datasets exactly as `cfdb.open_edataset`
does. It used ebooklet's own remote fetchers unchanged. Warm MongoDB reads took 2–15 ms, and a full
WRF map took 170 ms (mostly decompression). Cold reads cost the same B2 round trips as plain ebooklet.

**Top risks.** (1) A chunk fetch can 404 between a writer's push and the worker's next poll. The API
retries and then answers 503 or a loud 500 (see "A 404 on a chunk"). (2) One response can span two
consecutive pushes across different chunks. The worker's write order stops the metadata from running
ahead of the entries. (3) A stalled worker serves stale data silently unless `checked_at` is
watched.

### The worker

- It is the only process that reads db objects and the catalogue from B2.
- It mirrors the B2 catalogue into MongoDB. B2 stays the master, and the mirror is never edited. The
  worker's list of datasets to poll comes from the mirror.
- It polls each dataset's db object with a HEAD request. When the remote timestamp moves, it
  downloads the db object and diffs the new index against the previous one, which it holds in memory.
- It applies each diff in this order: (1) upsert changed and new entries, (2) update the metadata
  document, (3) delete the entries of removed keys. The metadata therefore never runs ahead of the
  entries.
- Index entries are one document per key: `{key, ts, gid, gen, offset, len}`. Each entry carries its
  group generation, so the read path needs no manifest. A diff compares whole entries because a
  repack moves members whose `ts` is unchanged.
- It updates `checked_at` on every poll, including polls that find no change.
- It does nothing else. In particular it does not prefill chunks.
- Known limit: one response can span two consecutive pushes across different chunks.

Full snapshots per push were rejected. They would rewrite the whole index on every change: about 10k
entries an hour for ECan, and 156k per WRF variable whenever it changes.

### The API

- Every request queries MongoDB. There are no process-level caches.
- Each request builds its own store object and its own cfdb object. A process shares no mutable
  state between requests, so cfdb thread-safety is not a concern.
- The request flow is:
  1. read the dataset's metadata document;
  2. resolve the selection on the coordinates through cfdb's native selection;
  3. compute the request's costs and check the limits;
  4. read the index entries;
  5. read the cached chunks;
  6. fill misses from B2 with ebooklet's fetchers;
  7. decode with cfdb, and encode the response.
- The chunk cache is insert-only, keyed `(db_url, chunk key, ts)`. The `ts` is the timestamp of the
  bytes actually fetched, which for per-key storage is the object's own metadata timestamp. A revised
  chunk therefore gets a new id, and concurrent fills of one chunk are harmless.
- A TTL index on the fetch time expires cache documents. The TTL length is open.
- Coordinates are read natively through the chunk path. Special coordinate indexing is added only
  if measurement shows a real problem.

### A 404 on a chunk

The API never writes the index. It handles a 404 like this:

1. Re-read the chunk's index entry from MongoDB. If it names a new generation, fetch again.
2. If the entry is unchanged, wait briefly and repeat step 1, up to a cap of a second or two.
3. After the cap:
   - **The worker has not checked since the 404** (`checked_at` is older than it): answer 503 with
     `Retry-After` set to the poll interval.
   - **The worker has checked and the entry is unchanged**: this is an integrity fault. Answer 500
     and log it loudly.

### Limits

- Both caps are computed after the coordinates are resolved and before any data chunk is read:
  - **decoded bytes touched**: 100 MB per request;
  - **values returned**: about 1–2 million per request.
- A request over either cap gets a 413 that points to direct envlib access (§8).
- Per-IP quotas use the same cost unit over two windows, hourly and 24-hourly. Each window is a set
  of hourly buckets in MongoDB updated with `$inc`. The placeholders are 2 GB per hour and 10 GB per
  24 h. A request that would exceed a quota gets a 429 with `Retry-After`.
- Traefik's rate-limit middleware limits the number of requests.
- Cloudflare is in front. The client IP comes from `CF-Connecting-IP`, and the origin accepts only
  Cloudflare's address ranges. IPv6 clients are bucketed by /64.
- Mike's servers are allowlisted. Dashboards on the swarm call the API on an internal entrypoint,
  and external servers are allowlisted by IP.

### The EDR surface

- **Collections.**
  - The collection `id` is the `dataset_id`, and `title` is readable. EDR defines `id` as an
    identifier and `title` as the label.
  - A collection serves its latest version only. The `dataset_version_id` rides in the `envlib`
    object and the `ETag`.
  - Only catalogued envlib datasets are served.
- **Queries.**
  - `ts_ortho` collections offer `/locations`, `/area` and `/radius`. The `locId` is `station_id`,
    which is unique per row in every ECan dataset. `station_ref` is searchable, and it repeats in the
    raw datasets.
  - Grid collections offer `/position` and `/cube`. Grid `/area` comes later.
- **Parameters and formats.** The parameters are `datetime`, `parameter-name`, `coords`, `bbox`, `f`
  and `limit`, with CRS84 input only. The formats are CoverageJSON, CSV and GeoJSON. netCDF waits for
  the ts_ortho export fix (see the `[cfdb]` item in `OPEN_WORK.md`).
- **Extents.** The collection extents come from the catalogue entry. This was checked 2026-11-23: the
  catalogue's `time_end` equals the last time value of every ECan dataset.

### Forecasts: later, but designed for now

No forecast dataset is in envlib yet, so nothing here is implemented now. Instances are forecast runs.
An instance id is the ISO reference time, as in EDR 1.2's own Annex E.4 example. The instance list
covers the last 30 days. Older runs are reached through envlib directly. `/instances/latest/…`
redirects to the current run and is not listed. A query on the collection itself returns the best
estimate: for each valid time, the newest run with a finite value. A collection with this default
cannot also carry custom run dimensions, because Requirement A.76 statement E would make the default
"every run".

The rest of the implementation must leave room for this. The `instances` routes stay free. Extents
come from envlib's forecast helper (`_forecast_time_range`). The cost calculation handles
three-dimensional forecast selections.

### Versions and discovery

- **`GET /catalogue`** is the HTTP form of `Catalogue.query()`. It has the same queryable fields and
  the same spatial and temporal filters. It returns the latest version by default and every version
  on request.
- Each entry carries the `dataset_version_id`, the metadata, the `db_url`, a `latest` flag, a link to
  the EDR collection when that version is served, and an envlib snippet that opens it.
- **`GET /catalogue/distinct/{field}`** mirrors `distinct()`.
- Each EDR collection links to its versions with `rel="version-history"`.
- The matching rules have one definition. envlib exposes its catalogue matching as a public function,
  and the API calls it rather than reimplementing the rules in MongoDB queries.
- STAC or OGC API – Records are the later route for external harvesting.

### Stack changes this needs

- **ebooklet** (an optional `ebooklet[mongo]` extra) gets two things: the worker's refresh (fetch,
  parse, diff and apply in order) and the read-only store.
- **cfdb** gets a public hook to open a dataset on a supplied store.
- **envlib** gets the public catalogue-matching function.

### Spike results

The spike ran 2026-11-23 on the released stack (ebooklet 0.11.2, booklet 0.12.11, cfdb 0.11.0,
envlib 0.1.8), pymongo 4.20.1 and MongoDB 8.0 on tmpfs, all reading the live remotes.

| Read | Plain ebooklet, cold | MongoDB store, cold | MongoDB warm | Hot (in process) |
|---|---|---|---|---|
| ECan 1 station, 2 weeks | 0.64 s | 0.80–0.85 s | 4 ms | 0.4 ms |
| ECan 1 station, full history (73 chunks) | 7.8 / 2.0 s | 1.9 / 7.3 s | 3 ms | 2 ms |
| ECan 144 stations, 48 h | 0.41–0.60 s | 0.48–0.60 s | 5 ms | 4 ms |
| WRF 1 cell, 1 year | 3.2–3.4 s | 3.5 s | 14 ms | 6 ms |
| WRF full map, 1 hour (322 chunks) | 2.1–2.2 s | 1.4–2.1 s | 170 ms | 148 ms |
| Flow forecast, latest run | 1.0–1.2 s | 1.0–1.3 s | 2 ms | 0.3 ms |
| Flow forecast, last 120 runs (per-key) | 3.0–6.8 s | 2.5–2.6 s | 3 ms | 2 ms |

- **Equality.** Every array equalled plain `open_edataset` exactly, NaN positions included, in 84
  comparisons across all runs.
- **Planted defects.**
  - A miss that returns nothing read DIFFERENT.
  - Silent fetchers raised.
  - One 404 healed and read EQUAL.
  - A persistent 404 raised.
  - A truncated cached chunk raised.
  - A swapped cached chunk read DIFFERENT.
  - A first one-byte-flip mutant read EQUAL. The flip most likely fell in an hour the map does not
    read, so it was replaced by the truncation and swap mutants.
- **Concurrency.** Six processes filling one empty collection were all correct and produced no
  duplicate documents. Together they made 3,918 B2 fetches for 671 unique chunks.
- **Format 3 and size.** A cold full WRF map on format 3 takes about 2 s and pulls about 22 MB, down
  from 13 s on format 2 (§1). The largest compressed chunk was 174 KB, far below MongoDB's 16 MB
  document limit.
- **Indexes in MongoDB.** The WRF precipitation index has 156,500 entries. It parsed in 0.24 s and
  inserted in 0.43 s. A 322-key lookup took 0.8–1.0 ms. 167k entries came to 17.3 MB.
- **Eviction.** A capped collection evicted oldest-first and stayed exactly correct. TTL was chosen
  instead.

### Open for the plan

- ~~The poll interval for each dataset type.~~ **Settled by plan 2:** one interval for every dataset,
  60 s (`poll_seconds` in `envlib-api`'s config; at most 150).
- ~~The TTL length.~~ **Settled by plan 2:** 7 days (`chunk_ttl_days`), to be revisited when plan 6
  calibrates the caps and quotas.
- Calibrating the caps and quotas on the swarm. Plan 3 set the caps' defaults, and added a CSV row cap
  (the `[api]` section of `envlib-api/envlib_api/config.py`). The cluster has four nodes, not the two VPSes assumed
  here (checked 2026-11-24): uswest9 and uswest12 are processors, and uswest10 and uswest11 are web
  servers. uswest11 has 8 vCPUs and 23 GiB, and runs the MongoDB and the refresher.
- The Cloudflare details: compression and re-encoding, caching, and locking the origin.
- ~~The repo~~ **Settled by plan 2:** the repo is `envlib/envlib-api`. The deployment for
  `api.envlib.xyz` is plan 6.

### Verification status of this section

- **Ran:** the spike, including the equality comparisons, the planted defects, the concurrency run,
  the capped collection and the index measurements. Also a check of the catalogue's `time_end` and of
  `station_id` uniqueness against the live ECan datasets.
- **Read:**
  - EDR 1.2 §4.5, §8.2.9, §8.2.10, Requirement A.76, Tables C.5, C.8 and C.10, and Annex E.4, all
    verbatim;
  - the cfdb store contract and ebooklet's fetchers in source.
- **Accepted, not verified:** these came from subagent reports.
  - CoverageJSON forbids extra domain axes and lists multiple time dimensions as future work.
  - EDR issue #712 is open, about a default or latest instance.
  - pygeoapi lacks EDR instances.
- **Not verified:**
  - MongoDB on disk and across the network;
  - B2 latency from the VPSes;
  - sustained load;
  - healing against a real writer commit and GC (only simulated);
  - that capped collections forbid size-changing updates in MongoDB 8;
  - that RFC 5829 defines `version-history`;
  - Cloudflare's behaviour.

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
