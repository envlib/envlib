"""Local (no-S3) tests for envlib.catalogue: validate, query matching, bbox logic, offline fallback."""

import warnings

import booklet
import cfdb
import numpy as np
import pytest
import shapely

from envlib import catalogue as cat_mod
from envlib.catalogue import Catalogue, ValidationError
from envlib.metadata import compute_station_id
from envlib.tests.conftest import DEFAULT_POINTS, build_grid, build_ts


def make_catalogue(entries=None, cache_dir=None) -> Catalogue:
    """Bare catalogue over synthetic entries (bypasses remote construction)."""
    cat = Catalogue.__new__(Catalogue)
    cat._cache_dir = cache_dir
    cat._sources = []
    cat._entries = dict(entries or {})
    return cat


def make_entry(user_meta, remote_conn=None):
    return {
        'entry_version': 1,
        'type': 'EVariableLengthValue',
        'timestamp': 0,
        'remote_meta': {},
        'user_meta': user_meta,
        'remote_conn': remote_conn
        or {'db_key': 'x.cfdb', 'bucket': 'b', 'endpoint_url': 'https://s3.example.com', 'db_url': None},
    }


###################################################
# validate()


def test_validate_grid_ok(tmp_path):
    meta = build_grid(tmp_path / 'g.cfdb')
    result = make_catalogue().validate(tmp_path / 'g.cfdb')
    assert result['dataset_version_id'] == meta.dataset_version_id
    assert result['dataset_id'] == meta.dataset_id
    assert result['state']['dataset_type'] == 'grid'
    assert result['state']['bbox'] == [170.0, -44.0, 172.0, -42.0]
    assert result['state']['time_start'] == '2020-01-01T00:00:00Z'
    assert result['state']['time_end'] == '2020-01-01T05:00:00Z'
    assert result['state']['x_step'] == 0.5
    assert result['state']['y_step'] == 0.5
    # (temperature, atmosphere) -> curated default auto-populates
    assert result['standard_name'] == {'action': 'populate', 'value': 'air_temperature'}


