# Opening Data

A `DatasetRef` from `cat.query()` (or `cat.datasets`) opens the underlying cfdb file as a read-only [cfdb EDataset](https://mullenkamp.github.io/cfdb/guide/s3-remote/):

```python
refs = cat.query(variable='temperature', feature='ocean')   # the ESA sea surface temperature
ref = refs[0]
ds = ref.open()

ds['temperature']          # chunks pull from the remote on demand
ds.attrs['envlib_dataset_id']
ds.close()
```

Publicly hosted datasets — the normal case — open exactly like that: `ref.open()` reads via plain HTTPS from the dataset's public URL. No account, no keys. Catalogue entries **never contain credentials** — only the dataset's location and, when the owner configured one, its public `data_url`.

## Private buckets

Datasets hosted on private buckets are the exception: they need your own keys injected at open time:

```python
ds = ref.open(access_key_id='...', access_key='...')
```

!!! warning "Only inject credentials for endpoints you trust"
    Injected keys are used to cryptographically sign requests **against the entry's stored endpoint**. Supplying your keys when opening a third party's entry sends signed requests to *that party's server*. Inject credentials only for entries whose `endpoint_url`/`bucket` you recognize as yours (or your organisation's).

## The local cache

Opening downloads chunks into a local cfdb file — by default under the catalogue's cache directory (`~/.envlib/cache/<dataset_version_id>.cfdb`), or wherever you say:

```python
ds = ref.open(file_path='sea_temperature.cfdb')
```

Subsequent opens of the same file reuse already-downloaded chunks and fetch only what's missing or stale. envlib adds no cache policy of its own — eviction and disk management are yours (delete files from the cache directory freely).

## Reading the data

Everything from here is cfdb: indexing and `.loc` selection, chunk iteration, groupby, interpolation, netCDF4 export. See the [cfdb documentation](https://mullenkamp.github.io/cfdb/) — a good starting point:

```python
view = ds.select_loc({'time': slice('2020-01-01', '2020-01-07')})   # one week, the whole grid
subset = view['temperature'].data          # (7, 1000, 1600): ~45 MB in memory
```

Select before reading: `.data` decodes the whole selection into memory, and a published dataset can be far larger than RAM (the hourly WRF temperature is ~274 GB decoded). Only the chunks a selection touches are downloaded.

For station (`ts_ortho`) datasets, the geometry coordinate `ds['point']` returns shapely Points and `ds['station_id']` gives each station's permanent id — see [Producing Datasets](producing-datasets.md#station-time-series-ts_ortho) for the conventions.
