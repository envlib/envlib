# envlib — Open Work

Tracks **verification debts** (work done but not yet proven; each has a close-check — remove the item once it passes) and **backlog** (known work not yet started) for the **stack-development track** (the envlib/cfdb/ebooklet packages themselves). The **datasets/ingestion track** (ingest toolkit + per-source repos, dataset selection, the tethys data migration) is tracked separately in `envlib-ingest-base/OPEN_WORK.md` (split 2026-07-19). Items are tagged: `[envlib]` (this repo), `[booklet]`, `[s3func]`, `[ebooklet]`, `[cfdb]`, `[cfdb-ingest]`, `[ifs-download]`, `[infra]`, `[MEGA]` and `[new service]`. The Backlog is grouped by the package an item changes. Completed items move to **`OPEN_WORK_DONE.md`** (newest first), so this file shows only open work.

_Status 2026-11-26 (checked on PyPI):
- **The released stack:** booklet 0.12.11, s3func 0.10.0, ebooklet 0.13.2 and cfdb 0.12.0 (ebooklet 0.13.0 and
  cfdb 0.12.0 released 2026-11-24, carrying the MongoDB read path of "EDR plan 1: the MongoDB read path";
  ebooklet 0.13.1 the same day, with the incarnation token from "EDR plan 2: the worker service and MongoDB on
  the swarm"; ebooklet 0.13.2 on 2026-11-25, with `MongoStore(http_session=)` from "EDR plan 3: the API core
  and station data"), envlib 0.1.9 (2026-11-26, with the public catalogue matching of "EDR plan 5:
  catalogue discovery") and envlib-ingest-base 0.8.0.
- **Live datasets:** every one is on ebooklet storage format 3.
- **Locks:** cfdb, envlib, envlib-api, `envlib-ingest-base` and `-ecan-env` are refreshed to ebooklet 0.13.2
  (envlib-api's and envlib's are committed; the other three are not yet). envlib-api, `envlib-ingest-base` and
  `-ecan-env` are re-locked to envlib 0.1.9 too, uncommitted. `-esa-sst`, `-wrf-3k` and `flow-forecast-app-envlib` are on 0.13.0, with uncommitted lock
  changes of their own. The rest is the item "Refresh locks to booklet 0.12.11 and ebooklet 0.11.2".
- **The EDR API:** its work is the `### EDR API (new service)` group. Plans 1, 2 and 3 are closed (in
  `OPEN_WORK_DONE.md`). The refresher and MongoDB 9.0 run on uswest11 as the stack `envlib-api` (repo
  `envlib/envlib-api`). The API for station data is built in the same repo and runs locally; it is
  deployed in "EDR plan 6: going public". Plan 4 (grid queries) closed 2026-11-25 with envlib-api
  0.3.0 on PyPI. Plan 5 (catalogue discovery) closed 2026-11-26 with envlib 0.1.9 and envlib-api
  0.4.0 on PyPI. "EDR plan 7: the public docs site" comes next, then "EDR plan 6: going public"._

## Verification debts

The live rollout of the released stack is tracked in the ingestion file (below).

- [ ] **[new service] Verify the envlib-api refresher's Sentry alerts** (added 2026-11-24, from closing "EDR plan 2: the worker service and MongoDB on the swarm"). The refresher reports errors and a cron check-in each cycle (`envlib-api/envlib_api/refresher.py`), but no Sentry side was checked: during the live close-checks the refresher was scaled to 0 for 4 minutes, and whether its monitor alerted was not looked at. **Close-check:** Sentry shows the `envlib-api-refresher` cron monitor receiving check-ins, and a planned `docker service scale envlib-api_refresher=0` for more than the 5-minute margin raises a missed check-in alert.
- [ ] **[cfdb + envlib] The docs-example tests (Sybil) and `mkdocs build --strict`: built, not yet run on GitHub**
  (built 2026-11-14 from the Backlog item "Test the docs' code examples automatically (Sybil), and build the sites
  with `--strict`"; plan reviewed in round `docs-tests-plan-1`, Fable 5.2 + Sonnet 5.5). Every Python block of `README.md` and `docs/` now
  runs as a test (`uv run pytest README.md docs`; envlib adds `--docs-live` for the blocks that read the live
  commons). The machinery and the rules for writing examples are in each repo's `CLAUDE.md`, "Docs examples are
  tests", which also lists the known limits accepted as rare. **Code review `docs-tests-code-1`** (Fable 5.2; the
  Sonnet 5.5 arm was killed at 15 min with no report, and Mike chose not to relaunch it) found 13 issues plus 2 on
  the pages. All the non-rare ones are fixed: a `+SKIP` doctest option or text after a blank line in a `>>>` block
  passed unseen; a widened skip region left the manifest unchanged (it now records `covers=N`); the value-comment
  lint saw only top-level statements; a chained exception turned a failure into a pytest INTERNALERROR (a Sybil bug,
  worked around in `docs_support.py`); the moto server outlived a SIGTERM or SIGKILL of pytest; the `.data` guard and
  S3 rewrite stayed installed for unit runs; four pages relied on hidden imports; `indexing.md` swapped the file
  behind `file_path`; and the combining page now warns visibly about the `overlap` bug (cfdb item below).
  **Run locally (2026-11-14, after the fixes):** envlib offline 59 passed and 43 skipped in 12 s, live 99 passed
  and 1 skipped in 40 s; cfdb 219 passed and 2 skipped in 13 s; both `mkdocs build --strict` pass; the unit suites
  keep their test sets (envlib 187 = 185 + 2 inventory tests; cfdb 514 = 512 + 2). 22 planted defects in envlib
  and 11 in cfdb each failed with their named cause, re-planted after the last harness change. **Not yet run:**
  the GitHub jobs (`test.yml` `docs` and envlib `docs-live` on push to `dev`; `documentation.yml` with `--strict`;
  envlib's weekly `docs-live.yml`, which uses `main` only). **Close-check:** after Mike pushes `dev`, both repos' `docs` jobs and envlib's `docs-live` job pass;
  after the dev → main merge, the deploy builds with `--strict` and the first scheduled live run passes.

## Backlog

### Cross-cutting

- [ ] **[cfdb + envlib] The public docs sites lag the releases: merge `dev` into `main` to redeploy them**
  (added 2026-11-14). Both sites build from `main` on push (`.github/workflows/documentation.yml`), and both
  `main`s are at 2026-09-24. So mullenkamp.github.io/cfdb shows 0.10.0, and envlib.github.io/envlib shows "0.1.7
  (unreleased)", while PyPI has cfdb 0.12.0 (2026-11-24) and envlib 0.1.9 (2026-11-26). The live pages document
  `num_groups`, which raises under both releases, and cfdb's S3 example uses `S3Connection(object_key=...)`,
  which ebooklet never had. A docs audit on 2026-11-14 fixed the rest on `dev` (uncommitted until Mike commits):
  dated changelogs; that old hash-grouped remotes cannot be opened and how to move them; that the storage mode is
  fixed per remote; wrong reference signatures and defaults in cfdb; the forecast types in cfdb's `dataset_type`
  docstrings; envlib's stale "not hosted yet" notes and quickstart id; `PublishIntegrityError` exported, and it
  and `validate_dataset` added to envlib's reference. Close-check: each live changelog page shows the PyPI
  version, and the live S3 and publishing guides have no `num_groups`. Since then the cfdb fixes (2026-11-14) are
  committed as `8a623d8` and the envlib ones as `7597861`/`b50256a`, all on `dev`; the merge to `main` remains.
  The merge will also deploy the docs changes made for the docs-example tests (uncommitted on `dev` as of
  2026-11-14; the verification debt "The docs-example tests (Sybil) and `mkdocs build --strict`").
- [ ] **[cfdb/envlib] No representation for IRREGULAR station series (`frequency_interval=None`) — and it is UPSTREAM of two other workstreams** (surfaced 2026-08-03 while planning the ECan tethys migration; Mike's ruling that cfdb should solve this BEFORE the tethys archiver, not after). The identity layer already anticipates irregular data — `frequency_interval` is a closed CV whose `None` entry means "irregular", and `Metadata` accepts it — but there is nowhere to *store* it: `ts_ortho` is a dense fixed-step axis by definition, and `envlib_ingest_base.tsortho._freq_step` raises on `None`. So a producer can legally *describe* an irregular dataset and then cannot *build* one. **Concrete driver: ~30 of the 36 quality-controlled ECan datasets in tethys are irregular** (lab sample analyses, manual gaugings; 1900→2022) — single-copy in a system being decommissioned, no migration path today, and consequently excluded from the ECan data-foundation migration. **Why this must land before the tethys archiver:** the archiver needs the same representation, so if it invents its own you get two incompatible irregular layouts plus a conversion later; define it once here and the archiver mirrors it. **Candidate form** — a long/tidy table, three parallel columns (`station_index`, `time`, `value`), which is CF's *indexed ragged array* described without the DSG framing. **Note the dense-with-NaN trick that makes `ts_ortho` cheap does NOT transfer**: for regular data the axis comes from the declared cadence and NaN runs compress away, but an irregular dataset has **no cadence to build an axis from** — the axis would be the union of observed timestamps, roughly as long as the observation count itself, giving ~n_stations × n_observations cells for n_observations values. That is a representation problem, not a compression one. Design questions when picked up: a new `dataset_type` alongside `ts_ortho` or a variant of it; how `Catalogue.validate` recognises it; whether the toolkit grows a `build_local`/`merge_dataset` pair for it or irregular data is append-only. Context: `tethys-repos/tethys-archiver/planning/design-notes.md` (moved 2026-08-03 out of the ecan-flow-forecasts repo, where it was first drafted). **CORRECTION 2026-08-03 to the dense-storage figures this entry originally cited** (dense zlib-4 12.0 MB vs ragged 11.9 MB, "~1% penalty"): that benchmark used an axis **10× too short** — 56,614 steps against a real 565,824 — so the absolute numbers were wrong, though the sparsity ratio (78%) happened to be about right. Re-measured on real data with the whole file: dense gzip-1 is **1.50× the source without HDF5 `shuffle` and 0.61× with it**. `shuffle=True` is the load-bearing flag and was missing from the original comparison entirely. **Status: the archiver shipped v1 WITHOUT irregular support**, covering only the 6 regular-cadence ECan QC datasets — so the ~30 irregular ones remain single-copy and unbacked. ⚠️ **CORRECTION 2026-08-07: this item is NOT what stands between them and a backup, and saying so has been delaying one.** A *representation* is needed to put irregular data into cfdb/envlib; it is not needed to **copy the tethys objects to disk**. Those objects are public zstd'd netCDF chunks with a JSON manifest — `rclone`/HTTP against the `tethys/v4/{dataset_id}/…` prefix preserves them byte-for-byte with no schema decision at all, and they can be converted later once this item lands. **Newly urgent:** ECan's raw tethys extractions were reset around 2026-05-07 (ten datasets across five parameters all start that day; raw streamflow at 2025-11-12), losing their prior history. The QC datasets were checked on 2026-08-07 and are intact — same 59 datasets as the archive snapshot, zero start dates moved — but there is now precedent for loss in this bucket, and ~30 single-copy datasets reaching back to 1900 are sitting behind it. **Do the dumb byte-copy first; solve the format afterwards.** **Status 2026-10-09:** no irregular dataset is in envlib yet. Mike recalls that all the tethys QC data has been archived. The archiver's own record says the irregular datasets are NOT exported (`tethys-repos/tethys-archiver/PROVENANCE.md:233`, and its `OPEN_WORK.md` item "Irregular datasets have no export path, and they are single-copy"), and its Mega S4 copy (2026-08-04) is a copy of those exports. Find where the irregular datasets' copy is (or make the byte-copy) before treating them as backed up.
- [ ] **[infra] MkDocs 2.0 is unlicensed — stack docs stay on mkdocs 1.x for now** (investigated 2026-07-08; LOW urgency): the "Currently unlicensed – unsuitable for production use" banner in docs builds is mkdocs-material *warning about MkDocs 2.0* (released without a license per squidfunk's 2026-02-18 analysis), not about material itself. The stack's builds are clean today: mkdocs 1.6.1 (BSD) + material 9.7.6 (MIT), and material caps `mkdocs<2` so unpinned syncs can't pull 2.0. Longer-term watch: squidfunk is steering users toward **Zensical** (their successor generator). **Assessed 2026-07-08 with Mike — do NOT switch yet**: Zensical is pre-1.0 (v0.0.47 as of 2026-07-05) and, while mkdocs.yml + Python-Markdown extensions (pymdownx incl. snippets) carry over, **MkDocs plugins do not yet — mkdocstrings is unsupported**, which would kill every stack site's API reference pages (3 in envlib, ~10 in cfdb). **Revisit trigger**: Zensical ships mkdocstrings-equivalent API-reference support (their roadmap Phase 2/3 "popular third-party plugins"); then migrate the whole stack in one pass. Until then: mkdocs 1.6.x (BSD) + material 9.x (MIT, caps mkdocs<2) is licensed, working, and safe.
- [ ] **[all repos on the stack] Refresh locks to booklet 0.12.11 and ebooklet 0.11.2** (added 2026-11-11; both on
  PyPI 2026-11-10).
  **Status 2026-11-24:** every lock now has booklet 0.12.11, and ebooklet 0.12.0 or later. The later releases are
  folded into this item.
  - **Refreshed to ebooklet 0.13.0 and cfdb 0.12.0, uncommitted:** cfdb, envlib and `envlib-ingest-base`; their
    tests pass.
  - **Not touched:** `-ecan-env`, `-esa-sst`, `-wrf-3k` and `flow-forecast-app-envlib`. They hold *uncommitted*
    lock refreshes to ebooklet 0.12.0 from another effort, and `-esa-sst` and `-wrf-3k` also hold uncommitted
    `PROVENANCE.md` edits. Mike commits or discards those first, then run in each:
    `uv lock --upgrade-package ebooklet --upgrade-package cfdb --refresh-package ebooklet --refresh-package cfdb`.
    Without `--refresh-package`, uv's cached index silently kept ebooklet 0.12.0 in cfdb's lock on 2026-11-24. Every live remote index is relocated with 144,013 buckets (sweep 2026-11-10), so any dataset
  whose index passes 144,013 keys hangs its next push on booklet 0.12.10. Order by exposure:
  - **esa-sst first:** 16,402 keys of headroom; it runs from its lock.
  - **ECan:** 128k+ of headroom. Its images `pip install` the newest on their next rebuild, so a rebuild suffices.
  - **The rest:** ebooklet, cfdb, envlib, `envlib-ingest-base`, `-ecan-env`, `flow-forecast-app-envlib`.
  - **Done:** `-wrf-3k`. booklet 0.12.11 since `5949b66`; ebooklet 0.11.2 since `eccf098` and `15cdce6` (the floor,
    then the lock). Sky has run on both since 2026-11-12 (`uv sync --locked`), so the forward year was published
    on them.

  `uv lock --upgrade-package booklet --upgrade-package ebooklet` in each. Close-check: every lock shows booklet
  0.12.11 and the esa-sst environment imports it.
- [ ] **[booklet + cfdb + ebooklet + rechunkit] Release benchmarks, standardised** (added 2026-11-10, Mike agreed; the
  rule is in global CLAUDE.md, "Benchmark performance-critical packages, as a release step"). Each package gets a
  `benchmarks/` suite of about a minute over its hot paths:
  - booklet: get/set/iterate, reindex, prune;
  - cfdb: chunk read and write, `iter_chunks`/`groupby`, rechunk, remote reads;
  - ebooklet: push, and `load_items` over a fake S3;
  - rechunkit: plan cost and read amplification.

  One shared helper downloads the previous PyPI release into a scratch tree, alternates the runs and prints ratios
  next to the noise floor. Each release checklist gets the line "benchmark compare: nothing beyond the noise
  floor, or explained". Not a CI gate. Start with booklet: its `benchmarks/bench.py` exists, and the booklet 0.12.11
  scratch scripts (a fixed-length benchmark and the A/B driver) are the helper's first draft. Close-check: each of
  the four has a suite plus the helper, and one release has gone through the compare.
- [ ] **[MEGA] File bug reports** (reproducers ready in `s3func/benchmarks/`): (1) conditional writes (`If-None-Match:*`) accepted but NOT atomic under concurrency — 8 simultaneous creates all succeed (`conditional_write_probe.py`); (2) multi-object-delete POST hangs indefinitely on keys containing `$` (singular DELETE works). Both verified live 2026-07-02/03 on `s3.ca-west-1.s4.mega.io`. Mike's call whether/when to file.

### EDR API (new service)

- [ ] **[new service] Read-only data API speaking OGC API – EDR, on the Docker Swarm cluster** (assessed 2026-10-07; full findings, measurements and sources in `plans/edr_api_assessment.md`). Feasible, and it should be Python on top of envlib/cfdb rather than Rust. Cold reads are bound by B2 round trips, not decoding, and ebooklet format 3 would obsolete a second reader on arrival. EDR 1.2 (published 2026-09-08) maps closely: collection = `dataset_id`, instance = forecast run (decided 2026-11-23; versions are discoverable through `/catalogue` instead), `/locations` = ts_ortho stations, and `/position`/`/area`/`/cube` = grids. Output is CoverageJSON plus CSV and netCDF4. The full envlib metadata rides in a namespaced `envlib` object on each collection, and the standard slots (`extent`, `parameter_names` with `measurementType`, `keywords`, licence link) are derived from it. **Design constraints found (2026-10-07; the 2026-11-23 design in §11 of the doc answers them):** one cache directory per process (even read-only sessions hold an exclusive lock; ran); open handles once (2–3 s per open); a freshness timer for hourly datasets; a per-request chunk budget returning 413 (one cold WRF map is 322 chunks, 13 s). The 413 points the user to the envlib Python package and the dataset's `db_url` for direct chunk-level access (Mike, 2026-10-07); a CDS-style processing service (job queues, large servers doing bulk work for users) is an explicit NON-GOAL (Mike, 2026-10-07): bulk users go through envlib directly. **Deferred:** temporal aggregation and Part 2 notifications. Forecasts are designed (§11) but wait until a forecast dataset is in envlib. **Design decided 2026-11-23** (Mike; the full record is §11 of the doc, and the spike is in `plans/spikes/edr-mongo-store/`). One worker mirrors the B2 catalogue and each dataset's index into MongoDB. Stateless FastAPI processes answer every request from MongoDB, and on a miss they fill an insert-only chunk cache from B2. The stack changes are a read store and the worker's refresh in ebooklet (`ebooklet[mongo]`), a store hook in cfdb and a public catalogue-matching function in envlib. The spike re-measured the cold timings on format 3: a full WRF map now takes about 2 s. **Next step:** the six plans, each in its own item below this heading and each reviewed and closed on its own (split 2026-11-23, Mike: more, smaller plans). The order is "EDR plan 1: the MongoDB read path", then "EDR plan 2: the worker service and MongoDB on the swarm", then "EDR plan 3: the API core and station data". After those, "EDR plan 4: grid queries" and "EDR plan 5: catalogue discovery" can go in either order. "EDR plan 6: going public" comes last. This item closes when all seven have closed, "EDR plan 7: the public docs site" included (Mike, 2026-11-26: "the public docs site is very important").
- [ ] **[new service + infra] EDR plan 6: going public** (added 2026-11-23; §11). Per-IP quotas (hourly and 24-hourly), Traefik's request-rate limit, Cloudflare in front (compression, caching, and an origin locked to Cloudflare's ranges), the allowlist for Mike's servers, and deployment to `api.envlib.xyz`. The caps and quotas are calibrated on the VPSes. **Carried from plan 3** (code review `edr-api-code-3`; its synthesis is in `envlib-api/planning/`):
- **Links:** they follow the request's `Host` header, so set `public_url`. Behind a proxy that is not on loopback, uvicorn ignores `X-Forwarded-Proto` unless `FORWARDED_ALLOW_IPS` names it.
- **Caching:** make the ETag weak, or one per encoding, and answer `If-None-Match`. It does not move when only the catalogue entry changes. Once it answers 304, add `ETag` to the CORS `Access-Control-Expose-Headers` and `If-None-Match` to the preflight's allowed headers (plan 5 left both out, since nothing answered 304). `/catalogue` has no `Cache-Control`; a short `max-age` would suit it, since the mirror changes once per poll.
- **Load:**
  - add a concurrency bound, since one worker runs a 40-thread pool;
  - `/collections` costs about 90 MongoDB operations for 5 collections, uncached, and grids will grow it.
  - `/catalogue` reads the whole mirrored catalogue on every request: 41 KB for today's 18 entries, and about 48 ms and 11 MB at 5,000 entries on loopback (plan review `edr-api-plan-5`). Look again past a few thousand entries.
- **The OpenAPI document:** `/api` lists no query parameters, so `oas31` is not claimed; describe them, then claim it.
- **Browsers:** answer `HEAD`. CORS headers and the `OPTIONS` preflight moved to "EDR plan 5: catalogue discovery" (Mike, 2026-11-25).
- **Strictness:** make `datetime` parsing strict RFC 3339 (Python accepts week dates and the basic format).
- **Risks to weigh:**
  - the API's `insert` on `chunks` can plant bytes under an uncached id;
  - the API fetches from whatever `db_url` the catalogue records;
  - CSV does not neutralise a station name that starts with `=`.
- **Response shape:** no response states a series' time-label anchor (`interval_start`).

**Carried from plan 4** (`envlib-api/planning/edr-api-plan-4.md` and its close-check record):
- **Memory under load** (estimated 2026-11-25, not run):
  - one process runs at most 40 requests at once, which is anyio's default thread pool;
  - each holds its compressed chunks until it answers: about 1/6 of its decoded bytes on the WRF temperature and wind grids, so up to about 17 MB at the 100 MB bytes cap;
  - the values cap is the larger term: about 100 MB of JSON encoding per request at 2 M values.
- **The caps:** kept at their plan 3 defaults (Mike, 2026-11-25: "it's easier to increase it than decrease it"). A full WRF or SST map at one time step answers 413, since it is 322 or 459 chunks (623 MB or 793 MB decoded). Calibrate from real use.
- **A cold `/collections`** took 28 s for 18 collections, reading their attrs and coordinates from B2 one after another. Warm, it took 0.08 s.

**Also publishes** the docs site from "EDR plan 7: the public docs site", which comes before this plan (Mike, 2026-11-25). **This plan updates those docs** for every change it makes that a reader sees: the public URL, `HEAD`, ETags and 304s, the CORS additions for conditional requests, strict RFC 3339 `datetime`, the 429 for quotas, and the calibrated caps and quotas (Mike, 2026-11-26).

**Close-check:** the public endpoint answers through Cloudflare; the origin refuses direct requests; the quotas and the rate limit are verified from outside. **Review:** one arm. **Status:** not started.
- [ ] **[new service] EDR plan 7: the public docs site** (added 2026-11-25, Mike: "one thing we did forget to include in our plans is the public docs site"). It was left out of the six-plan split of 2026-11-23. Its scope is not planned yet.
- **When** (Mike, 2026-11-25):
  - after "EDR plan 4: grid queries" and "EDR plan 5: catalogue discovery", once the API's surface is complete;
  - before "EDR plan 6: going public";
  - published as part of plan 6, so the public endpoint and its docs go live together, and plan 6's review covers the docs.
- **Proposed for the plan, not yet decided:**
  - **Fill in `/api` here.** Describe the query parameters in `/api` (carried in plan 6's item today), so the reference pages can be generated from it and the `oas31` claim restored.
  - **Run the docs examples as tests** against a local API over the hermetic test datasets, as envlib's docs examples are.
  - **Point at the cap and quota values** rather than restating them, because plan 6 calibrates them.
- **Open:** an API section of envlib's existing mkdocs site (the lean, 2026-11-25), or a separate site.

**Status:** not started.
- [ ] **[new service] EDR forecasts (option C)** (added 2026-11-23; designed in §11, "Forecasts: later, but designed for now"). Instances are forecast runs. The instance list covers 30 days, `/instances/latest` redirects to the current run, and a query on the collection returns the best estimate. **Trigger:** the first forecast dataset in envlib.
- [ ] **[new service] EDR grid `/area` and netCDF output** (added 2026-11-23; §11). Grid `/area` is `/cube` plus a polygon mask. netCDF output waits for the item "[cfdb] ts_ortho → netCDF export crashes on the geometry coord". **Trigger:** "EDR plan 4: grid queries" closed, and the export fix for netCDF. Plan 4 closed 2026-11-25 (envlib-api 0.3.0), so only the netCDF fix remains.
- [ ] **[new service] Bound the cube hull's projection on large grids** (added 2026-11-25, code review `edr-api-code-4`; Mike: document it now, build it when needed).
  - **The problem:** `/cube` finds its rectangle by projecting every cell centre to CRS84, before the caps are checked (`envlib-api/envlib_api/api/grid.py`, `Grid.hull`). That costs 15 ms on WRF's 168,210 cells, but about 2 s and 784 MB on a 16-million-cell grid (Sonnet measured it).
  - **The fix:** project the bbox's densified edge into the grid's CRS first, then test only the centres in that index window plus a cell of margin. Test it against the full scan.
  - **Trigger:** the first projected grid of more than about 1 million cells offered to the API.

### booklet

- [ ] **[booklet] 0.12.12: recover a file left mid-reindex, instead of refusing it** (added 2026-11-10; the 0.12.11
  plan's decision B1 put it here). Since 0.12.11 an interrupted reindex leaves the header flag (byte 199) up, and
  the file refuses to open in both modes. That is safe, but the only remedy is to recreate the file, restore a copy,
  or for an ebooklet file fetch it again. A rollback on an in-process failure (truncate to the old EOF, re-initialise
  the old index, relink the live blocks by a sequential scan) would make the instance and file come back exactly.
  Fable prototyped this in plan review `booklet-reindex-plan-1` and both injected failures recovered. A
  `booklet.recover(path)` for a flagged file found on disk (a kill) would need the old EOF recorded in the header.
  A file whose data is fully rewired but whose flag is still up (killed during the last op) is consistent and could
  be cleared after a rescan check (code review `booklet-reindex-code-2`, Sonnet F5). Not blocking: the trigger was
  fixed in 0.12.11.
- [ ] **[booklet] Stale `n_keys` header after a hard crash, then `OverflowError` in `__delitem__`** (added 2026-10-07; code review `ebooklet-wog-code-2`, Fable's out-of-scope note; UNVERIFIED). Fable's simulated hard crash of a flag `'n'` ebooklet session that had synced once left booklet's `n_keys` header stale. The recovery push then died in booklet's `__delitem__` with `OverflowError: can't convert negative int to unsigned`. That was the arm's own crash simulation, untraced. **Wanted:** reproduce with a real kill, then decide whether booklet should recount `n_keys` on open or clamp it in `__delitem__`.
- [ ] **[booklet] `'c'`-create TOCTOU is SILENT CORRUPTION in shipped 0.12.9** (re-characterized 2026-07-22 after the blind Opus-vs-Fable reviewer test proved it; trigger is narrow but the effect is corruption, not the "wasted space" this item first claimed): 0.12.9 fixed the `flag='n'` truncate-before-lock data loss, but left the narrower `'c'` race. `flag='c'` picks the create-vs-open-existing branch from an `fp.exists()` check, so a file created+populated by another process in that window (or two racing `'c'` openers) takes the create path, locks, and — because 0.12.9 truncates only for `'n'` — writes fresh init-bytes + bucket indexes over the HEAD of a populated file WITHOUT truncating, leaving the old data blocks as a stale tail. `keys()`/`items()` walk data blocks to EOF, so the stale tail is **iterated as live**: the Fable reviewer's experiment measured `len()==0` but 20 ghost keys enumerated — a silently self-inconsistent DB (and the `n_keys_crash` rebuild would count the ghosts). **Regression-in-a-corner: 0.12.8's `'w+b'` truncated → clean-but-empty file; 0.12.9 → silent corruption.** Not a release blocker because the trigger (concurrent `'c'`-create on the same new path) is essentially never in the single-producer commons — but severity when it fires is corruption. Fix (Fable's, cleaner than getsize-under-lock): make the create/open decision atomic — `os.open(fp, os.O_CREAT|os.O_EXCL|os.O_RDWR, 0o666)`; on success you provably created it → create path (truncate unconditionally; an acquire-failure can safely `unlink` the file it created); on `FileExistsError` → open-existing path. Its own small diff.

### s3func

- [ ] **[s3func/ebooklet] Make `copy_remote`'s cross-account (indirect) path STREAM instead of buffering** (surfaced 2026-07-23 by the copy_remote review; Mike's request — the durable fix for the memory limitation noted above): `indirect_copy_remote` reads the whole object into `.data` (× ≈20 copy threads) because ebooklet sessions are `stream=False` and s3func's `put_object` has no `content_length` param, so it cannot consume an (unseekable) streaming GET — Gemini confirmed a raw urllib3 stream crashes `put_object`'s `.seek()` Content-Length probe. Fine for small per-key ts_ortho objects; **unsuitable for large/grouped-mode objects** (10–100 MB generation blobs → up to ~2 GB resident). **Fix:** add a `content_length` param to s3func `put_object` (skip the seek probe when given), then have the indirect path do a streaming GET (a stream=True read session) → streaming PUT with the source's known `content_length`. **s3func change → its own review + release + downstream lock refresh** (booklet→s3func→ebooklet→cfdb→envlib).
- [ ] **[s3func] Remove the B2-native module (the promised 1.0 removal; Mike's direction 2026-07-15 — "excessive to manage both APIs")**: `B2Session`/`B2Lock` already carry DeprecationWarnings and have ZERO production usage in the stack (grep-verified: ebooklet/cfdb/envlib are pure S3-compat; only two ebooklet test files import B2Session). The 0.10.1 round demonstrated the dual-surface cost concretely (every transport fix ×2; the BytesIO wrap needed a b2-specific retry-rewind companion fix). Removal round: delete `b2.py`'s native session + `B2Lock` + the `locking.py` registry entry + `__init__` exports + the native lock tests; clean the two ebooklet test imports; changelog + README. Extra payoff identified 2026-07-16: `test_B2Lock_concurrency` is the flaky CI element (1-of-4 workers exceeded its 120s native-lock acquire timeout in the 2026-07-15 matrix run — an intra-test flake of the deprecated path, NOT a cross-job race) — removal deletes the flake with the module. Until then the module is frozen-deprecated (the 0.9.4 rewind fix keeps it correct). Rides whenever — its own small diff, NOT part of the 0.9.4/0.10.1 release train.
- [ ] **[s3func] Drop the orjson dependency for stdlib json** (ruled by Mike 2026-07-12 during the Phase-1 serialization decision; NOT part of the 0.9.3 round): all s3func orjson uses are small decode-only response/error parsing (b2 auth, error bodies) where performance is irrelevant — stdlib json removes a compiled dependency. Some future s3func round.

### ebooklet

- [ ] **[ebooklet] A benchmark suite for ebooklet's core paths** (added 2026-11-24, Mike). The global release rule
  wants each performance-critical package to keep a `benchmarks/` suite of about a minute, and to A/B it against
  the previous PyPI release before each release. ebooklet has only `benchmarks/bench_mongo.py`, which covers
  the MongoDB read path and nothing else. The suite should cover:
  - opening a session (the HEAD and the index download);
  - warm reads per key and batched (`get_items` / `load_items`);
  - cold reads, grouped and per-key;
  - push (pack, upload, commit, GC) and pull/`changes()`.
  Build it on the in-memory fake S3, in booklet's `bench.py` style. Every run should include a booklet baseline
  measured in the same run.
  **Lead for the first measurement (a profile, 2026-11-24):** ebooklet's warm per-key read is slow. On 10,000
  shuffled warm reads (grouped storage, 200 B values), the rates were:
  - booklet opened `'r'`: 424K keys/s;
  - the same `get` on ebooklet's own local file: 157K keys/s;
  - ebooklet `eb[key]`: 48K keys/s;
  - ebooklet `get_items` (batched): 51K keys/s.

  There are two causes:
  - ebooklet opens its local file and its remote-index file writable in every session mode, including
    `'r'`, so booklet's mmap read path is never used (`ebooklet/utils.py:695–699` says so).
  - Every key costs three booklet lookups: the remote-index entry, the local timestamp (the freshness
    check) and the value. That is about 10 file reads and 9 seeks per key. `get_items` does the same
    lookups key by key, so batching it does not help.

  The levers to measure are an mmap read path for read-only sessions, and skipping the per-key freshness
  check when the session has just synced. For comparison, `ebooklet.mongo`'s batched store read reached 180K
  keys/s in the same benchmark. The script is `benchmarks/bench_mongo.py` and the results are in
  `planning/mongo-read-path-evidence/`.
  **Close-check:** the suite runs in about a minute, and an A/B against 0.12.0 is recorded, with each ratio next
  to the run-to-run spread.
- [ ] **[ebooklet + cfdb] Small pre-existing defects found while building "EDR plan 1: the MongoDB read path"**
  (added 2026-11-23; none affects that plan). The first three came from the plan review `edr-mongo-plan-1`, and
  the last from implementation:
  - `bool(S3SessionReader)` raises `AttributeError`, because `__bool__` returns `self.read_access`, which is
    never defined (`ebooklet/remote.py`).
  - cfdb `Dataset.prune()` is not guarded by `writable`, so on a read-only store it fails with an
    `AttributeError` instead of a clear error.
  - ebooklet's floors in `requirements.txt` and `conda/meta.yaml` have drifted from `pyproject.toml`. The conda
    recipes are unmaintained, so only `requirements.txt` matters.
  - ebooklet's docs do not build with current mkdocstrings-python. `mkdocs.yml` uses the removed `import:`
    option, and there is a `Highlight.__init__` error with current mkdocs-material; the dependencies are
    unpinned. Pin them, or update the config, before the next docs deploy.
  **Close-check:** each is fixed or ruled not worth fixing.
- [ ] **[ebooklet] A non-replacement push with upload failures commits anyway** (added 2026-11-11, plan review
      `wrf3k-append-plan-1`, Fable F1; reproduced there by injecting one failed group PUT). `push` logs "Please run
      this again" (`ebooklet/utils.py:1694-1700`) and then commits the groups that did upload; only a replacement
      push refuses (`:1750`). Readers of a public dataset then see missing labels or values until a retry. Callers
      work around it by retrying at once (the wrf-3k README, "If a publish fails part-way"). **Wanted:** decide
      whether a push with failures should commit at all, or commit only a state that keeps every reader consistent.
- [ ] **[ebooklet] fsck does not flag a group object smaller than its live bytes** (added 2026-11-11, plan review
      `wrf3k-append-plan-1`, Sonnet F1; read at `ebooklet/fsck.py:157-170`). A missing object is reported
      (`claimed_but_missing`), but a short or truncated one only feeds `dead_fraction` when it is larger
      (`if size and live < size`). **Wanted:** report `size < live` as damage. It is a byte-free structural check.
- [ ] **[ebooklet] Rewritten groups grow past `group_bytes`** (added 2026-11-11, plan review `wrf3k-append-plan-1`,
      Fable F5; an estimate). A rewritten key keeps its group, so an append that rewrites a partly filled band grows
      that band's groups well past the target (estimated ~50–110 MiB for 32 MiB groups on the WRF 3 km datasets).
      That affects read and upload size only. **Wanted (only if it matters):** move rewritten keys whose group
      would exceed the target into a new group.

- [ ] **[ebooklet] Make `EVariableLengthValue.close()` match booklet's on a failed sync** (added 2026-11-10; Mike
  agreed with the direction and deferred it; raised by code review `booklet-reindex-code-2`, Sonnet). **Released
  as-is in ebooklet 0.11.2 (2026-11-10)**, so this now changes released behaviour: `close()` runs the finalizer even
  when `sync()` raises (`try: self.sync() finally: self._finalizer()`). That releases the S3 lock at once, but the
  `weakref.finalize` is one-shot. After a transient failure (a full disk) a retried `close()` can no longer reach
  the local file, so unpushed local writes and journal state can be lost. booklet 0.12.11 chose the opposite on
  purpose: a failed sync keeps the instance open with its buffers, so a retry loses nothing.
  - **Direction (agreed):** `close()` goes back to `sync(); finalizer()`, so a failed sync keeps everything open for
    a retry. The S3 lock is then released by the retry, at garbage collection or at process exit. Keep the
    finalizer's other change: each teardown step in `try/finally`, so a teardown that does run always reaches
    `lock.release()`, a `KeyboardInterrupt` in `journal.persist` included.
  - **Why little is given up:** the orphaned-lock incident (ECan, 2026-10-13) came from a writer that DIED, which
    no `try/finally` can cover.
  - **Close-check:** `ebooklet/tests/test_finalizer_release.py` `test_close_runs_the_finalizer_when_sync_raises`
    inverted (the finalizer must NOT run on a failed sync, and a second `close()` must complete); re-mutate.
- [ ] **[ebooklet/cfdb] Size the remote index's hash-bucket count to the dataset — DEFERRED by Mike (D4, 2026-10-08).** Split out of the index-prune item (Done, ebooklet 0.11.1). cfdb's default of 144,013 buckets gives a ~0.86 MB floor even for 7 keys, and every hourly ECan commit moves it three times. Fable measured 908 KB → 69 KB at `n_buckets=4096` (booklet re-indexes as keys grow). The sidecar is created once, at a dataset's first publish, so that is the moment to set it. The `OverflowError` that fired past ~150k keys at `n_buckets=12007` was the second-reindex bug, fixed in booklet 0.12.11 (Done, 2026-11-11), so a lower bucket count is now safe to try. Note: 144,013 → 1,728,017 buckets grows a published index by 10.4 MB of bucket table (precipitation 8.7 → 20.7 MB), which this item would also address.
- [ ] **[ebooklet] Coalesce grouped ranged reads** (added 2026-10-07, from the write-order-groups plan; out of its scope). `get_remote_group_values` (`ebooklet/utils.py:835-897`) fetches one byte range per group, from the first wanted member to the last, so a sparse read downloads everything packed between them. cfdb measured 24× over-read for a single-point series on esa-sst's 134 MB groups (`cfdb/benchmarks/RESULTS.md`, "Remote (EDataset) reads vs chunk size"). This matters more once groups are 32 MB and in write order (a 2×2-tile read of one band spans about one row of tiles, ~10 MB). **Wanted:** split the range wherever the gap between wanted members exceeds a threshold, giving several ranged GETs per group. Mike recalls looking into this before and finding it harder than expected; there is no record of that attempt in `ebooklet/planning/`.
- [ ] **[ebooklet] `del k; db[k] = v; del k` loses the delete; hide deletes through the journal instead** (added 2026-10-07, code review `ebooklet-wog-code-1` F3 and S8; pre-existing on 0.10.5, both modes; reproduced by `~/git/ebooklet/planning/write-order-groups-evidence/f3.py`). The re-set cancels the journaled delete, and the second `del` finds no sidecar entry, so it only discards the write. The push is a no-op, the remote keeps serving `k`, and a later unrelated commit drops it silently (per-key mode leaves `d/k` as an orphan). If an index re-fetch comes first, `k` is resurrected instead. `clear()` after a del + re-set takes the same branch (read, not run). **Design candidate (Fable S8, not tested):** stop editing the sidecar in `__delitem__` and hide deleted keys through `journal.deletes`. That removes both delete replays (open and pull) and `discard()`'s forced re-pull, and fixes this.
- [ ] **[ebooklet] Compaction of dead bytes in grouped remotes** (added 2026-10-07, from the write-order-groups plan). Lazy deletes remove only the index entry, so a deleted value's bytes stay in its group object until that group is repacked for another reason; they stay publicly downloadable until then. fsck reports each group's dead fraction from 0.11. **Wanted (only if a workload needs it):** a pass that repacks groups above a dead-fraction threshold. envlib's append-mostly datasets do not need it.
- [ ] **[ebooklet] `moto[s3]` is a declared dev dependency but no test uses it, and server mode needs `moto[server]`** (added 2026-09-25, round `wrf3k-ingest-plan-1`, Sonnet). The suite runs on the hand-rolled `tests/fake_s3.py`. Also, moto drops HTTP metadata headers containing underscores (Fable had to patch s3func's transport to run a moto round trip). Either drop the dependency or build a moto-backed tier.
- [ ] **[ebooklet] WRITERS read through the public `db_url` (CDN) whenever one is set** — found
  2026-09-08 while chasing the MetService ghost (`remote.py create_s3_read_session` prefers
  `db_url` even for a credentialed session). A writer's read-modify-write then depends on the CDN
  being honest at that moment; Mike has seen Cloudflare serve stale objects despite a bypass rule.
  Not the cause of the 2026-09-07 incident (all objects `cf-cache-status: DYNAMIC`), but a latent
  hazard: credentialed sessions should read via the S3 API and leave `db_url` to credential-less
  readers.
- [ ] **[ebooklet] Readers' `keys()`/`in`/`len` never heal after a remote deletion** — values heal
  per key via `_resolve_missing`, the sidecar entries stay for the life of the local file and
  disagree with `items()` (verified 2026-09-08, both storage modes). Documented in 0.10.5's
  `docs/ops.md`; deliberately not fixed there (a reader must not unlink a cache on an unconfirmed
  404). A cheap improvement is a warning on a `'r'` open with a non-empty sidecar against an
  uninitialised remote.
- [ ] **[ebooklet] Batch the three serial `delete_object` loops, add delete-pass progress, and repair a vacuous GC test** (spun off 2026-08-08 from the s3func 0.9.6 round; MEDIUM, and the test repair is the urgent part). ⚠️ **The line numbers below predate ebooklet 0.11.0.** On 0.11.1 the singular `delete_object` calls are at `utils.py:1907`, `:1916` and `:1922` and `fsck.py:233` (grep, 2026-10-09; not matched one by one to the three loops named below). The s3func fix does not touch these — each is a Python loop calling `delete_object` one key at a time, i.e. 2 requests per key, serially: `utils.py:1645-1648` (replacement sweep, unbounded, and it already holds a full listing), `utils.py:1652-1663` (phase-D generational GC, bounded by `num_groups`), `fsck.py:179-188` (orphan sweep). The easy one is the replacement sweep: `remote_session.delete_objects(sweep_keys)` inside the existing `try` at 1637 — state the trade-off, that today one child's failure skips only that child whereas batched, a resolution failure aborts the sweep. The GC loop needs a new `except urllib3.exceptions.HTTPError` (it has none) and loses per-gid attribution in its warning; the fsck sweep must keep per-key `report.swept` granularity. Also: the push delete pass at `utils.py:1580-1581` emits **nothing** — no progress at all for what was a 17-minute step — so wire in `push_logger` / the `_PushProgress` convention (`utils.py:1087-1136`, user-facing contract in `docs/ops.md:48-80`). ✅ **The test repair is DONE (2026-10-07, staged with the write-order-groups round):** `test_gc_failure_is_invisible_orphan` now makes the plural `delete_objects` fail and asserts that the repacked group's OLD generation survives as an orphan; mutation-checked (a GC that raises turns it red). The batching and delete-pass progress remain. Original note: **Do the test repair FIRST, and do not trust the current one:** `tests/test_generational.py:104-127` patches `_write_session.delete_object` (singular) but the GC path calls `RemoteWriter.delete_object` → `_write_session.delete_objects` (**plural**), so the patch never fires, the GC it means to fail actually succeeds, and the assertion `before & set(_group_objects(store))` is non-empty regardless because k2's group is untouched by that push. Verified independently three ways in the 0.9.6 round (my read, plus both review arms — Fable instrumented it: `patched singular fired: 0 | plural fired: 1 | GC actually ran: True | assertion passes: True`). Fix: patch the plural method and assert `before - after == set()`. Until then the downstream regression gate has a hole exactly where a GC-phase raise would land. Minor companion: the docstring at `remote.py:377-380` justifies its return-not-raise contract by naming `upload_group` as the caller, but `upload_group` (`utils.py:691-742`) contains no delete call at all — the contract is still worth keeping, its stated reason is stale.
- [ ] **[ebooklet] Verify-BEFORE-commit inside push — full *prevention* of published over-claims** (deferred from the envlib publish-verify fix; Mike's call 2026-07-27 to defer): envlib's `verify_objects` runs AFTER `push()` commits the db object, so it *detects* an over-claim loudly but can't un-commit the already-live generation on a *re-publish* (the entry pins the db_key the push just overwrote). Full prevention = verify this-push's uploaded objects BEFORE writing the db object, inside ebooklet's push (confirm the uploads landed; refuse to commit otherwise). Heavier (ebooklet change + release + downstream lock refresh) AND its prime trigger (booklet 0.12.8 create-path race) is already fixed in 0.12.9 — so deferred; pull it out only if a related over-claim recurs.
- [ ] **[ebooklet] `copy_remote` aborts the whole dataset on ANY single child-copy failure (no per-child retry)** (surfaced 2026-07-23 during the ECan migration; MEDIUM): streamflow's indirect (cross-account) copy failed after 1073 children on a transient blip, while gage_height (1530 objects) + precipitation (3884) — both LARGER, copied right after — succeeded, so it was NOT volume/throttling. The indirect path submits each child once; a single non-2xx (after s3func's 3 per-request attempts) lands in `failures`, and `copy_remote` then SKIPS the db-object write → a torn state (orphans, no db object). Recoverable by resume (re-run skips already-copied children, then writes the db object — verified), but fragile for large cross-account copies. Fix: per-child retry/backoff in the indirect loop and/or a bounded retry of the `failures` set before aborting. Also: `migrate.py` was discarding `copy_remote`'s returned `failures` dict — patched 2026-07-23 to print the per-object reasons. Ties to the streaming-copy item above.
- [ ] **[ebooklet] `copy_remote` same-creds routing ignores `endpoint_url`** (pre-existing, surfaced 2026-07-23 by the copy_remote review; LOW — fails loud): the same-account server-side-copy check (`remote.py:486`) compares only access-key id + secret, not `endpoint_url`. Identical keys across different regional endpoints would send the server-side copy PUT to the source session's endpoint with the dest bucket name → a 301 (loud, lands in `failures`). Add `endpoint_url` to the equality check.
- [ ] **[ebooklet] `copy_remote` TOCTOU between child-enumeration and the last db-object copy** (pre-existing, surfaced 2026-07-23 by the copy_remote review; LOW for supervised one-time copies): children are enumerated from one db-object GET (`remote.py:459-472`) but the live latest db object is copied LAST; a concurrent source push between the two yields a target db referencing never-copied children, and the advertised "rerun copy_remote" remedy is then blocked by the target-exists check. Harmless for a supervised migration with no concurrent writer; real for the general primitive. Applies to both copy strategies.
- [ ] **[ebooklet] Remote METADATA deletion doesn't propagate to warm caches** (Claude reviewer find, 2026-07-20 delete-reconcile round — the metadata twin of the fixed key defect): the 0.10.2 reconciliation scan never sees reserved keys (booklet iterators skip them), and `refresh_local_metadata` early-returns when a fetched payload carries no meta section (`utils.py:447-448`) — so a remote whose metadata was removed (e.g. a replacement push, which embeds no section) leaves warm caches serving the old metadata forever; the only nulling path is `_resolve_missing`'s fetch-404 branch. Candidate fix: on a fresh ingest whose payload has no meta section (and no `meta_pending`), null the local metadata. Small, its own round.
- [ ] **[ebooklet] Freshness-gate clock-skew hole** (Claude reviewer find, 2026-07-20, pre-existing): every pull/open sync sits behind `remote_session.timestamp > local_file._file_timestamp` (`utils.py:323`) — a foreign push whose commit ts (pusher's clock) is ≤ the local stamp is never fetched, so never seen and (now) never reconciled; worse, a warm writer in that state pushes a sidecar index still referencing the foreign push's GC'd generations (stale-writer-push corruption). Cross-machine sequential writers with skewed clocks only — the single-producer commons is immune. Related nit: the open path never stamps `_file_timestamp` (only push/pull do), so open-path-only readers re-download the index on every open — harmless (and it's what lets pre-0.10.2 reader caches heal on first open), but a deliberate design pass on "wall-clock as truth" should cover both.
- [ ] **[ebooklet] Interactive read-consumer fail-fast on a held cache lock** (spun off from the booklet 0.12.9 fix, 2026-07-21): booklet 0.12.9 makes a held-lock open *diagnosable* (warns then blocks) but end-to-end fail-fast for interactive re-opens needs ebooklet to pass a finite `timeout=` when opening the local cache and the `.remote_index` sidecar (`ebooklet/utils.py:347,561`, both `'w'`), and/or open read-only caches shared where materialization isn't needed. Turns Mike's Spyder `refs[0].open()` from "warns then blocks until you close the stale handle" into "raises `LockTimeoutError` immediately." Needs ebooklet's booklet pin → `>=0.12.9`. Its own small round.
- [ ] **[ebooklet] Build out the mkdocs site** (Mike, 2026-07-13, explicitly NOT now): ebooklet has outgrown its two-page site (About + API reference) — 0.10.0 adds the ops guide, offline mode, the typed taxonomy, format 2, fsck. Some post-0.10.0 round: proper guide pages (concepts/format/ops), mirroring the envlib docs structure. The planning/assessment docs deliberately live OUTSIDE the mkdocs source (`planning/` at the repo root, moved there 2026-07-13) so they never publish.
- [ ] **[ebooklet+s3func] CDN-safe Cache-Control headers on push** (Mike's question 2026-07-16, from the tethys stale-Cloudflare-cache experience): TODAY the commons is verifiably uncached (`cf-cache-status: DYNAMIC` — extensionless keys don't match Cloudflare's default cache list; every read hits B2, and B2→CF egress is free) so there is NO staleness issue. But if CF caching is ever enabled (latency + B2 Class-B transaction savings on hot datasets), the ONE mutable object per database (the db object) becomes a staleness surface: a stale cached manifest pointing at GC'd generations makes fresh readers raise RemoteIntegrityError until the edge TTL expires (loud, not silent — but broken). Pre-emptive fix: upload with `Cache-Control: no-cache` (or short max-age) on db objects and `public, max-age=31536000, immutable` on generation objects (immutable + uniquely-named = perfectly cacheable forever) — small s3func change (pass Cache-Control through put_object/put_db_object) + ebooklet setting the two policies. Verify B2's S3-compat stores/serves the header. **IMPORTANT caution from Mike's tethys experience (2026-07-16): toggling caching off in Cloudflare did NOT always stop stale serving** (candidate culprits: already-cached entries persisting until explicit purge, tiered/upper-tier caches, CF ranged-request handling against cached bodies) — so do NOT trust CF configuration alone; the design must include the config-independent hardening: **ebooklet's integrity re-pull (`_resolve_missing`/`_pull_remote_index`) appends a unique cache-busting query param when re-fetching the db object after a confirmed 404-claim** (a new URL defeats every cache layer regardless of settings), and the round's verification must empirically reproduce an update-after-cache scenario through the real domain chain (push → read via b2.envlib.xyz → push update → immediate fresh-reader read), not just inspect headers. NOT part of the 0.10.1 train.

### cfdb

- [ ] **[cfdb] A `flag='n'` replacement over an existing remote may read the old remote's chunks and drop
  attrs keys** (added 2026-11-24; seen by both arms of code review `edr-mongo-code-1`, outside that
  change; not yet reproduced by me). Fable saw `cfdb.open_edataset(flag='n')` over an existing remote read
  an old chunk during `v[:] = data` (`ValueError: cannot reshape array of size 144 into shape (12,3,2)` at
  `support_classes.py:1618`). Sonnet saw a `flag='n'` replacement lose every attrs key from the remote
  (`__.attrs`, `_t.attrs`, …), and guessed that `attrs_finalizer` skips writing attrs equal to the old
  remote's. **If the attrs loss is real, a replacement silently drops metadata.** **Close-check:**
  reproduce both against an unmodified HEAD; fix, or rule them expected.
- [ ] **[cfdb] A `.loc` slice on a float coordinate needs exact labels, and a non-label bound raises a bare
      `IndexError`** (added 2026-11-14, found testing envlib's docs examples). `loc_index_numeric`
      (`cfdb/indexers.py:31`) finds a float bound with `np.isclose(coord_data, key)` and takes its first hit, so
      `select_loc({'latitude': slice(-44, -43)})` on the ESA SST grid (cell centres at -43.975, …) fails with
      `IndexError: index 0 is out of bounds`. Datetime and integer coordinates use `searchsorted`, which treats a
      bound as a range limit. The cfdb docs test (2026-11-14) found a second inconsistency: a float slice's stop is
      EXCLUSIVE (`loc[2.0:5.0]` gives 2, 3, 4), while integer and datetime stops are inclusive (`searchsorted(side=
      'right')`, `indexers.py:34`), as is `Coordinate.truncate`. So `combine(sel={'latitude': slice(35.0, 72.0)})`
      silently drops the 72.0 row. The docs now state both rules (cfdb `docs/guide/indexing.md`, the "Float
      coordinates" warning). **Wanted:** `searchsorted` semantics for float slices too (a range selection with an
      inclusive stop, as for the other types), or at least an error naming the coordinate and its nearest labels.
      Then drop the docs warning.
- [ ] **[cfdb] Attribute writes on a closed Dataset are silently lost** (added 2026-11-14, cfdb docs test). After a
      `with cfdb.open_dataset(...) as ds:` block, `ds.attrs['x'] = 1` neither raises nor persists, whereas a data
      read on the closed handle raises `ValueError: seek of closed file`. **Wanted:** attribute writes (and reads)
      on a closed dataset raise.
- [ ] **[cfdb] A geometry dtype without `precision` fails with an opaque `int(None)` TypeError** (added
      2026-11-14, cfdb docs test). `ds.create.coord.generic(..., dtype='point')` reaches `Geometry.__init__`'s
      `int(precision)` (`cfdb/dtypes.py:168`) and raises `TypeError: int() argument must be ... not 'NoneType'`.
      Two docs examples did exactly that (fixed to `cfdb.dtypes.dtype('point', precision=6)`). **Wanted:** a
      clear error ("geometry dtypes need precision=…"), or a documented default precision.
- [ ] **[cfdb] `combine(overlap='first')` drops data and `overlap='error'` raises, for disjoint inputs that share an
      output chunk** (added 2026-11-14, found by the docs tests; reproduced). The overlap test is per chunk, not per
      value: `out_var.get_chunk(out_sel, missing_none=True) is not None` (`cfdb/combine.py:373-384`;
      `_write_noncontiguous`, L401-408, has the same shape). Two NZ grids with disjoint latitudes (-41..-34 and
      -48..-41.5, 0.5°, chunks of 15 rows): `overlap='first'` left 14 of 29 latitude rows all-NaN, and
      `overlap='error'` raised `Overlap detected for variable temperature at (slice(0, 14, None), …)`.
      `overlap='last'` is correct. A 1-D case with the second input appended after the first did not reproduce it.
      The docs skip those two lines with this reason and show a visible "Known issue" warning (cfdb
      `docs/guide/combining-datasets.md`, manifest `cfdb/tests/docs_skips.txt`). **Wanted:** a per-value overlap
      test (stored and not fill), then remove the skip and the warning.
- [ ] **[cfdb] `combine` leaves its output dataset open when it raises** (added 2026-11-14, docs tests;
      reproduced). After the `overlap='error'` failure above, `out.cfdb` was still open, so the next open of that
      file waits forever on the lock. **Wanted:** close the output (or delete the partial file) on any exception.
- [ ] **[cfdb] `create.coord.generic(..., axis='z')` raises `AttributeError: 'DataVariable' object has no attribute
      'axis'` once the dataset holds a data variable** (added 2026-11-14, docs tests; reproduced with a dataset
      holding `lat` and data variable `t`). The duplicate-axis check (`cfdb/creation.py:206-211`) loops over every
      variable, data variables included. The `creator.md` example passes only because its hidden setup opens a
      dataset with coordinates alone. **Wanted:** check coordinates only; then let that example's setup use a
      dataset with data variables.
- [ ] **[cfdb] a slice with numpy-integer bounds is silently ignored and returns the whole axis** (found 2026-11-10 in
      `wrf-model-eval`, cfdb 0.11.0). `v[np.int64(5000):np.int64(5120), :]` on an `(8760, 1300)` variable returns shape
      `(8760, 1300)`; the same slice with Python ints returns `(120, 1300)`. Indices from `np.flatnonzero`,
      `np.searchsorted` or `argmax` are numpy integers, so this is easy to hit, and nothing warns. Probable cause, from
      a grep and not a full reading: `cfdb/indexers.py` tests slice bounds with `isinstance(start, int)` (lines 180,
      184, 236, 242), which a numpy integer fails. A fix would accept `numbers.Integral` (or call
      `operator.index`). **Close-check:** a test that slices with `np.int64`, `np.int32` and Python ints and requires
      identical shapes and values, which fails before the fix. Caller-side workaround meanwhile: `int(...)` the bounds.
- [ ] **[cfdb] `truncate` leaves dead rows that read back as values after a gapped re-extend** (added 2026-11-11,
      plan review `wrf3k-append-plan-1`, both arms ran it). `Coordinate.truncate` keeps the truncated rows in
      partial boundary chunks as "dead data" (`support_classes.py:1275`). If the axis is later extended over those
      rows without writing every label, the unwritten slots read as the old values instead of as missing, and a NaN
      scan cannot see it. **Wanted:** blank (fill) the truncated rows of the boundary chunks in `truncate`, or make
      a re-extend treat them as missing.

- [ ] **[cfdb] A packed `DataType` without `fillvalue` is silently stored as plain float32** (added 2026-10-21 from wrf-model-eval plan review `c1-store-phase-a-plan-1`; reproduced on cfdb 0.11.0). `create.data_var.generic(..., dtype=cfdb.dtypes.dtype(name='float32', precision=2, dtype_encoded='uint16', offset=-1))` keeps `precision` but drops `dtype_encoded` and `offset`, with no warning; reopened, the variable reports `dtype_encoded None`. With `fillvalue=0` it packs. `cfdb.dtypes.dtype`'s docstring (`dtypes.py:583`) says offset and fillvalue "must also be passed", and the code honours that literally. The same loss happens through `cfdb.dtypes.Float(...)` and a `dtype=` override of a named template. **Wanted:** refuse (or warn on) an encoded dtype whose fill value is missing, instead of quietly dropping the encoding. Workaround in use: `wrf-model-eval/lab/2026-10_c1_campaign_store/phase_a.py` passes `fillvalue=0` and asserts the encoding after reopening.
- [ ] **[cfdb] The trim-mode WKT writer rounds differently from the rest of the stack's "5 decimal places" — an upstream decision, not needed for the `canonical_station_point` fix (envlib 0.1.4, in `OPEN_WORK_DONE.md`)** (moved from Verification debts 2026-10-09: it is a pending decision, not unproven work; surfaced 2026-08-25, round `envlib-stationid-1`; LOW). `Geometry.encode` uses `shapely.to_wkt(..., rounding_precision=N)` with shapely's `trim=True` default. The reviewer's alternative: encode with `trim=False` then strip trailing zeros string-wise — byte-identical for values already exactly N-dp, but correct at the rounding boundary, fixing the writer for *every* cfdb consumer without churning stored WKT. Producer-side canonicalisation was taken instead because changing the encoder alters the stored representation for every geometry any cfdb user re-encodes. Note a **third** rounding semantic is also live in the tree: `envlib-ingest-ecan-env/qa/source.py` compares coordinates with Python's banker's-rounding `round(x, 5)`. So "5 decimal places" currently means three different things depending on the code path.
- [ ] **[cfdb] `Attributes.__iter__` returns `dict_keys`, not an iterator** (added 2026-10-08, found writing `compare_datasets`; ran). `set(ds.attrs)`, `iter(ds.attrs)` and `for k in ds.attrs` raise `TypeError: iter() returned non-iterator of type 'dict_keys'` (`cfdb/support_classes.py:530-531`). `dict(ds.attrs)` works, because it goes through `keys()`. The fix is `return iter(self.keys())`.
- [ ] **[cfdb] `create.coord.like()` without data rejects a datetime coordinate** (added 2026-10-07, found by the `group_bytes` benchmark; cfdb 0.10.0 and the 0.11 tree). `like('time', src['time'])` passes the source's int `step` (60) to `generic`. Without data, `utils.parse_coord_inputs` accepts any step for an integer dtype, but for every other dtype only a bool or an `np.floating`: a plain Python `int` or `float` raises "step must be a bool, int, or float", although both are documented as valid (`Coordinate.step` returns plain Python numbers, so `like()` without data fails for any non-integer coordinate with a step). With `copy_data=True` the data path is taken and it works. Workaround used: create the coordinate with its first values through `generic(..., data, step=...)`.
- [ ] **[cfdb] `cfdb_summary_usage.md`'s chunk-sizing section is stale against the cfdb reference skill** (added 2026-10-06, same round). The repo copy still says "pre-compressed ~2 MB (and always > 1 MB)"; `~/.claude/skills/cfdb/SKILL.md` says ~10⁵–5·10⁵ elements per chunk and that the old > 1 MB rule was wrong (measured 2026-09-23, `benchmarks/RESULTS.md`). The two copies are meant to stay identical, and a review arm quoted the stale one. Sync the section (and diff the rest of the two files).
- [ ] **[cfdb] `shuffle+lz4-1` (`lz4_shuffle`) was measured after review round `cfdb-compression-1`, so no arm has checked it** (added 2026-09-23; updated 2026-09-24). Now measured on all three benchmark datasets: d01 0.83x zstd-1, ECan streamflow 0.76x, and the raw-float32 gabriele ERA5 set 0.95x (run 2026-09-24, `benchmarks/compression/results/2026-09-22_gabriele_3km_era5/codec_bench_lz4.txt`). Mike, 2026-09-24: `lz4_shuffle` is still a good contender, but `zstd_shuffle` stays the default for now; that review is the input for revisiting it. Close-check: include it in the next review of `benchmarks/compression/`.
- [ ] **[cfdb] Writing to a multi-dimensional variable fails once a NON-first coordinate has a nonzero origin** (added 2026-09-23, pre-existing in 0.9.7). E.g. dims `('time', 'y')` after `ds['y'].prepend(...)`: `v[:] = data` raises `cannot reshape array of size 240 into shape (12,25)` — the write path adds the origin shift to the shape of a non-first dim. Loud, not silent; reads are correct; prepending the FIRST dim works. Repro and matrix in cfdb `benchmarks/results/review-cfdb-shuffle-plan-1.md` (found while building fixtures); `cfdb/tests/fixtures/make_fixtures.py` orders its writes around it.
- [ ] **[cfdb or envlib-ingest-base] Don't store chunks that are entirely missing values** (added 2026-09-23). In the public ECan streamflow dataset 271 of 1 072 stored chunks (25 %) hold only fill values (22 bytes each), most likely from writing whole station rows, including years before a station reported. On an ungrouped remote each costs a full GET: a quarter of the requests in a full read. Fix in ingest (skip all-missing chunks) or in cfdb `set()` (don't store an all-fill chunk, and DELETE an existing one rather than skip, or stale data survives). Needs a design decision. Evidence: cfdb `benchmarks/RESULTS.md`, "Station (ts_ortho) data".
- [ ] **[cfdb] `DataVariableView.set()` pays ~20–40 µs per call before doing any work** (added 2026-09-23): `get_coord_origins` tests `hasattr(self, 'coords')`, and `coords` is a property that builds a coordinate object per dim (8 objects per `set()`). It doubles small-chunk write cost in the one-`set()`-per-chunk loop the cfdb skill recommends. Evidence: `benchmarks/results/review-cfdb-profile-1.md`, finding 3.
- [ ] **[cfdb] Reads decode every chunk into freshly allocated buffers** (added 2026-09-23), which page-fault at multi-MB chunks under the default glibc allocator and cause most of the large-chunk read penalty. With a reused buffer a decode-like step stayed flat per element up to 2 M elements (fresh buffers: 2.3× slower); glibc allocator settings cut stored-shape reads 15–25 % here, leaving a ~1.2–1.5× penalty, mostly decompression. Evidence: cfdb `benchmarks/RESULTS.md`, "Per-chunk costs vs chunk size, real data", and `benchmarks/results/review-cfdb-profile-1.md`, finding 5.
- [ ] **[cfdb] Lead, not a commitment: per-variable zstd dictionaries for sub-1 KB chunks** (added 2026-09-23). One review arm measured +22 % ratio and +23 % compression speed on RH at 960 B blocks (not reproduced). Cost: chunks stop being self-contained. `benchmarks/compression/results/review-cfdb-compression-1.md`.
- [ ] **[cfdb] `Coordinate.truncate`'s docstring wrongly claims `ds.prune()` reclaims boundary-chunk dead space** (surfaced 2026-08-07, round `ecan-alpha2-1`; LOW — docs only, but actively misleading about an irreversible operation). Truncating leaves the retained *partial* boundary chunk holding all the pre-cut cells (~9,400 per station at ECan precip scale). They are unreachable through any read, because the coordinate's `origin` moves past them — but `prune()` cannot reclaim them: prune is storage-level compaction of orphaned *blocks*, while these cells live inside a **live key's value**. Reclaiming them would mean rewriting the boundary chunk. The docstring should say the dead cells persist in the retained chunk, not that prune removes them; anyone needing "the bad bytes are actually gone" has to rewrite that chunk deliberately. *(Present in both 0.9.4 and 0.9.5 — `truncate` is byte-identical across them.)*
- [ ] **[cfdb] Datetime coord dtypes: cadence-appropriate units + int packing** (Mike, 2026-07-17, out of the ingest-toolkit unit discussion; NOTE the separate encode() fabrication BLOCKER found 2026-07-18 is already FIXED in the 0.9.4 tree — see the ECan entry round 4): cfdb's int-packing (`precision`/`min_value`/`max_value` → width) exists only for floats — datetime coords store plain int64 regardless of unit. Two parts: (a) **time coords should carry the dataset's true cadence unit** — DONE toolkit-side 2026-07-17 (tsortho now builds `[D]`/`[h]`/`[m]` coords; esa-sst's daily axis still reads as ns — republish someday); (b) optional int32/int16 packing for coarse/bounded ranges (hours-since-epoch fits int32 to year ~245k; minutes to ~6053). **Review finds to fold into (b)** (2026-07-17 dual-blind round): the packing must hook at the M8 override — `cfdb/creation.py:27-29` currently DISCARDS any explicit/packed DataType whenever datetime64 data is passed (that's also why `cfdb_vars.time_dtype_params`' pre-defined packed params never apply); latent bug: `CoordinateView.update_step` calls nonexistent `utils.coord_data_step_check` (`support_classes.py:935` — AttributeError on any populated coord); `init_parse_step` has its irregularity raises commented out (`utils.py:302,311` — silently yields step=None) and a `np.equal(int, timedelta64)` deprecation (`utils.py:310`, becomes an error in a future numpy; the toolkit sidesteps all three by passing explicit int steps).
- [ ] **[cfdb] ts_ortho → netCDF export crashes on the geometry coord** (independently reproduced 2026-07-22 on cfdb 0.9.4, the production floor; also seen on in-tree 0.9.5 during the ingest-toolkit station-metadata review): `ds.to_netcdf4(...)` on a minimal ts_ortho dataset (a geometry `point` coord + a `(point, time)` var) raises `AttributeError: 'Point' object has no attribute '_factor'` at `cfdb/main.py:600` — the export path assumes every coord dtype carries the numeric-packing `_factor`, which the Geometry dtype does not. Consequence: ts_ortho (station) datasets cannot be exported to netCDF at all, and CF variable attrs can't be verified through the netCDF archive path. Fix: a geometry-aware branch in the export (encode WKB/WKT, or skip `_factor` for non-numeric coord dtypes). Its own small cfdb round; not on the ingest critical path.

### cfdb-ingest and ifs-download

- [ ] **[cfdb-ingest, ifs-download] Pass `group_bytes=None` instead of `num_groups=None`** (added 2026-10-07, from the write-order-groups round). `cfdb_ingest/forecast_archive.py:81` and `ifs_dl/archive.py:72` pass `num_groups=None` to `cfdb.open_edataset`, meaning per-key. ebooklet 0.11 keeps that meaning for one release (an explicit `num_groups=None` maps to `group_bytes=None`; an omitted one would now default to grouped), and 0.12 removes the argument. Switch both to `group_bytes=None` with their cfdb floor raised to 0.11.0 in the same commit, and update cfdb-ingest's `docs/guide/forecast-datasets.md:106`.
- [ ] **[cfdb-ingest] Five WRF items MOVED 2026-10-09 to `~/git/wrf-repos/wrf-model-eval/OPEN_WORK.md`, Backlog → "cfdb-ingest and cfdb-vars"** (Mike: they affect WRF work; that file already held cfdb-ingest's other WRF items). They are: `WrfPlevIngest` `extend`, `extend` tests on region-dimensioned (WVT) variables, the 4.3–8.6 MB default chunks, the `only_variable` target option (wanted by every envlib producer, e.g. `envlib-ingest-wrf-3k`), and the CLI `--compression` help text. The `group_bytes=None` item above stays here because it belongs to the ebooklet 0.11 → 0.12 migration.

### envlib

- [ ] **[envlib] ts_ortho bbox spans 350° across the antimeridian** (added 2026-11-24, plan review `edr-api-plan-3`, Fable; checked live). The two ECan QC streamflow collections (`814fd7…`, `6ca564…`) hold two Chatham Islands stations at lon −176.7. `_extract_state` takes the plain min/max of the station longitudes, so their catalogue `bbox` is `[-176.664, -44.95, 173.84, -42.11]`: almost the whole globe, instead of a box crossing the antimeridian (west > east, which the catalogue already allows for grids). The EDR API copies the `bbox` into each collection's extent, and `Catalogue.query(bbox=…)` matches these collections far too widely. **Fix:** for point datasets, choose the smaller of the two longitude spans (the plain one, or the one across ±180) and write west > east when it crosses. **Close-check:** both collections' `bbox` becomes about `[169.8, -44.95, -176.55, -42.11]` after a re-publish, and a `Catalogue.query(bbox=…)` over the Atlantic no longer matches them. **Status (2026-11-26):** the fix is released in envlib 0.1.9 ("EDR plan 5: catalogue discovery": the shortest arc of the stations reprojected to EPSG:4326, whatever the CRS). Recomputed from the live datasets, both boxes become `[169.76028, -44.95052, -176.55923, -42.10505]`, and the other three station boxes are unchanged (`envlib-api/planning/close-checks-catalogue-2026-11-25.md`). The re-publish waits on the ingestion item "Rebuild the ingest images on envlib 0.1.9, so the station bboxes that cross 180° are corrected", because the ECan images install envlib from PyPI.
- [ ] **[envlib] Bundle the CF standard-name table v95** (added 2026-11-14). The bundled
      `envlib/vocabularies/standard_name.json` is v94; `vocabularies.refresh()` fetched v95 on 2026-11-14. Regenerate
      the bundled files with `refresh(_target_dir=...)` before the next release, and check the curated mappings
      against the new table.
- [ ] **[envlib] `Catalogue.refresh` turns a uuid-mismatched `.rcg` cache into an EMPTY catalogue** (added 2026-10-08, plan review `ecan-telemetry-plan-1b`, Sonnet executed it). `catalogue.py:801-812` catches `UUIDMismatchError`, warns and treats the source as empty, so a reader whose cached catalogue predates a recreated catalogue sees no datasets until the cache file is deleted. The per-key catalogue republish keeps the uuid, so it does not trigger this. A catalogue recreated from a different file would.
- [ ] **[envlib] Interval-start datasets: `time_end` is the last label, so coverage is under-reported by one interval** (added 2026-09-25, review round `wrf3k-ingest-plan-1`, all three arms). `_extract_state` sets `time_end = time[-1]` (`catalogue.py:393`), and `_time_overlaps` (`:1177`) drops a dataset when `time_end < start_date`. So a query starting inside the final interval misses the dataset: e.g. `start_date='…T22:30'` against an hourly dataset whose last label is 22:00. This applies to every interval-labelled dataset (esa-sst's last day too). Decide whether `time_end` means the last label or the end of coverage (label + `frequency_interval`), and document it.
- [ ] **[envlib] Grid bbox is taken from cell CENTRES, so it is half a cell short on every side** (added 2026-09-25, round `wrf3k-ingest-plan-1`, Gemini). `_extract_state` uses the x/y min/max (`catalogue.py:410–412`), so point queries in the outer half-cell of a domain miss: 1.5 km for WRF 3 km, 0.025° for esa-sst. The fix is to add half a step per side before `transform_bounds`.
- [ ] **[envlib] The first `publish` skips CV validation for producers that stamp via `Metadata.to_dict()`** (added 2026-09-25, round `wrf3k-ingest-plan-1`, Fable). `publish` sets `first_time = attrs.get('envlib_dataset_version_id') is None` (`catalogue.py:1013`), but `to_dict()` already writes the dvid, so the first publish validates with `validate_cv=False`. The `Metadata` constructor validates CVs on set, so this is mostly harmless today, but the heuristic doesn't do what its comment says. `validate_dataset(path)` still validates with CVs on.
- [ ] **[envlib] No test covers a projected-CRS grid bbox** (added 2026-09-25, round `wrf3k-ingest-plan-1`, Sonnet). The `not crs.is_geographic` branch of `_extract_state` (`transform_bounds(densify_pts=21)`) has no test in envlib or cfdb. Sonnet checked it against a dense-perimeter ground truth on a synthetic Lambert grid (agreement ~3×10⁻⁸°), including an antimeridian crossing. Add that as a regression test.
