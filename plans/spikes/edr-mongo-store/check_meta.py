import collections, datetime, tempfile, pathlib, warnings
import numpy as np
from envlib.catalogue import Catalogue
warnings.filterwarnings('ignore')
c = Catalogue()
tmp = pathlib.Path(tempfile.mkdtemp())
print('now (UTC):', datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M'))
for d in c.datasets:
    if d.owner != 'ecan':
        continue
    m = d.metadata
    with d.open(file_path=tmp / f'{d.dataset_id[:10]}.cfdb') as ds:
        t = np.asarray(ds['time'][-1:].data)[-1]
        sid = [str(x) for x in np.asarray(ds['station_id'].data)]
        sref = [str(x) for x in np.asarray(ds['station_ref'].data)]
    dup_id = [k for k, n in collections.Counter(sid).items() if n > 1]
    dup_ref = [k for k, n in collections.Counter(sref).items() if n > 1]
    print(f"{d.dataset_id[:10]} {d.variable:14s} {d.processing_level:18s} catalogue time_end={m.get('time_end')}  data last time={t}  "
          f"rows={len(sid)} dup station_id={len(dup_id)} dup station_ref={len(dup_ref)} {dup_ref[:3]}")
