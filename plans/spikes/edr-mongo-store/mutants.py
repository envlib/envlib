"""Planted defects: each must produce DIFFERENT, an exception, or (for heal_once) a healed EQUAL read.

usage: mutants.py <mutant> <collection>
"""
import sys
import warnings

import numpy as np
import pymongo
from bson.binary import Binary
from ebooklet import utils as eu

import bench
import mongo_store as ms

warnings.filterwarnings('ignore')
mutant, collname = sys.argv[1], sys.argv[2]
coll = pymongo.MongoClient('mongodb://127.0.0.1:27018')['spike'][collname]
ref = np.load('out/ebk1.npz')
CASES = [c for c in bench.CASES if c[0] in ('ecan_1stn_2wk', 'wrf_map_1h', 'fc_latest_run')]

real_group, real_key = eu.get_remote_group_values, eu.get_remote_value
calls = {'n': 0}

if mutant == 'skip_remote':          # a miss silently returns nothing -> cfdb NaN-fills
    orig = ms.MongoReadStore._get_many

    def _get_many(self, keys, _retry=True):
        ents, _ = self._entries(keys)
        out = {}
        for k, e in ents.items():
            d = self._coll.find_one({'_id': self._cid(k, e[0])})
            if d:
                out[k] = bytes(d['v'])
        return out
    ms.MongoReadStore._get_many = _get_many
elif mutant == 'fetch_silent':       # fetchers deliver nothing and report nothing -> must be LOUD
    eu.get_remote_group_values = lambda *a, **k: None
    eu.get_remote_value = lambda *a, **k: None
elif mutant in ('heal_once', 'gone_always'):   # a GC'd generation: 404 once / forever
    def g(gid, gen, infos, sink, session, *a, **k):
        calls['n'] += 1
        if mutant == 'gone_always' or calls['n'] == 1:
            return eu.MissingRemoteObject(eu.group_obj_key(gid, gen), [i[0] for i in infos])
        return real_group(gid, gen, infos, sink, session, *a, **k)

    def p(sink, key, session):
        calls['n'] += 1
        if mutant == 'gone_always' or calls['n'] == 1:
            return eu.MissingRemoteObject(key, [key])
        return real_key(sink, key, session)
    eu.get_remote_group_values, eu.get_remote_value = g, p
elif mutant == 'corrupt_doc':        # one cached chunk's bytes are wrong
    d = coll.find_one({'_id': {'$regex': r'\|precipitation!119280\.0\.0\|'}})
    v = bytearray(d['v'])
    v[len(v) // 2] ^= 0xFF
    coll.update_one({'_id': d['_id']}, {'$set': {'v': Binary(bytes(v))}})
    print('corrupted', d['_id'][-40:])
elif mutant == 'truncate_doc':       # a cached chunk is cut short -> must RAISE
    d = coll.find_one({'_id': {'$regex': r'\|precipitation!119280\.24\.24\|'}})
    coll.update_one({'_id': d['_id']}, {'$set': {'v': Binary(bytes(d['v'])[: len(d['v']) // 2])}})
    print('truncated', d['_id'].split('|')[1])
elif mutant == 'swap_doc':           # valid bytes of ANOTHER chunk -> must read DIFFERENT
    m = ref['wrf_map_1h'][0]
    a_y, a_x = 240, 144              # target chunk; pick a donor whose selected-hour block differs
    donor = None
    for b_y in range(0, 528, 24):
        for b_x in range(0, 312, 24):
            if (b_y, b_x) != (a_y, a_x) and not np.array_equal(m[a_y:a_y + 24, a_x:a_x + 24], m[b_y:b_y + 24, b_x:b_x + 24], equal_nan=True):
                donor = (b_y, b_x)
                break
        if donor:
            break
    da = coll.find_one({'_id': {'$regex': rf'\|precipitation!119280\.{a_y}\.{a_x}\|'}})
    db = coll.find_one({'_id': {'$regex': rf'\|precipitation!119280\.{donor[0]}\.{donor[1]}\|'}})
    coll.update_one({'_id': da['_id']}, {'$set': {'v': db['v']}})
    print('swapped', da['_id'].split('|')[1], '<-', db['_id'].split('|')[1],
          'target block finite', int(np.isfinite(m[a_y:a_y + 24, a_x:a_x + 24]).sum()),
          'nonzero', int((m[a_y:a_y + 24, a_x:a_x + 24] != 0).sum()))
else:
    raise SystemExit(f'unknown mutant {mutant}')

stores = {}
for name, dsn, var, selfn in CASES:
    st = stores.setdefault(dsn, ms.MongoReadStore(bench.URLS[dsn], coll))
    try:
        ds = ms.open_dataset(st)
        a = bench.read(ds, var, selfn)
        ds.close()
        verdict = 'EQUAL' if np.array_equal(a, ref[name], equal_nan=True) else 'DIFFERENT'
    except Exception as e:
        verdict = f'RAISED {type(e).__name__}: {str(e)[:90]}'
    print(f'{mutant:13s} {name:15s} {verdict}  heal={st.stats["heal"]}')
