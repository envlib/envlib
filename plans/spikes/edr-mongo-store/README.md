# Spike: a MongoDB-backed read store under cfdb (2026-11-23)

A throwaway prototype for the EDR API design. It is not production code. The decisions and results
are recorded in `plans/edr_api_assessment.md` §11. This directory keeps the scripts for the
implementation steps.

**What it showed.** cfdb reads a dataset unchanged through a store that keeps compressed chunks in
MongoDB. ebooklet's own remote fetchers fill that store on a miss, unchanged.

## How it differs from the decided design

The prototype predates part of the design. When reusing it, change the following:

- **Index.** It loads each dataset's remote index into the process. The decided design has the
  worker write index entries into MongoDB, and API processes hold no index.
- **Cache.** It keeps a per-process LRU of chunk bytes. The decided design has no process-level
  cache, and MongoDB is the only cache.
- **Store lifetime.** It shares one store object per process. The decided design builds a store per
  request.
- **Cache labels.** It labels every cached chunk with the index `ts`. The decided rule labels a chunk
  with the timestamp of the bytes actually fetched. For per-key storage that is the object's own
  metadata timestamp, which the sink already receives.
- **Healing.** On a 404 it re-pulls the index itself, a refresh plus one retry. In the decided design
  the API never refreshes the index: it re-reads the entry from MongoDB, then answers 503 or 500.
- **Eviction.** It uses no TTL index. The capped collection was tested instead, and TTL was chosen.

## Files

| File | Purpose |
|---|---|
| `mongo_store.py` | The prototype store and `open_dataset(store)` |
| `probe.py` | Opens each target dataset through the store and prints its shapes and chunk shapes. Writes `urls.json`. |
| `bench.py` | `ebk` mode: plain `cfdb.open_edataset`, cold then warm. `mongo` mode: the store in a fresh process, first pass then hot. |
| `compare.py` | Exact array equality (NaN positions included) between saved runs. Exits 1 on any difference. |
| `mutants.py` | Planted defects, applied by monkeypatch. Each must read DIFFERENT, raise, or heal to EQUAL. |
| `index_to_mongo.py` | Insert and lookup timings for whole remote indexes stored as MongoDB documents |
| `check_meta.py` | Compares the catalogue's `time_end` with each ECan dataset's last time value, and checks `station_id`/`station_ref` uniqueness |
| `urls.json` | The public `db_url`s used |
| `results/` | The raw JSON output of the runs. The first `ebk` run printed to the terminal only, so its numbers are in §11's table. |

## Running it

```bash
# an isolated environment with the released stack the spike used
uv venv -p 3.12 .venv
uv pip install -p .venv/bin/python "ebooklet==0.11.2" "booklet==0.12.11" "cfdb==0.11.0" "envlib==0.1.8" pymongo

# a throwaway MongoDB on a non-default port, on tmpfs (removed on stop)
docker run -d --rm --name envlib-spike-mongo -p 127.0.0.1:27018:27017 --tmpfs /data/db:size=8g mongo:8.0

mkdir -p out
.venv/bin/python bench.py ebk out/ebk1.npz            # baseline
.venv/bin/python bench.py mongo out/m_cold.npz c1     # empty collection: cold
.venv/bin/python bench.py mongo out/m_warm.npz c1     # fresh process, filled collection: warm
.venv/bin/python compare.py out/ebk1.npz out/m_cold.npz out/m_warm.npz
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python mutants.py skip_remote mut1   # also: fetch_silent, heal_once, gone_always
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python mutants.py swap_doc c1        # needs a filled collection and out/ebk1.npz

docker stop envlib-spike-mongo
```

Run the scripts from this directory, because they import `mongo_store` and read `out/` relative to
the working directory. They read the live public remotes, so the results depend on the network and on
the current data. Run the corruption mutants (`truncate_doc`, `swap_doc`) on separate collections:
the swap check cannot run on a collection that a truncation has already damaged.

The scripts were not written to the repo's lint settings. `ruff` and `black` report them.
