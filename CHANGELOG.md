# Changelog

Notable changes to envlib. The format loosely follows [Keep a Changelog](https://keepachangelog.com/);
envlib does not promise SemVer before 1.0 — minor versions may change behavior.

## 0.1.1 (unreleased)

Companion to ebooklet 0.9.3 (now required):

- **Publish/register/deregister raise on partial push failure** instead of silently
  claiming success: ebooklet's `push()` can return a dict of failed keys (the pending
  changes are retained for retry) — envlib now checks it and raises `RuntimeError`
  naming the failed keys and the recovery path.
- **Remote-integrity faults are no longer mistaken for connectivity trouble**:
  ebooklet's new `RemoteIntegrityError` (the store contradicts its own index)
  propagates out of `refresh()` instead of triggering the offline-cache fallback.
- A stale catalogue cache pointing at a deleted-and-recreated RCG now warns with the
  actual fix (delete the named cache file) instead of the generic "not readable yet"
  bootstrap message.

## 0.1.0 (2026-07-08)

Initial release:

- **Metadata model**: the 11-field identity model with validation and normalization on assignment; permanent deterministic ids (`dataset_id`, `dataset_version_id`, `station_id`) locked by golden-vector tests and a dual-model independent review.
- **Vocabularies**: bundled controlled vocabularies (feature, variable = ODM2 ∪ envlib extensions, method, processing_level, aggregation_statistic, frequency_interval, license, CF standard names v94) with a curated `(variable, feature)` → CF standard_name mapping, user-dir overlay, and `refresh()` from the upstream APIs.
- **Catalogue**: RCG-backed discovery (`query()` with spatial/temporal/latest-version semantics, `distinct()` + plural browse properties), `validate()`, `publish()`/`register()`, `deregister()` with a shared-target guard, offline fallback to the cached index.
- Verified against live S3 (grid + station-time-series round trips) on Python 3.10–3.12.
