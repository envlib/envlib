# Changelog

Notable changes to envlib. The format loosely follows [Keep a Changelog](https://keepachangelog.com/);
envlib does not promise SemVer before 1.0 — minor versions may change behavior.

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
