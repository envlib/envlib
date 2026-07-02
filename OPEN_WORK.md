# envlib — Open Work

Tracks **verification debts** (work done but not yet proven; each has a close-check — remove the item once it passes) and **backlog** (known work not yet started). The project spans repos — items are tagged: `[envlib]` (this repo), `[ebooklet]`, `[tethys]` (migration checks), `[infra]`.

_Last updated: 2026-07-02_

## Verification debts

- [ ] **[tethys] Timestamp convention check** — the revised architecture plan assumes tethys datasets used interval-start timestamps (migration compatibility for the global envlib convention). Close-check: inspect one known tethys dataset (e.g., a daily-mean series) and confirm stored time values mark interval start. Also listed in the plan's Verification section.
- [ ] **[ebooklet] Concurrent-writer semantics** — the plan flags as an open question whether ebooklet locking makes concurrent `RemoteConnGroup.add()`+push safe, or whether the index is last-writer-wins. Close-check: read/test ebooklet lock semantics; document the guarantee (or a single-writer restriction) in the plan before v1 release.
- [ ] **[envlib] pandas freqstr claim** — the plan asserts pandas canonical offset spellings changed in 2.2 (`'H'`→`'h'`, `'M'`→`'ME'`) as rationale for envlib-owned frequency codes; asserted from model knowledge, not run. Close-check: 5-minute experiment across pandas versions, or soften the wording. (The design decision doesn't hinge on it.)

## Backlog

- [ ] **[envlib] Dual-blind independent review of the architecture plan** — before implementation step 0 begins. Claude subagent + Gemini (human-driven `agy`), same adversarial brief and scope for both; proposed scope: `envlib/plans/`, `ebooklet`, `cfdb-repos/cfdb`, `booklet`, `tethys-repos/tethys-utils` sources. The hash serialization rules are the highest-stakes target (permanent once a second party registers a dataset).
- [ ] **[envlib] Resolve flagged plan judgment calls** from the 2026-07-02 revision: hash-order position of `processing_level` (currently #5); `cat.deregister()` shape (one method + `delete_data` flag); `envlib_` attr prefix; `modified_at` bumps-only-on-change rule; placeholder frequency codes. Plus: the Metadata example's `product_code='era5'` + `owner='niwa'` contradicts the plan's own owner semantics — fix or justify.
- [ ] **[ebooklet] Step 0 enhancement** — `key=` param on `RemoteConnGroup.add()` (+ `__setitem__` accepting an `S3Connection` value), explicit `user_meta=` param (cfdb's SysMeta occupies the remote metadata slot), and pin the exact RCG entry schema. Must be released before envlib implementation begins.
- [ ] **[envlib] Finalize the frequency_interval code table** (implementation step 1) — closed set, one spelling per cadence, no anchoring variants.
- [ ] **[envlib] Curate the variable → CF standard_name mapping** for the v1 / tethys-migration variable subset — incomplete-by-design; `refresh()` reports upstream diffs but never regenerates the curated mapping.
- [ ] **[envlib] Implementation steps 1–5** per `plans/architecture_plan.md`: vocabularies → metadata → catalogue → tests → public API exports.
- [ ] **[infra] Public RCG hosting** — read-only public-HTTPS RCG on Backblaze (S3-compatible), `ENVLIB_PUBLIC_RCG_URL` env-var override.
