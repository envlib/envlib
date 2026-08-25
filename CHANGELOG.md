# Changelog

Notable changes to envlib. The format loosely follows [Keep a Changelog](https://keepachangelog.com/);
envlib does not promise SemVer before 1.0 — minor versions may change behavior.

## 0.1.6 (2026-08-25)

- **New public `envlib.validate_dataset(dataset, *, validate_cv=True)`** — the catalogue's own
  validation, without a catalogue, a remote, or a network call. It accepts either a path or an
  already-open cfdb `Dataset`/`EDataset`.

  This exists for producers that build envlib-shaped datasets and deliberately do **not** publish
  them — a private `EDataset` archive, for instance. Every structural guard envlib applies lives
  inside `Catalogue.publish`'s call to the private `_validate_dataset`, so such a dataset was
  previously never checked at all. The guard that usually matters is `_check_stations`, which
  recomputes each `station_id` from the geometry stored beside it — the entire basis of joining a
  forecast series to its measured counterpart.

  `Catalogue.validate` could not serve this: constructing a `Catalogue` requires a public RCG and
  performs a network refresh, neither of which a local build has or wants. `Catalogue.validate` is
  now a thin wrapper over the new function, so there is one implementation.

  Prefer passing an already-open dataset when you have one: reopening a remote-linked file starts
  a second session against the remote, and an open `EDataset` pulls transparently, so extents come
  from the whole dataset rather than from whichever chunks happen to be local.

## 0.1.5 (2026-08-25)

Support for cfdb's two forecast dataset types. **Requires cfdb >= 0.9.6** (a hard floor — the
types do not exist before it). Designed and dual-blind reviewed as round `ecan-theta-1`.

- **`ts_forecast` and `grid_forecast` validate and register.** Their axes are
  `(forecast_reference_time, forecast_period)` — init and lead — rather than `time`, so the
  long-standing "every envlib dataset must have a time coordinate" rule is now scoped to the
  non-forecast types.
- **`time_start` / `time_end` for a forecast dataset are the VALID range**: first init through
  *last init + longest lead*. That is what a consumer asking "does this cover my period?" means,
  and it keeps the catalogue semantically uniform with measured data, where valid time is
  observation time. Note `time_end` therefore sits in the future and corresponds to no coordinate
  value in the file — it is a bound, not an index.
- **`forecast_period` must declare a CF `units` attribute** and validation refuses a dataset
  without one. cfdb has no timedelta dtype, so lead is a bare integer; the units attr is the only
  thing that says what it means. (Adding a bare integer to a `datetime64[m]` axis silently adds
  *minutes*.) Bare `'m'` is refused as ambiguous — in CF it means metres; write `'min'`.
- **`forecast_period` must be an integer dtype.** A float lead used to truncate through `int()`,
  understating the range with no warning.
- **Both ends of the valid range come from the leads**: `first_init + min(lead)` through
  `last_init + max(lead)`. Deriving the start from the init alone was wrong twice over — a negative
  lead (an assimilation window) *inverted* the range, and a day-2-only product claimed a full extra
  day of coverage that does not exist in the file.
- **Forecast types must declare `method='forecast'`.** `dataset_type` is not one of the 11 hashed
  identity fields, so without this a forecast dataset and its measured counterpart produce the same
  `dataset_version_id`. `method` is an identity field and its vocabulary already carried `forecast`.
- **`_check_stations` now runs for `ts_forecast`**, not only `ts_ortho`. It is the guarantee that a
  station's stored id is reproducible from the geometry stored beside it — and the forecast↔measured
  join is nothing but those two hashes colliding at 5 decimal places.

### Fixed

- **Publishing a dataset whose `dataset_type` differs from an existing entry's is now refused
  instead of silently overwriting it.** Because `dataset_type` is not an identity field, two
  datasets that differ only in shape share a `dataset_version_id`, and the upsert replaced the
  first entry's `user_meta` — type, bbox and time range — with no warning. **This was reachable
  before the forecast types existed**, with a plain `grid`/`ts_ortho` pair. A genuine type change
  now requires deregistering first, or changing an identity field.
- The bounding-box branch keyed on exact `dataset_type == 'grid'` with a catch-all `else` that
  assumed station geometry, so `grid_forecast` was routed into the station branch and failed with a
  message about `ts_ortho`. Grid-shaped types now take the grid branch.
- Validation error messages no longer hardcode "ts_ortho" on paths reachable by other types.

## 0.1.4 (2026-08-25)

- **New `envlib.canonical_station_point()` — producers must store the point it returns, not
  the raw one.** A store that re-rounds a geometry as it writes it will hold a point that no
  longer derives the `station_id` written beside it, and the dataset then fails `validate()`
  forever with `'station_id' values do not match the envlib derivation`. cfdb is such a
  store: it encodes point coordinates with `shapely.to_wkt(..., rounding_precision=5)`,
  whose `trim=True` default rounds the shortest decimal **string** half-to-even, while
  `compute_station_id` rounds the underlying **binary** value via `wkt.dumps` (`trim=False`).
  The two disagree on roughly 9% of coordinates supplied to 6 decimal places — in every case
  an ordinate whose shortest representation ends in a trailing `5` past the 5th decimal, for
  which the decimal string is exactly halfway and the binary value is not. A canonical point
  has no 6th decimal left to round, so the store's round-trip becomes a fixed point. Verified
  over 2.42 M exhaustive lattice values plus poles, antimeridian, signed zero, subnormals and
  magnitudes to 1e300: zero round-trip failures. Found when a live ECan station at
  `(171.1091, -43.631905)` blocked a publish on 2026-08-24.