def test_validate_missing_units(tmp_path):
    build_grid(tmp_path / 'g.cfdb', with_units=False)
    with pytest.raises(ValidationError, match='units'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_missing_crs(tmp_path):
    build_grid(tmp_path / 'g.cfdb', with_crs=False)
    with pytest.raises(ValidationError, match='CRS'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_missing_time(tmp_path):
    build_grid(tmp_path / 'g.cfdb', with_time=False)
    with pytest.raises(ValidationError, match='time coordinate'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_primary_variable_name_mismatch(tmp_path):
    build_grid(tmp_path / 'g.cfdb', var_name='not_the_variable')
    with pytest.raises(ValidationError, match='primary data variable'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_missing_required_metadata(tmp_path):
    build_grid(tmp_path / 'g.cfdb')
    with cfdb.open_dataset(tmp_path / 'g.cfdb', flag='w') as ds:
        del ds.attrs['envlib_license']
    with pytest.raises(ValidationError, match='license'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_hand_edited_identity_detected(tmp_path):
    build_grid(tmp_path / 'g.cfdb')
    with cfdb.open_dataset(tmp_path / 'g.cfdb', flag='w') as ds:
        ds.attrs['envlib_owner'] = 'someone-else'
    with pytest.raises(ValidationError, match='dataset_version_id'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_standard_name_override_kept(tmp_path):
    build_grid(tmp_path / 'g.cfdb', var_attrs={'standard_name': 'surface_temperature'})
    result = make_catalogue().validate(tmp_path / 'g.cfdb')
    assert result['standard_name'] == {'action': 'keep', 'value': 'surface_temperature'}


def test_validate_standard_name_invalid_override_rejected(tmp_path):
    build_grid(tmp_path / 'g.cfdb', var_attrs={'standard_name': 'not_a_cf_name'})
    with pytest.raises(ValidationError, match='standard name'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_standard_name_curated_empty_absent(tmp_path):
    # (temperature, waterway) is curated to "no applicable standard name"
    build_grid(tmp_path / 'g.cfdb', meta_kwargs={'feature': 'waterway'})
    with warnings.catch_warnings():
        warnings.simplefilter('error')  # absent must NOT warn
        result = make_catalogue().validate(tmp_path / 'g.cfdb')
    assert result['standard_name'] == {'action': 'absent', 'value': None}


def test_validate_standard_name_uncurated_warns(tmp_path):
    # velocity is curated only for waterway; atmosphere is uncurated
    build_grid(tmp_path / 'g.cfdb', meta_kwargs={'variable': 'velocity'}, var_name='velocity')
    with pytest.warns(UserWarning, match='no curated CF standard_name'):
        result = make_catalogue().validate(tmp_path / 'g.cfdb')
    assert result['standard_name'] == {'action': 'uncurated', 'value': None}


def test_validate_ancillary_variables_checked(tmp_path):
    build_grid(tmp_path / 'g.cfdb', var_attrs={'ancillary_variables': 'temperature_qc'})
    with pytest.raises(ValidationError, match='ancillary'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


def test_validate_ts_ortho_ok(tmp_path):
    meta = build_ts(tmp_path / 't.cfdb')
    result = make_catalogue().validate(tmp_path / 't.cfdb')
    assert result['dataset_version_id'] == meta.dataset_version_id
    state = result['state']
    assert state['dataset_type'] == 'ts_ortho'
    assert 'x_step' not in state
    assert 'y_step' not in state
    assert state['bbox'][0] == pytest.approx(172.5)
    assert state['bbox'][2] == pytest.approx(174.78)
    assert result['standard_name'] == {'action': 'populate', 'value': 'water_volume_transport_in_river_channel'}


def test_validate_ts_missing_station_id(tmp_path):
    build_ts(tmp_path / 't.cfdb', station_ids=None)
    with pytest.raises(ValidationError, match='station_id'):
        make_catalogue().validate(tmp_path / 't.cfdb')


def test_validate_ts_wrong_station_id(tmp_path):
    sids = [compute_station_id(p) for p in DEFAULT_POINTS]
    sids[1] = 'deadbeefdeadbeefdeadbeef'
    build_ts(tmp_path / 't.cfdb', station_ids=sids)
    with pytest.raises(ValidationError, match='do not match'):
        make_catalogue().validate(tmp_path / 't.cfdb')


def test_validate_ts_spatial_resolution_must_be_point(tmp_path):
    build_ts(tmp_path / 't.cfdb', meta_kwargs={'spatial_resolution': '1km'})
    with pytest.raises(ValidationError, match="spatial_resolution='point'"):
        make_catalogue().validate(tmp_path / 't.cfdb')


###################################################
# bbox extraction: longitude wrapping through real datasets


def test_full_globe_0_360_grid_wraps_to_full_globe(tmp_path):
    lons = np.arange(0.0, 360.0, 0.25)
    build_grid(tmp_path / 'g.cfdb', lons=lons)
    result = make_catalogue().validate(tmp_path / 'g.cfdb')
    assert result['state']['bbox'][0] == -180.0
    assert result['state']['bbox'][2] == 180.0


def test_regional_crossing_grid_uses_crossing_convention(tmp_path):
    lons = np.arange(170.0, 190.25, 0.25)  # 170E..190E == 170E..170W
    build_grid(tmp_path / 'g.cfdb', lons=lons)
    bbox = make_catalogue().validate(tmp_path / 'g.cfdb')['state']['bbox']
    assert bbox[0] == pytest.approx(170.0)
    assert bbox[2] == pytest.approx(-170.0)
    assert bbox[0] > bbox[2]  # crossing convention, not a near-global box


def test_wrap_lon_extent_units():
    assert cat_mod._wrap_lon_extent(0.0, 359.75, 0.25) == (-180.0, 180.0)
    assert cat_mod._wrap_lon_extent(170.0, 190.0, None) == (170.0, -170.0)
    assert cat_mod._wrap_lon_extent(0.0, 10.0, 0.5) == (0.0, 10.0)
    assert cat_mod._wrap_lon_extent(-180.0, 180.0, None) == (-180.0, 180.0)


###################################################
# small helpers


def test_dt64_to_iso():
    assert cat_mod._dt64_to_iso(np.datetime64('2020-01-01T00', 'h')) == '2020-01-01T00:00:00Z'
    assert cat_mod._dt64_to_iso(np.datetime64('2020-01-01T00:00:00.500', 'ms')) == '2020-01-01T00:00:00.5Z'
    assert cat_mod._dt64_to_iso(np.datetime64('2020-06-15', 'D')) == '2020-06-15T00:00:00Z'


def test_validate_data_url():
    assert cat_mod._validate_data_url(None) is None
    url = 'https://b2.example.com/file/bucket/data.cfdb'
    assert cat_mod._validate_data_url(url) == url
    with pytest.raises(ValidationError, match='userinfo'):
        cat_mod._validate_data_url('https://user:pass@example.com/x')
    with pytest.raises(ValidationError, match='query string'):
        cat_mod._validate_data_url('https://example.com/x?X-Amz-Signature=abc')
    with pytest.raises(ValidationError, match='http'):
        cat_mod._validate_data_url('ftp://example.com/x')


###################################################
# query matching (synthetic entries; no S3)


def _grid_meta(**overrides):
    base = {
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
        'attribution': 'C3S',
        'dataset_version_id': 'a' * 24,
        'dataset_id': 's' * 12 + 'e' * 12,
        'dataset_type': 'grid',
        'bbox': [-180.0, -90.0, 180.0, 90.0],
        'time_start': '2020-01-01T00:00:00Z',
        'time_end': '2021-01-01T00:00:00Z',
        'created_at': '2026-01-01T00:00:00Z',
        'modified_at': '2026-01-01T00:00:00Z',
        'data_url': None,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def query_cat():
    e1 = make_entry(_grid_meta(dataset_version_id='1' * 24, version='1', created_at='2026-01-01T00:00:00Z'))
    e2 = make_entry(_grid_meta(dataset_version_id='2' * 24, version='2', created_at='2026-03-01T00:00:00Z'))
    e3 = make_entry(
        _grid_meta(
            dataset_version_id='3' * 24,
            dataset_id='f' * 24,
            variable='streamflow',
            owner='ecan',
            product_code=None,
            license='CC-BY-4.0',
            dataset_type='ts_ortho',
            spatial_resolution='point',
            bbox=[166.0, -47.0, -172.0, -34.0],  # crosses the antimeridian
            time_start='2015-01-01T00:00:00Z',
            time_end='2018-01-01T00:00:00Z',
            created_at='2026-02-01T00:00:00Z',
        )
    )
    return make_catalogue({'1' * 24: e1, '2' * 24: e2, '3' * 24: e3})


def _ids(refs):
    return sorted(r.dataset_version_id for r in refs)


def test_query_latest_per_dataset_default(query_cat):
    refs = query_cat.query(variable='temperature')
    assert _ids(refs) == ['2' * 24]  # v2 has the greater created_at


def test_query_version_pin(query_cat):
    refs = query_cat.query(variable='temperature', version='1')
    assert _ids(refs) == ['1' * 24]


def test_query_backfill_caveat():
    # documented v1 behavior: a version back-filled AFTER a newer version wins
    # "latest" because created_at, not the version string, decides it.
    e_new = make_entry(_grid_meta(dataset_version_id='4' * 24, version='2', created_at='2026-01-01T00:00:00Z'))
    e_backfill = make_entry(_grid_meta(dataset_version_id='5' * 24, version='1', created_at='2026-05-01T00:00:00Z'))
    cat = make_catalogue({'4' * 24: e_new, '5' * 24: e_backfill})
    refs = cat.query(variable='temperature')
    assert _ids(refs) == ['5' * 24]


def test_query_case_insensitive_mixed_case_cv(query_cat):
    refs = query_cat.query(license='cc-by-4.0')
    assert _ids(refs) == ['3' * 24]
    refs = query_cat.query(owner=['ECAN', 'NIWA'])
    assert _ids(refs) == ['3' * 24]


def test_query_none_matches_null_field(query_cat):
    refs = query_cat.query(product_code=None)
    assert _ids(refs) == ['3' * 24]


def test_query_dataset_type(query_cat):
    refs = query_cat.query(dataset_type='ts_ortho')
    assert _ids(refs) == ['3' * 24]


def test_query_bbox_antimeridian_both_sides(query_cat):
    east_side = query_cat.query(variable='streamflow', bbox=[178.0, -45.0, 179.0, -40.0])
    assert _ids(east_side) == ['3' * 24]
    west_side = query_cat.query(variable='streamflow', bbox=[-179.0, -45.0, -175.0, -40.0])
    assert _ids(west_side) == ['3' * 24]
    miss = query_cat.query(variable='streamflow', bbox=[0.0, -45.0, 10.0, -40.0])
    assert miss == []


def test_query_geometry_filter(query_cat):
    hit = query_cat.query(variable='streamflow', geometry=shapely.Point(179.0, -42.0).buffer(0.5))
    assert _ids(hit) == ['3' * 24]
    miss = query_cat.query(variable='streamflow', geometry=shapely.Point(10.0, -42.0).buffer(0.5))
    assert miss == []


def test_query_within_radius(query_cat):
    hit = query_cat.query(variable='streamflow', within_radius=((178.5, -42.0), 100))
    assert _ids(hit) == ['3' * 24]
    # point just west of the antimeridian, near the box's west half across 180°
    wrap_hit = query_cat.query(variable='streamflow', within_radius=((-179.9, -40.0), 50))
    assert _ids(wrap_hit) == ['3' * 24]
    miss = query_cat.query(variable='streamflow', within_radius=((0.0, -42.0), 100))
    assert miss == []


def test_query_temporal_overlap(query_cat):
    refs = query_cat.query(start_date='2019-01-01')
    assert _ids(refs) == ['2' * 24]  # e3 ends 2018; e1/e2 collapse to latest
    refs = query_cat.query(end_date='2016-06-01')
    assert _ids(refs) == ['3' * 24]
    refs = query_cat.query(start_date='2015-06-01', end_date='2020-06-01')
    assert _ids(refs) == ['2' * 24, '3' * 24]


def test_query_unknown_field_raises(query_cat):
    with pytest.raises(ValueError, match='unknown query fields'):
        query_cat.query(nope='x')


def test_query_spatial_filters_mutually_exclusive(query_cat):
    with pytest.raises(ValueError, match='mutually exclusive'):
        query_cat.query(bbox=[0, 0, 1, 1], within_radius=((0.0, 0.0), 10))


def test_distinct_values(query_cat):
    assert query_cat.distinct('variable') == ['streamflow', 'temperature']
    assert query_cat.distinct('owner') == ['ecan', 'ecmwf']
    # None excluded from the plain list...
    assert query_cat.distinct('product_code') == ['era5']
    # ...but present in the counts dict
    assert query_cat.distinct('product_code', counts=True) == {'era5': 2, None: 1}
    assert query_cat.distinct('dataset_type') == ['grid', 'ts_ortho']
    with pytest.raises(ValueError, match='unknown field'):
        query_cat.distinct('nope')


def test_distinct_plural_properties(query_cat):
    assert query_cat.variables == ['streamflow', 'temperature']
    assert query_cat.owners == ['ecan', 'ecmwf']
    assert query_cat.product_codes == ['era5']
    assert query_cat.features == ['atmosphere']
    assert query_cat.licenses == ['CC-BY-4.0', 'Copernicus-1.0']
    assert query_cat.dataset_types == ['grid', 'ts_ortho']
    assert query_cat.versions == ['1', '2']
    assert query_cat.methods == ['simulation']
    assert query_cat.processing_levels == ['quality_controlled']
    assert query_cat.aggregation_statistics == ['mean']
    assert query_cat.frequency_intervals == ['1h']
    assert query_cat.utc_offsets == ['+00:00']
    assert query_cat.spatial_resolutions == ['0.25deg', 'point']


###################################################
# DatasetRef


def test_datasetref_attribute_access(query_cat):
    ref = query_cat.query(variable='streamflow')[0]
    assert ref.variable == 'streamflow'
    assert ref.owner == 'ecan'
    assert ref.dataset_version_id == '3' * 24
    assert 'streamflow' in repr(ref)
    with pytest.raises(AttributeError):
        _ = ref.not_a_field


def test_datasetref_open_requires_url_or_credentials(query_cat, tmp_path):
    ref = query_cat.query(variable='streamflow')[0]
    ref._cache_dir = tmp_path
    with pytest.raises(ValidationError, match='no public db_url'):
        ref.open()


###################################################
# public RCG default + offline fallback


def test_bare_catalogue_without_public_rcg_raises(monkeypatch):
    monkeypatch.delenv(cat_mod.PUBLIC_RCG_ENV_VAR, raising=False)
    with pytest.raises(ValueError, match='public envlib RCG'):
        Catalogue()


def test_include_public_without_public_rcg_raises(monkeypatch, tmp_path):
    monkeypatch.delenv(cat_mod.PUBLIC_RCG_ENV_VAR, raising=False)
    with pytest.raises(ValueError, match='include_public'):
        Catalogue(remotes=['https://example.com/rcg'], cache=str(tmp_path), include_public=True)


def _write_fake_index(path, entries):
    with booklet.open(path, 'n', key_serializer='str', value_serializer='orjson', n_buckets=101) as blt:
        for key, value in entries.items():
            blt[key] = value


def test_read_cached_index_skips_non_entry_keys(tmp_path):
    path = tmp_path / 'index.rcg'
    entry = make_entry(_grid_meta())
    _write_fake_index(path, {'a' * 24: entry, 'internal_meta_key': {'not': 'an entry'}})
    result = cat_mod._read_cached_index(path)
    assert list(result) == ['a' * 24]
    assert result['a' * 24]['user_meta']['variable'] == 'temperature'


def test_catalogue_offline_fallback(tmp_path):
    url = 'https://envlib-test-nonexistent.invalid/rcg'
    cache_path = tmp_path / f'{cat_mod._conn_cache_key(url)}.rcg'
    _write_fake_index(cache_path, {'a' * 24: make_entry(_grid_meta())})
    with pytest.warns(UserWarning, match='operating offline'):
        cat = Catalogue(remotes=[url], cache=str(tmp_path))
    assert len(cat.datasets) == 1
    assert cat.datasets[0].variable == 'temperature'


def test_catalogue_offline_without_cache_raises(tmp_path):
    url = 'https://envlib-test-nonexistent.invalid/rcg'
    with pytest.raises(Exception, match=r'invalid|resolve|failed'):
        Catalogue(remotes=[url], cache=str(tmp_path))
