# Producing Datasets

A dataset is a cfdb file that satisfies envlib's requirements. You build it with the [cfdb API](https://mullenkamp.github.io/cfdb/), describe it with `envlib.Metadata`, and hand it to `cat.validate()` / `cat.publish()`. This page covers the envlib-specific parts; for cfdb itself (chunk shapes, dtypes, appending, compression) use [cfdb's docs](https://mullenkamp.github.io/cfdb/).

## The requirements checklist

`validate()` and `publish()` enforce all of these:

- **Complete Identity metadata** (all 11 fields) plus `license` and `attribution`, stored in the file's attributes via `meta.to_dict()`.
- **Exactly one primary data variable, named after `meta.variable`** — if `variable='temperature'`, the file must contain `ds['temperature']`. Ancillary variables (QC flags, uncertainties) are welcome alongside it, declared via the CF `ancillary_variables` attribute on the primary variable.
- **`units` on the primary variable.** Units describe *your* stored data and are never auto-populated.
- **A CRS**, set with `ds.create.crs.from_user_input(...)`.
- **A `time` coordinate with at least one value.** Every envlib dataset is a time series — quasi-static data (a DEM, a soil map) carries a single timestamp marking the start of its validity, with revisions appended as new time slices.
- For station datasets: a **`station_id` variable** matching envlib's derivation (below).

Two conventions to know:

- **Time values are UTC instants** (timezone-naive `datetime64`, interpreted as UTC). The `utc_offset` field describes aggregation *boundaries*, it never shifts stored times.
- **Timestamps mark interval starts**: for aggregated data (anything but `aggregation_statistic='point'`), each time value is the *start* of its aggregation interval.

## Metadata: what the validation does for you

Every `Metadata` field validates and normalizes on assignment (construct all at once or field-by-field — order never matters):

```python
import envlib

meta = envlib.Metadata()
meta.feature = ' Atmosphere '        # -> 'atmosphere' (stripped, case-folded to the CV)
meta.owner = 'ECMWF'                 # -> 'ecmwf' (slugs lowercase; ASCII [a-z0-9._-], ≥1 letter/digit)
meta.frequency_interval = '60min'    # -> '1h' (input aliases resolve to the canonical code)
meta.spatial_resolution = '0.250deg' # ValidationError: non-canonical spellings are REJECTED, never rewritten
meta.utc_offset = 'Pacific/Auckland' # ValidationError: fixed offsets only
```

The rules worth internalizing:

- **`utc_offset` is a fixed offset, not a timezone.** Canonical form `±HH:MM`, range −12:00 to +14:00, minutes in {00, 15, 30, 45}. For DST-observing regions use standard time year-round (NZ = `+12:00`, never `+13:00`). It has meaning only when it changes the aggregation binning: an offset that divides the cadence evenly is automatically reduced to `+00:00` (hourly means at `+12:00` bin identically to UTC), while calendar cadences (`month`, `year`) always keep it.
- **`spatial_resolution`** is `<number><unit>` with units `m`/`km`/`deg` and exactly one accepted spelling per value (`0.25deg`, never `.25deg`/`0.250deg`) — or `point` for station datasets, or `None` for irregular grids.
- **`version` is a string and the string is the identity** — `1` and `1.0` are different versions. Pick a convention per dataset and keep it.
- **`product_code`** names the *production line* (`era5-land`, `stream_depletion_method_1`) — QC state does **not** belong there, that's `processing_level`. Plain observation collections use `None`.

## CF standard names: derived, not required

You do not set `standard_name` yourself. envlib curates the mapping from `(variable, feature)` to CF standard names and auto-populates the curated default at publish time:

```python
from envlib import vocabularies

vocabularies.get_cf_standard_names('temperature', feature='atmosphere')
# ['air_temperature']                       <- the first entry is what gets populated
vocabularies.get_cf_standard_names('temperature', feature='waterway')
# []                                        <- curated: NO applicable CF name (common for freshwater)
vocabularies.get_cf_standard_names('barometric_pressure', feature='atmosphere')
# ['air_pressure', 'air_pressure_at_mean_sea_level']   <- multiple candidates
```

- An **empty list** means envlib has verified no CF name applies (CF's water-property names are ocean-scoped, so freshwater water-quality legitimately has none) — the attribute simply stays absent, which is valid CF.
- To use a **non-default candidate** (say, the MSL-reduced pressure name), set `standard_name` on the variable yourself — envlib validates it against the CF table and keeps it.
- An **uncurated** `(variable, feature)` pair produces a warning, not an error.

## A complete grid dataset

```python
import numpy as np
import cfdb
import envlib

meta = envlib.Metadata(
    feature='atmosphere', variable='temperature', method='simulation',
    product_code='era5', processing_level='quality_controlled', owner='ecmwf',
    aggregation_statistic='mean', frequency_interval='1h', utc_offset='+00:00',
    spatial_resolution='0.25deg', version='1',
    license='Copernicus-1.0',
    attribution='Generated using Copernicus Climate Change Service information',
)

lats = np.arange(-44.0, -41.75, 0.25)
lons = np.arange(170.0, 172.25, 0.25)
times = np.arange('2020-01-01T00', '2020-01-02T00', dtype='datetime64[h]')

with cfdb.open_dataset('era5_temp_v1.cfdb', flag='n') as ds:
    ds.create.coord.lat(data=lats)
    ds.create.coord.lon(data=lons)
    ds.create.coord.time(data=times, dtype=times.dtype)
    ds.create.crs.from_user_input(4326, x_coord='longitude', y_coord='latitude')   # (1)

    dv = ds.create.data_var.generic('temperature',                                 # (2)
                                    ('latitude', 'longitude', 'time'), dtype='float32')
    dv.attrs['units'] = 'degC'                                                     # (3)
    dv[:] = np.zeros((len(lats), len(lons), len(times)), dtype='float32')

    # optional ancillary variable, declared on the primary
    qc = ds.create.data_var.generic('temperature_qc', ('latitude', 'longitude', 'time'), dtype='int8')
    qc[:] = np.ones((len(lats), len(lons), len(times)), dtype='int8')
    dv.attrs['ancillary_variables'] = 'temperature_qc'

    ds.attrs.update(meta.to_dict())                                                # (4)
```

The envlib-specific lines: **(1)** a CRS is required; **(2)** the primary variable's name equals `meta.variable`; **(3)** `units` is required; **(4)** the metadata rides in the file's attributes.

## Station time series (ts_ortho)

Station datasets store an orthogonal `(point, time)` layout: a geometry coordinate of shapely Points, with every station sharing the time axis. Two extra conventions apply — `spatial_resolution='point'`, and a `station_id` variable holding envlib's deterministic station hash so the same physical station gets the same id in *every* dataset that records it:

```python
import numpy as np
import shapely
import cfdb
import envlib

meta = envlib.Metadata(
    feature='waterway', variable='streamflow', method='sensor_recording',
    product_code=None, processing_level='quality_controlled', owner='ecan',
    aggregation_statistic='mean', frequency_interval='1h', utc_offset='+00:00',
    spatial_resolution='point', version='1',
    license='CC-BY-4.0', attribution='Environment Canterbury',
)

points = [shapely.Point(172.5, -43.5), shapely.Point(171.9, -43.1)]     # EPSG:4326
times = np.arange('2020-01-01T00', '2020-01-02T00', dtype='datetime64[h]')

with cfdb.open_dataset('ecan_flow_v1.cfdb', flag='n', dataset_type='ts_ortho') as ds:
    ds.create.coord.point()
    ds['point'].append(points)
    ds.create.coord.time(data=times, dtype=times.dtype)
    ds.create.crs.from_user_input(4326, xy_coord='point')

    dv = ds.create.data_var.generic('streamflow', ('point', 'time'), dtype='float32')
    dv.attrs['units'] = 'm^3/s'
    dv[:] = np.zeros((len(points), len(times)), dtype='float32')

    # the required station_id variable, derived with envlib's permanent hash    # (1)
    sid = ds.create.data_var.generic('station_id', ('point',), dtype='str')
    sid[:] = np.array([envlib.compute_station_id(p) for p in points])

    ds.attrs.update(meta.to_dict())
```

**(1)** `compute_station_id` rounds the point to 5 decimal places (~1 m) and hashes it; `validate()` recomputes and compares, so a wrong or stale id fails loudly. Points must be 2D shapely Points in EPSG:4326 (envlib reprojects for you at validation if the dataset's CRS differs; a z coordinate is ignored for identity).

Optional station attribute variables envlib recognizes (all shaped `(point,)`): `station_name`, `surface_altitude` (the ground level at the station — distinct from a vertical *measurement* axis, which is a cfdb coord named `altitude`/`height`/`depth`), and `operator` (when it differs from the dataset `owner`). Add any others you need; envlib doesn't constrain them.

Because `station_id` is deterministic, consumers can correlate stations *across* datasets by matching ids — no central station registry needed.

## Validate early, validate often

```python
cat = envlib.Catalogue(remotes=[])
result = cat.validate('era5_temp_v1.cfdb')     # raises ValidationError with a specific message
```

`validate()` is pure local inspection (no S3, no catalogue changes) — suitable for CI. When it passes, you're ready for [Publishing & Registration](publishing.md).
