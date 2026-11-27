import sys, time, json
import pymongo
from envlib.catalogue import Catalogue
import mongo_store as ms
c = Catalogue()
want = {'8110f89cb7': 'ecan_raw_streamflow', 'c731b9ea49': 'wrf_precip'}
urls = {}
for d in c.datasets:
    if d.dataset_id[:10] in want:
        urls[want[d.dataset_id[:10]]] = d.entry['remote_conn']['db_url']
urls['flow_fc'] = 'https://b2.tethys-ts.xyz/file/point-forecasts/envlib/flow-forecasts/streamflow'
coll = pymongo.MongoClient('mongodb://127.0.0.1:27018')['spike']['probe']
for name, url in urls.items():
    st = ms.MongoReadStore(url, coll)
    ds = ms.open_dataset(st)
    print(name, url, st._kind, 'index', st.stats['index_bytes'], 'refresh %.2fs' % st.stats['refresh_s'])
    print('  type', ds.dataset_type, 'coords', {k: ds[k].shape for k in ds.coord_names})
    for v in ds.data_var_names:
        print('  var', v, ds[v].shape, ds[v].chunk_shape, ds[v].dtype)
    st.shutdown()
json.dump(urls, open('urls.json', 'w'), indent=1)