- **No ids changed.** `compute_station_id` is now `blake2b` over `canonical_station_point`'s
  WKB — a pure extraction of what it already did. Confirmed against 0.1.3 over ~143,000
  points (global lattices at 1–15 dp, every documented edge case, and the error contract)
  with zero differences in either ids or exception types and messages. Nothing needs
  republishing, and `canonical_station_point` is idempotent, so applying it to points that
  are already canonical costs nothing.

- **`_check_stations`' failure message now points at the real cause.** It previously ended
  "Use `envlib.compute_station_id` on the EPSG:4326 station points" — which is exactly what
  the broken producer had already done. It now reports the *stored* geometry alongside the
  two ids, says the stored geometry is the usual culprit rather than the id, and directs you
  to `canonical_station_point`.

## 0.1.3 (2026-07-25)

- **Publish now verifies the pushed objects before advertising the dataset.** `publish()`
  and `register()` fsck the member remote between the data push and the catalogue entry
  write (default `verify_objects=True`), and raise the new `PublishIntegrityError` if the
  committed index references objects that are not actually in the store — a *silent
  over-claim* (e.g. a storage layer that reported success for an upload that never durably
  landed). This closes a gap where such a dataset was advertised and served broken until a
  reader hit `RemoteIntegrityError`. The check runs on **every** publish (a broken remote
  must never be registered on any path) and adds one object listing per publish.
  `PublishIntegrityError` is a `ValidationError` (a `ValueError`), deliberately **not**
  ebooklet's `urllib3.HTTPError`-based `RemoteIntegrityError`, so a transport-retry wrapper
  cannot mistake a permanent integrity fault for a transient one. Recovery from an
  over-claim is **retract + full republish** (`deregister(..., delete_data=True)` then
  publish) — a plain re-run does **not** heal it. **Member credentials now need LIST**
  (`ListBucket` on S3, `listFiles` on B2) in addition to PUT/GET/HEAD/DELETE; a write-only
  key fails loud on the verify. Pass `verify_objects=False` to opt out.

## 0.1.2 (2026-07-13)

- **The public envlib commons is live, and a bare `Catalogue()` now connects to it** —
  read-only, credential-less, at `https://b2.envlib.xyz/file/envlib/envlib-commons/catalogue`
  (baked in as the default; the `ENVLIB_PUBLIC_RCG_URL` environment variable still
  overrides it for stand-ins, testing, or mirrors). The catalogue starts empty — the
  tethys production datasets migrate in next.

## 0.1.1 (2026-07-13)

Companion to ebooklet 0.10.0 and cfdb 0.9.1 (both now required):

- **Requires ebooklet >= 0.10.0** — the release carrying the architecture-roadmap
  rounds: the delete-safety fixes (deleting data that emptied a storage group could
  destroy unrelated sibling groups; deleting a remote whose key is a prefix of
  another's could destroy the sibling; delete-then-recreate of one key silently lost
  it on push), the persistent pending-change journal, the generational storage
  format 2 (readers can no longer observe a mid-push window), and the Phase-2 API
  (typed exceptions, `PushResult`, offline read mode).
- **Station-time-series remotes now open as their real class**: cfdb 0.9.1 fixes
  `open_edataset` for ts_ortho datasets, and envlib reads the new public
  `dataset_type` property instead of cfdb's private sys-metadata.

- **Publish/register/deregister raise on partial push failure** instead of silently
  claiming success: envlib checks `push()`'s `PushResult.failures` and raises
  `RuntimeError` naming the failed keys and the recovery path. `register()`'s
  metadata push, previously unchecked, is now covered too.
- **Remote-integrity faults are no longer mistaken for connectivity trouble**:
  ebooklet's `RemoteIntegrityError` (the store contradicts its own index)
  propagates out of `refresh()` instead of triggering the offline-cache fallback.
- **The offline-cache fallback moved into ebooklet** (`open_rcg(..., offline='auto')`):
  the hand-rolled direct booklet read of the cached index is retired. Behavior is
  unchanged for the common cases (unreachable remote + cache → warn and serve the
  cache; unreachable + no cache → raise, now as `ebooklet.OfflineError`).
- **`refresh()`'s bootstrap dispatch is typed** — and this FIXES a latent bug: the
  old blanket `except ValueError` swallowed ebooklet's `UnsupportedFormatError`
  (a ValueError subclass) and mislabeled a too-new remote format as "RCG source not
  readable yet". Format errors now raise loudly; only the true bootstrap case
  (`RemoteMissingError`) is treated as an empty source.
- A stale catalogue cache pointing at a deleted-and-recreated RCG now warns with the
  actual fix (delete the named cache file) instead of the generic "not readable yet"
  bootstrap message — dispatched on ebooklet's typed `UUIDMismatchError` instead of
  string-matching the message.

## 0.1.0 (2026-07-08)

Initial release:

- **Metadata model**: the 11-field identity model with validation and normalization on assignment; permanent deterministic ids (`dataset_id`, `dataset_version_id`, `station_id`) locked by golden-vector tests and a dual-model independent review.
- **Vocabularies**: bundled controlled vocabularies (feature, variable = ODM2 ∪ envlib extensions, method, processing_level, aggregation_statistic, frequency_interval, license, CF standard names v94) with a curated `(variable, feature)` → CF standard_name mapping, user-dir overlay, and `refresh()` from the upstream APIs.
- **Catalogue**: RCG-backed discovery (`query()` with spatial/temporal/latest-version semantics, `distinct()` + plural browse properties), `validate()`, `publish()`/`register()`, `deregister()` with a shared-target guard, offline fallback to the cached index.
- Verified against live S3 (grid + station-time-series round trips) on Python 3.10–3.12.
