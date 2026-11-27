import json, time, warnings, pymongo, random
from ebooklet import utils as eu
import mongo_store as ms
warnings.filterwarnings('ignore')
urls = json.load(open('urls.json'))
db = pymongo.MongoClient('mongodb://127.0.0.1:27018')['spike']
for name in ('wrf_precip', 'ecan_raw_streamflow'):
    st = ms.MongoReadStore(urls[name], db['scratch'])
    snap = str(st._remote_ts)
    t0 = time.perf_counter()
    docs = []
    for k, v in st._index.items():
        ts, gid, off, ln = eu.decode_index_entry(v)
        docs.append({'_id': f'{name}|{snap}|{k}', 'ts': ts, 'g': gid, 'o': off, 'l': ln})
    t_parse = time.perf_counter() - t0
    coll = db['index']
    t0 = time.perf_counter()
    for i in range(0, len(docs), 10000):
        coll.insert_many(docs[i:i + 10000], ordered=False)
    t_ins = time.perf_counter() - t0
    keys = [d['_id'] for d in docs]
    sample = keys[len(keys)//2: len(keys)//2 + 322]
    t0 = time.perf_counter()
    for _ in range(20):
        got = list(coll.find({'_id': {'$in': sample}}))
    t_look = (time.perf_counter() - t0) / 20
    one = random.sample(keys, 5)
    t0 = time.perf_counter()
    for _ in range(50):
        list(coll.find({'_id': {'$in': one}}))
    t_small = (time.perf_counter() - t0) / 50
    print(f'{name}: {len(docs)} entries, parse {t_parse:.2f}s, insert {t_ins:.2f}s, lookup 322 keys {t_look*1000:.1f} ms, lookup 5 keys {t_small*1000:.2f} ms, got {len(got)}')
    st.shutdown()
s = db.command('collstats', 'index')
print('index collection', s['count'], 'docs', round(s['size']/1e6, 1), 'MB data', round(s['totalIndexSize']/1e6, 1), 'MB _id index')
