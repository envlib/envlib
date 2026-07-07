# Quick Start

## Finding and opening data

Most users start here: you want data someone else already published. The zero-config entry point is the public envlib catalogue — no configuration, no account, no credentials:

```python
import envlib

cat = envlib.Catalogue()         # the public envlib catalogue

# What does it contain?
cat.variables                    # ['precipitation', 'streamflow', 'temperature']
cat.owners                       # ['ecan', 'ecmwf', 'niwa']
cat.features                     # ['atmosphere', 'waterway']

# Filter down to what you want — the latest version of each matching dataset
refs = cat.query(
    variable='temperature',
    feature='atmosphere',
    bbox=[166, -47, 179, -34],           # WGS84 [min_lon, min_lat, max_lon, max_lat]
    start_date='2020-01-01',
)
refs[0]                          # prints its full metadata dict

# Open it — a cfdb dataset; chunks download on demand
ds = refs[0].open()
ds['temperature'].attrs['standard_name']    # 'air_temperature'
data = ds['temperature'].data
ds.close()
```

That's the whole flow — browse, query, open. From here it's the [cfdb API](https://mullenkamp.github.io/cfdb/) — selection, chunk iteration, netCDF export.

!!! note
    The public catalogue is not hosted yet — until it is, pass the location of a catalogue you know about instead: `envlib.Catalogue(remotes=['https://.../catalogue.rcg'])`. That form is also how you read any organisation-specific catalogue alongside (or instead of) the public one. Datasets on private buckets additionally need access keys injected at open time — see [Opening Data](../guide/opening-data.md#private-buckets).

## Publishing your own data

Producing is the same library in the other direction: build a cfdb file, describe it with envlib metadata, publish.

### 1. Build a dataset and attach metadata

The `Metadata` class validates and normalizes every field as you set it — invalid vocabulary terms, malformed offsets, or bad slugs fail immediately, not at publish time:

```python
import numpy as np
import cfdb
import envlib

meta = envlib.Metadata(
    feature='atmosphere',
    variable='temperature',
    method='simulation',
    product_code='era5',
    processing_level='quality_controlled',
    owner='ecmwf',
    aggregation_statistic='mean',
    frequency_interval='1h',
    utc_offset='+00:00',
    spatial_resolution='0.25deg',
    version='1',
    license='Copernicus-1.0',
    attribution='Generated using Copernicus Climate Change Service information',
)

lats = np.linspace(-44.0, -42.0, 5)
lons = np.linspace(170.0, 172.0, 5)
times = np.arange('2020-01-01T00', '2020-01-01T06', dtype='datetime64[h]')

with cfdb.open_dataset('data.cfdb', flag='n') as ds:
    ds.create.coord.lat(data=lats)
    ds.create.coord.lon(data=lons)
    ds.create.coord.time(data=times, dtype=times.dtype)
    ds.create.crs.from_user_input(4326, x_coord='longitude', y_coord='latitude')

    # the primary data variable must be named after meta.variable
    dv = ds.create.data_var.generic('temperature', ('latitude', 'longitude', 'time'), dtype='float32')
    dv.attrs['units'] = 'degC'
    dv[:] = np.random.default_rng(0).random((5, 5, 6)).astype('float32') * 10 + 5

    ds.attrs.update(meta.to_dict())
```

### 2. Validate

`validate()` checks everything a registration would — metadata completeness, the primary variable and its `units`, CRS, the time coordinate — and extracts the spatial/temporal extents, without touching any remote:

```python
cat = envlib.Catalogue(remotes=[])          # an empty catalogue works for validation
result = cat.validate('data.cfdb')

result['dataset_version_id']   # '5fb10df86042d17bc646f5b7'
result['state']['bbox']        # [170.0, -44.0, 172.0, -42.0]
result['standard_name']        # {'action': 'populate', 'value': 'air_temperature'}
```

Note the last line: you never set a CF `standard_name` — envlib derives it from its curated `(variable, feature)` mapping and will stamp it on the variable at publish time.

### 3. Publish

Publishing pushes the cfdb file to *your* S3 storage and registers it in a catalogue (an index hosted as its own S3 object). You need credentials for both:

```python
from ebooklet import S3Connection

data_conn = S3Connection(
    access_key_id='...', access_key='...',
    bucket='my-bucket', endpoint_url='https://s3.example.com',
    db_key='datasets/era5_temperature_v1.cfdb',
    db_url='https://s3.example.com/my-bucket/datasets/era5_temperature_v1.cfdb',  # public URL, optional
)
rcg_conn = S3Connection(
    access_key_id='...', access_key='...',
    bucket='my-bucket', endpoint_url='https://s3.example.com',
    db_key='catalogue.rcg',
)

cat = envlib.Catalogue(remotes=[rcg_conn])
cat.publish('data.cfdb', data_conn, rcg_conn, num_groups=101)   # prime numbers hash best
```

The data is pushed **before** the catalogue entry is written, so the catalogue never references incomplete data; re-running a failed publish is safe. Any consumer with the catalogue's location can now run the query at the top of this page and find your dataset.

## Where to next

- Station time series (`ts_ortho`) datasets: [Producing Datasets](../guide/producing-datasets.md)
- Query semantics, spatial filters, versions: [Browsing & Querying](../guide/browsing-querying.md)
- What the ids mean and why they never change: [The Data Model](../concepts/data-model.md)
