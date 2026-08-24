# Changelog

Notable changes to envlib. The format loosely follows [Keep a Changelog](https://keepachangelog.com/);
envlib does not promise SemVer before 1.0 — minor versions may change behavior.

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
