"""Shared fixtures: S3-config gating for live tests + small cfdb dataset builders.

Live (S3) tests are gated on ``envlib/tests/s3_config.toml`` (git-ignored) with
env-var fallback — absent credentials skip them, so CI stays local-only. The
config's values are only ever passed into connection objects, never printed.
"""

import os
import pathlib

try:
    import tomllib
except ImportError:  # py3.10: no stdlib tomllib - fall back to tomli like the
    try:              # other stack repos' tests (a silent None here made the
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:  # live tier silently skip on a 3.10 venv, 2026-07-09)
        tomllib = None  # type: ignore[assignment]

import cfdb
import numpy as np
import pytest
import shapely

from envlib.metadata import Metadata, compute_station_id

TESTS_DIR = pathlib.Path(__file__).parent
LIVE_BUCKET = 'achelous'

GRID_META = {
    'feature': 'atmosphere',
    'variable': 'temperature',
    'method': 'simulation',
    'product_code': 'era5',
    'processing_level': 'quality_controlled',
    'owner': 'ecmwf',
    'aggregation_statistic': 'mean',
    'frequency_interval': '1h',
    'utc_offset': '+00:00',
    'spatial_resolution': '0.25deg',
    'version': '1',
    'license': 'Copernicus-1.0',
    'attribution': 'Generated using Copernicus Climate Change Service information',
}

TS_META = {
    'feature': 'waterway',
    'variable': 'streamflow',
    'method': 'sensor_recording',
    'product_code': None,
    'processing_level': 'quality_controlled',
    'owner': 'ecan',
    'aggregation_statistic': 'mean',
    'frequency_interval': '1h',
    'utc_offset': '+00:00',
    'spatial_resolution': 'point',
    'version': '1',
    'license': 'CC-BY-4.0',
    'attribution': 'Environment Canterbury',
}

DEFAULT_TIMES = np.arange('2020-01-01T00', '2020-01-01T06', dtype='datetime64[h]')

DEFAULT_POINTS = [shapely.Point(172.5, -43.5), shapely.Point(174.78, -41.29)]


def load_s3_config():
    path = TESTS_DIR / 's3_config.toml'
    if path.exists():
        if tomllib is None:
            return None
        with open(path, 'rb') as f:
            conn = tomllib.load(f).get('connection_config', {})
    else:
        conn = {k: os.environ.get(k) for k in ('endpoint_url', 'access_key_id', 'access_key')}
    if not all(conn.get(k) for k in ('endpoint_url', 'access_key_id', 'access_key')):
        return None
    return {k: conn[k] for k in ('endpoint_url', 'access_key_id', 'access_key')}


class _S3Config(dict):
    """Masked repr so pytest failure headers never print credential values."""

    def __repr__(self):
        return '<s3 config (values masked)>'


@pytest.fixture(scope='session')
def s3_config():
    config = load_s3_config()
    if config is None:
        pytest.skip('S3 credentials not available')
    return _S3Config(config)


def build_grid(
    path,
    meta_kwargs=None,
    lons=None,
    lats=None,
    times=None,
    var_name=None,
    var_attrs=None,
    *,
    with_crs=True,
    with_units=True,
    with_time=True,
):
    """Create a small grid cfdb file with envlib attrs; returns the Metadata used."""
    kwargs = dict(GRID_META)
    kwargs.update(meta_kwargs or {})
    meta = Metadata(**kwargs)
    if lons is None:
        lons = np.linspace(170.0, 172.0, 5, dtype='float64')
    if lats is None:
        lats = np.linspace(-44.0, -42.0, 5, dtype='float64')
    if times is None:
        times = DEFAULT_TIMES
    name = var_name or meta.variable
    with cfdb.open_dataset(path, flag='n') as ds:
        ds.create.coord.lat(data=lats, chunk_shape=(len(lats),))
        ds.create.coord.lon(data=lons, chunk_shape=(len(lons),))
        coords = ['latitude', 'longitude']
        if with_time:
            ds.create.coord.time(data=times, dtype=times.dtype)
            coords.append('time')
        if with_crs:
            ds.create.crs.from_user_input(4326, x_coord='longitude', y_coord='latitude')
        dv = ds.create.data_var.generic(name, tuple(coords), dtype='float32')
        if with_units:
            dv.attrs['units'] = 'degC'
        for key, value in (var_attrs or {}).items():
            dv.attrs[key] = value
        shape = tuple(len(c) for c in ([lats, lons, times] if with_time else [lats, lons]))
        dv[:] = np.ones(shape, dtype='float32')
        ds.attrs.update(meta.to_dict())
    return meta


def build_ts(path, meta_kwargs=None, points=None, times=None, station_ids='auto', *, with_units=True):
    """Create a small ts_ortho cfdb file with envlib attrs; returns the Metadata used.

    station_ids: 'auto' derives correct ids; None omits the station_id variable;
    a list uses those values verbatim (e.g. to test mismatch detection).
    """
    kwargs = dict(TS_META)
    kwargs.update(meta_kwargs or {})
    meta = Metadata(**kwargs)
    if points is None:
        points = DEFAULT_POINTS
    if times is None:
        times = DEFAULT_TIMES
    with cfdb.open_dataset(path, flag='n', dataset_type='ts_ortho') as ds:
        ds.create.coord.point()
        ds['point'].append(points)
        ds.create.coord.time(data=times, dtype=times.dtype)
        ds.create.crs.from_user_input(4326, xy_coord='point')
        dv = ds.create.data_var.generic(meta.variable, ('point', 'time'), dtype='float32')
        if with_units:
            dv.attrs['units'] = 'm^3/s'
        dv[:] = np.ones((len(points), len(times)), dtype='float32')
        if station_ids is not None:
            if station_ids == 'auto':
                station_ids = [compute_station_id(p) for p in points]
            sid_var = ds.create.data_var.generic('station_id', ('point',), dtype='str')
            sid_var[:] = np.array(station_ids)
        ds.attrs.update(meta.to_dict())
    return meta
