"""THROWAWAY SPIKE benchmark.

usage: bench.py ebk  OUT.npz            plain cfdb.open_edataset on a fresh cache: cold, then warm
       bench.py mongo OUT.npz COLL      the MongoDB store in a FRESH process: first pass, then hot
                                        (run once with an empty COLL = cold, again = Mongo-warm)
"""
import collections
import json
import pathlib
import sys
import tempfile
import time
import warnings

import cfdb
import ebooklet
import numpy as np
import pymongo

import mongo_store as ms

warnings.filterwarnings('ignore')
URLS = json.load(open(pathlib.Path(__file__).with_name('urls.json')))

CASES = [
    # name, dataset, var, selection (as a function of the variable's shape)
    ('ecan_1stn_2wk', 'ecan_raw_streamflow', 'streamflow', lambda s: (slice(10, 11), slice(s[1] - 336, s[1]))),
    ('ecan_1stn_full', 'ecan_raw_streamflow', 'streamflow', lambda s: (slice(10, 11), slice(0, s[1]))),
    ('ecan_all_48h', 'ecan_raw_streamflow', 'streamflow', lambda s: (slice(0, s[0]), slice(s[1] - 48, s[1]))),
    ('wrf_cell_1y', 'wrf_precip', 'precipitation', lambda s: (slice(s[0] - 8760, s[0]), slice(267, 268), slice(157, 158))),
    ('wrf_map_1h', 'wrf_precip', 'precipitation', lambda s: (slice(300000, 300001), slice(0, s[1]), slice(0, s[2]))),
    ('fc_latest_run', 'flow_fc', 'streamflow', lambda s: (slice(0, s[0]), slice(s[1] - 1, s[1]), slice(0, s[2]))),
    ('fc_last_120_runs', 'flow_fc', 'streamflow', lambda s: (slice(0, s[0]), slice(s[1] - 120, s[1]), slice(0, s[2]))),
]


def read(ds, var, selfn):
    v = ds[var]
    sel = selfn(v.shape)
    return np.asarray(v[sel].data)


def run_ebk(out):
    tmp = pathlib.Path(tempfile.mkdtemp(prefix='ebk-'))
    res, arrays = collections.defaultdict(dict), {}
    handles = {}
    for name, dsn, var, selfn in CASES:
        if dsn not in handles:
            t0 = time.perf_counter()
            handles[dsn] = cfdb.open_edataset(ebooklet.S3Connection(db_url=URLS[dsn]), tmp / f'{dsn}.cfdb', flag='r')
            res[dsn]['open_s'] = round(time.perf_counter() - t0, 3)
        ds = handles[dsn]
        t0 = time.perf_counter()
        a = read(ds, var, selfn)
        res[name]['cold_s'] = round(time.perf_counter() - t0, 3)
        t0 = time.perf_counter()
        b = read(ds, var, selfn)
        res[name]['warm_s'] = round(time.perf_counter() - t0, 4)
        assert np.array_equal(a, b, equal_nan=True)
        arrays[name] = a
    for ds in handles.values():
        ds.close()
    res['cache_MB'] = round(sum(f.stat().st_size for f in tmp.iterdir()) / 1e6, 1)
    np.savez(out, **arrays)
    print(json.dumps(res, indent=1))


def run_mongo(out, collname):
    coll = pymongo.MongoClient('mongodb://127.0.0.1:27018')['spike'][collname]
    res, arrays = collections.defaultdict(dict), {}
    stores = {}
    for name, dsn, var, selfn in CASES:
        if dsn not in stores:
            t0 = time.perf_counter()
            stores[dsn] = ms.MongoReadStore(URLS[dsn], coll)
            res[dsn]['open_s'] = round(time.perf_counter() - t0, 3)
        st = stores[dsn]
        before = collections.Counter(st.stats)
        t0 = time.perf_counter()
        ds = ms.open_dataset(st)          # per-request cfdb object on the current snapshot
        a = read(ds, var, selfn)
        ds.close()
        res[name]['first_s'] = round(time.perf_counter() - t0, 4)
        d = collections.Counter(st.stats)
        d.subtract(before)
        res[name]['first'] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in d.items() if v and k not in ('index_bytes',)}
        t0 = time.perf_counter()
        ds = ms.open_dataset(st)
        b = read(ds, var, selfn)
        ds.close()
        res[name]['hot_s'] = round(time.perf_counter() - t0, 4)
        assert np.array_equal(a, b, equal_nan=True)
        arrays[name] = a
    for st in stores.values():
        st.shutdown()
    stats = coll.database.command('collstats', collname)
    res['mongo'] = {'docs': stats['count'], 'data_MB': round(stats['size'] / 1e6, 1),
                    'storage_MB': round(stats['storageSize'] / 1e6, 1), 'max_doc_B': coll.find_one(sort=[('n', -1)])['n']}
    np.savez(out, **arrays)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    if sys.argv[1] == 'ebk':
        run_ebk(sys.argv[2])
    else:
        run_mongo(sys.argv[2], sys.argv[3])
