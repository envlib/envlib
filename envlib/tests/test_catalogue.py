"""Local (no-S3) tests for envlib.catalogue: validate, query matching, bbox logic, offline fallback."""

import warnings

import booklet
import cfdb
import ebooklet
import numpy as np
import pyproj
import pytest
import shapely

import envlib
from envlib import catalogue as cat_mod
from envlib.catalogue import Catalogue, ValidationError
from envlib.metadata import canonical_station_point, compute_station_id
from envlib.tests.conftest import DEFAULT_POINTS, DEFAULT_TIMES, TS_META, build_grid, build_ts


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


# A 6-dp coordinate on which cfdb's WKT writer and compute_station_id round the 5th decimal
# in opposite directions (ECan site 68839; a live publish failed on it 2026-08-24). Every
# other point fixture here is 1-2 dp, hence exactly representable at 5 dp and blind to this.
SIXDP_POINTS = [shapely.Point(171.1091, -43.631905)]


def test_validate_ts_raw_six_dp_point_is_rejected(tmp_path):
    # the defect itself, at the layer that catches it: storing the RAW point means cfdb
    # re-rounds it on write, and the stored geometry no longer derives the stored id.
    build_ts(tmp_path / 't.cfdb', points=SIXDP_POINTS)
    with pytest.raises(ValidationError, match='do not match'):
        make_catalogue().validate(tmp_path / 't.cfdb')


def test_validate_ts_canonicalised_six_dp_point_is_accepted(tmp_path):
    # ...and the fix: a producer that canonicalises before writing round-trips cleanly.
    canonical = [canonical_station_point(p) for p in SIXDP_POINTS]
    build_ts(tmp_path / 't.cfdb', points=canonical)
    result = make_catalogue().validate(tmp_path / 't.cfdb')
    assert result['state']['dataset_type'] == 'ts_ortho'
    # the id is unchanged by canonicalisation — that is what makes this fix a no-op for
    # every station already published
    assert compute_station_id(canonical[0]) == compute_station_id(SIXDP_POINTS[0])
    # bbox comes back CANONICAL, not raw: -43.63191, never the -43.631905 that went in
    assert result['state']['bbox'][1] == pytest.approx(-43.63191, abs=1e-9)


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
# The public matching functions (plan EDR plan 5; plan review edr-api-plan-5)


def _v(dvid, **overrides):
    """A version of the one temperature dataset, as stored user_meta."""
    return _grid_meta(dataset_version_id=dvid * 24, **overrides)


def test_a_created_at_tie_goes_to_the_greater_dataset_version_id_in_either_order():
    a = _v('a', version='1', created_at='2026-01-01T00:00:00Z')
    b = _v('b', version='2', created_at='2026-01-01T00:00:00Z')
    for order in ([a, b], [b, a]):
        assert [m['dataset_version_id'] for m in envlib.latest_per_dataset(order)] == ['b' * 24]
        assert [m['dataset_version_id'] for m in envlib.match_entries(order)] == ['b' * 24]
        cat = make_catalogue({m['dataset_version_id']: make_entry(m) for m in order})
        assert _ids(cat.query()) == ['b' * 24]


def test_a_newer_created_at_beats_a_greater_id():
    old = _v('f', version='1', created_at='2026-01-01T00:00:00Z')
    new = _v('1', version='2', created_at='2026-01-01T00:00:01Z')
    assert envlib.latest_per_dataset([old, new]) == [new]


def test_all_versions_returns_every_matching_version(query_cat):
    assert _ids(query_cat.query(variable='temperature', all_versions=True)) == ['1' * 24, '2' * 24]
    assert _ids(query_cat.query(variable='temperature', version='1', all_versions=True)) == ['1' * 24]
    assert _ids(query_cat.query(variable='temperature', all_versions=False)) == ['2' * 24]


def test_a_time_filter_can_return_an_older_version_and_latest_per_dataset_says_so():
    v1 = _v('1', version='1', created_at='2026-01-01T00:00:00Z', time_start='2018-01-01T00:00:00Z')
    v1['time_end'] = '2019-01-01T00:00:00Z'
    v2 = _v('2', version='2', created_at='2026-03-01T00:00:00Z', time_start='2020-06-01T00:00:00Z')
    metas = [v1, v2]
    assert envlib.match_entries(metas, end_date='2019-06-01') == [v1]  # the latest of the MATCHING versions
    assert envlib.latest_per_dataset(metas) == [v2]  # the version a collection serves


def test_match_entries_returns_the_input_dicts_themselves():
    metas = [_v('1', version='1'), _grid_meta(dataset_version_id='3' * 24, dataset_id='f' * 24)]
    out = envlib.match_entries(metas, all_versions=True)
    assert len(out) == 2 and all(any(o is m for m in metas) for o in out)


def test_query_order_is_datasets_by_first_appearance_then_entries_without_a_dataset_id():
    x1 = _grid_meta(dataset_version_id='1' * 24, dataset_id='x' * 24, created_at='2026-01-01T00:00:00Z')
    no_id = _grid_meta(dataset_version_id='2' * 24, dataset_id=None)
    y1 = _grid_meta(dataset_version_id='3' * 24, dataset_id='y' * 24)
    x2 = _grid_meta(dataset_version_id='4' * 24, dataset_id='x' * 24, version='2', created_at='2026-02-01T00:00:00Z')
    metas = [x1, no_id, y1, x2]
    assert [m['dataset_version_id'][0] for m in envlib.match_entries(metas)] == ['4', '3', '2']
    cat = make_catalogue({m['dataset_version_id']: make_entry(m) for m in metas})
    assert [r.dataset_version_id[0] for r in cat.query()] == ['4', '3', '2']


def test_an_unparsable_created_at_is_the_oldest_with_a_warning():
    bad = _v('f', version='1', created_at='not-a-date')
    good = _v('1', version='2', created_at='2026-01-01T00:00:00Z')
    with pytest.warns(UserWarning, match='unparsable created_at'):
        assert envlib.latest_per_dataset([bad, good]) == [good]


def test_an_unparsable_stored_time_matches_no_time_filter_with_a_warning():
    bad = _v('1', time_start='2020-13-45')
    with pytest.warns(UserWarning, match='unparsable time_start'):
        assert envlib.match_entries([bad], start_date='2020-06-01') == []
    assert envlib.match_entries([bad]) == [bad]  # no time filter: unaffected


@pytest.mark.parametrize('stored', [[1.0, 2.0, 3.0], ['a', 0, 1, 2], [0.0, 0.0, float('nan'), 1.0], 'oops'])
def test_a_malformed_stored_bbox_matches_no_spatial_filter_with_a_warning(stored):
    bad = _v('1', bbox=stored)
    with pytest.warns(UserWarning, match='malformed bbox'):
        assert envlib.match_entries([bad], bbox=[-180, -90, 180, 90]) == []
    with pytest.warns(UserWarning, match='malformed bbox'):
        assert envlib.match_entries([bad], within_radius=((0.0, 0.0), 1.0)) == []
    assert envlib.match_entries([bad]) == [bad]


def test_a_polygon_in_0_to_360_longitudes_finds_what_its_twin_finds():
    crossing = _v('1', bbox=[166.0, -47.0, -172.0, -34.0])
    east = shapely.box(-179.5, -40.0, -179.2, -39.0)
    east_360 = shapely.box(180.5, -40.0, 180.8, -39.0)
    west_neg = shapely.box(-190.0, -40.0, -189.0, -39.0)  # 170..171 written as -190..-189
    for geom in (east, east_360, west_neg):
        assert envlib.match_entries([crossing], geometry=geom) == [crossing]
    assert envlib.match_entries([crossing], geometry=shapely.box(10.0, -40.0, 11.0, -39.0)) == []


def test_pad_fraction_gives_python_3_10_six_digits():
    assert cat_mod._pad_fraction('2020-01-01T00:00:00.5+00:00') == '2020-01-01T00:00:00.500000+00:00'
    assert cat_mod._pad_fraction('2020-01-01T00:00:00.25') == '2020-01-01T00:00:00.250000'
    assert cat_mod._pad_fraction('2020-01-01T00:00:00.123456Z') == '2020-01-01T00:00:00.123456Z'
    assert cat_mod._pad_fraction('2020-01-01') == '2020-01-01'
    assert cat_mod._parse_iso('2020-01-01T00:00:00.5Z') == cat_mod._parse_iso('2020-01-01T00:00:00.500Z')


def test_a_sub_second_stored_time_matches_a_time_filter():
    sub = _v('1', time_start='2020-01-01T00:00:00.5Z', time_end='2020-12-31T00:00:00.25Z')
    assert envlib.match_entries([sub], start_date='2020-06-01') == [sub]


def test_distinct_counts_order_is_values_by_text_then_none():
    metas = [_v(dvid, product_code=code) for dvid, code in (('1', 'b'), ('2', None), ('3', 'a'), ('4', 'b'))]
    assert list(envlib.distinct_values(metas, 'product_code', counts=True).items()) == [('a', 1), ('b', 2), (None, 1)]


def test_distinct_of_mixed_types_sorts_by_text_instead_of_failing():
    metas = [_v('1', version='2'), _v('2', version=10), _v('3', version='1')]
    assert envlib.distinct_values(metas, 'version') == ['1', 10, '2']


def test_the_public_names_are_exported():
    assert envlib.QUERYABLE_FIELDS is cat_mod.QUERYABLE_FIELDS
    assert {'dataset_id', 'dataset_version_id', 'license', 'dataset_type', 'variable'} <= envlib.QUERYABLE_FIELDS
    with pytest.raises(ValueError, match='unknown query fields'):
        envlib.match_entries([], nope='x')


###################################################
# Station bboxes: the shortest arc of longitude (plan review edr-api-plan-5)


def _station_bbox(tmp_path, lons, lat=-43.5):
    points = [shapely.Point(lon, round(lat + 0.01 * i, 5)) for i, lon in enumerate(lons)]
    build_ts(tmp_path / 's.cfdb', points=points)
    return make_catalogue().validate(tmp_path / 's.cfdb')['state']['bbox']


def test_station_bbox_not_straddling_180_is_plain_min_max(tmp_path):
    assert _station_bbox(tmp_path, [172.5, 171.9, 173.84193]) == pytest.approx([171.9, -43.5, 173.84193, -43.48])


def test_station_bbox_with_the_chathams_crosses_180(tmp_path):
    bbox = _station_bbox(tmp_path, [172.5, 171.9, -176.664])
    assert bbox[::2] == pytest.approx([171.9, -176.664])  # west > east: 11.4 degrees, not 348.6


def test_station_bbox_of_stations_all_east_of_180(tmp_path):
    assert _station_bbox(tmp_path, [-176.664, -176.5])[::2] == pytest.approx([-176.664, -176.5])


def test_station_bbox_of_one_station(tmp_path):
    assert _station_bbox(tmp_path, [-176.5])[::2] == pytest.approx([-176.5, -176.5])


def test_station_bbox_takes_the_largest_gap_wherever_it_lies(tmp_path):
    ## 0, 100 and -100: gaps 100, 100 and 160 (across 180) -> plain min/max
    assert _station_bbox(tmp_path, [0.0, 100.0, -100.0])[::2] == pytest.approx([-100.0, 100.0])
    ## 0, 120 and -120: three equal gaps of 120, the one across 180 among them -> plain min/max
    assert _station_bbox(tmp_path, [0.0, 120.0, -120.0])[::2] == pytest.approx([-120.0, 120.0])
    ## 10, 120 and -120: the largest gap (130) is -120..10, so the arc runs 10 -> 120 -> 180 -> -120
    assert _station_bbox(tmp_path, [10.0, 120.0, -120.0])[::2] == pytest.approx([10.0, -120.0])


def test_smallest_lon_arc_unit_cases():
    assert cat_mod._smallest_lon_arc([179.0, 180.0]) == (179.0, 180.0)
    assert cat_mod._smallest_lon_arc([179.0, -179.0]) == (179.0, -179.0)
    assert cat_mod._smallest_lon_arc([170.0, 183.5]) == (170.0, 183.5)  # 0..360 input: no crossing in its own notation


@pytest.mark.parametrize(
    ('lons', 'expected', 'width'),
    [
        ([350.0, 10.0], (-10.0, 10.0), 20.0),  # 0..360 straddling Greenwich (was 340)
        ([359.0, 0.8], (-1.0, 0.8), 1.8),  # (was 358.2)
        ([180.0, -179.9], (180.0, -179.9), 0.1),  # a station at exactly 180 (was 359.9)
        ([180.0, -170.0], (180.0, -170.0), 10.0),  # (was 350)
        ([-180.0, 170.0], (170.0, -180.0), 10.0),
    ],
)
def test_the_arc_after_the_wrap_is_shortest_for_edge_inputs(lons, expected, width):
    """Code review edr-api-code-5: the plain branch took the raw min/max, not the normalised one."""
    w, e = cat_mod._wrap_lon_extent(*cat_mod._smallest_lon_arc(lons), None)
    assert (w, e) == pytest.approx(expected)
    assert (e - w) % 360.0 == pytest.approx(width)


def _ts_in_crs(path, crs, lonlats):
    """A ts_ortho dataset whose station points are stored in `crs`, ids derived as envlib derives them."""
    meta = envlib.Metadata(**TS_META)
    to_crs = pyproj.Transformer.from_crs(4326, crs, always_xy=True)
    points = [shapely.Point(*(round(v, 5) for v in to_crs.transform(lon, lat))) for lon, lat in lonlats]
    with cfdb.open_dataset(path, flag='n', dataset_type='ts_ortho') as ds:
        ds.create.coord.point()
        ds['point'].append(points)
        ds.create.coord.time(data=DEFAULT_TIMES, dtype=DEFAULT_TIMES.dtype)
        ds.create.crs.from_user_input(crs, xy_coord='point')
        dv = ds.create.data_var.generic(meta.variable, ('point', 'time'), dtype='float32')
        dv.attrs['units'] = 'm^3/s'
        dv[:] = np.ones((len(points), len(DEFAULT_TIMES)), dtype='float32')
        back = cat_mod._reproject_points(ds['point'].data, ds.crs)
        sid = ds.create.data_var.generic('station_id', ('point',), dtype='str')
        sid[:] = np.array([compute_station_id(p) for p in back])
        ds.attrs.update(meta.to_dict())


@pytest.mark.parametrize('crs', [4167, 2193])  # NZGD2000 (geographic, not 4326) and NZTM (projected)
def test_the_station_arc_does_not_depend_on_the_crs(tmp_path, crs):
    _ts_in_crs(tmp_path / 's.cfdb', crs, [(172.5, -43.5), (171.9, -43.1), (-176.664, -44.0)])
    w, _, e, _ = make_catalogue().validate(tmp_path / 's.cfdb')['state']['bbox']
    assert w > e and w == pytest.approx(171.9, abs=1e-4) and e == pytest.approx(-176.664, abs=1e-4)


@pytest.mark.parametrize(
    ('query', 'expected'),
    [
        ([175, -45, 184, -42], [175, -45, -176, -42]),  # 0..360 across 180
        ([-185, -45, -176, -42], [175, -45, -176, -42]),  # -360..0 across 180
        ([190, -1, 200, 1], [-170, -1, -160, 1]),
        ([0, -1, 360, 1], [-180, -1, 180, 1]),  # full width
        ([-180, -1, 180, 1], [-180, -1, 180, 1]),
        ([175, -45, -176, -42], [175, -45, -176, -42]),  # envlib's own convention, unchanged
        ([172.3, -44, 172.4, -43], [172.3, -44, 172.4, -43]),
    ],
)
def test_a_query_bbox_is_normalised_as_a_geometry_is(query, expected):
    assert cat_mod._query_bbox(query) == pytest.approx(expected)


def test_a_0_360_bbox_finds_what_its_twin_finds():
    crossing = _v('1', bbox=[166.0, -47.0, -172.0, -34.0])
    for query in ([181.0, -40.0, 183.0, -38.0], [-179.0, -40.0, -177.0, -38.0]):
        assert envlib.match_entries([crossing], bbox=query) == [crossing]
    assert envlib.match_entries([crossing], bbox=[10.0, -40.0, 11.0, -39.0]) == []


@pytest.mark.parametrize(
    'query',
    [
        [190, -10, -190, 10],  # west more than 360 degrees east of east
        [0, -10, 361, 10],
        [0, 10, 1, -10],  # south > north
        [0, -91, 1, 0],
        [0, 0, float('inf'), 1],
        [0, 0, 1],
        'oops',
    ],
    ids=str,
)
def test_a_query_bbox_envlib_cannot_read_raises(query):
    with pytest.raises(ValueError, match='bbox'):
        envlib.match_entries([_v('1')], bbox=query)


def test_a_non_finite_geometry_raises_value_error():
    """Code review edr-api-code-5: shapely's translate raised GEOSException, a 500 over HTTP."""
    with pytest.raises(ValueError, match='finite'):
        envlib.match_entries([_v('1')], geometry=shapely.from_wkt('POLYGON((inf 0,1 1,2 2,inf 0))'))


def test_the_matching_functions_take_any_iterable():
    metas = [_v(n, version=n, created_at=f'2026-0{n}-01T00:00:00Z') for n in ('1', '2')]
    assert envlib.match_entries(iter(metas)) == [metas[1]]
    assert envlib.match_entries((m for m in metas), all_versions=True) == metas
    assert envlib.latest_per_dataset(iter(metas)) == [metas[1]]
    assert envlib.distinct_values(iter(metas), 'version') == ['1', '2']


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


def test_public_rcg_default_and_override(monkeypatch):
    # The commons URL is baked in; the env var overrides it.
    monkeypatch.delenv(cat_mod.PUBLIC_RCG_ENV_VAR, raising=False)
    assert cat_mod._public_rcg_url() == cat_mod.PUBLIC_RCG_URL
    assert cat_mod.PUBLIC_RCG_URL.startswith('https://')
    monkeypatch.setenv(cat_mod.PUBLIC_RCG_ENV_VAR, 'https://example.com/standin')
    assert cat_mod._public_rcg_url() == 'https://example.com/standin'


def test_bare_catalogue_without_public_rcg_raises(monkeypatch):
    # Guard path: only reachable with the baked default nulled out.
    monkeypatch.delenv(cat_mod.PUBLIC_RCG_ENV_VAR, raising=False)
    monkeypatch.setattr(cat_mod, 'PUBLIC_RCG_URL', None)
    with pytest.raises(ValueError, match='public envlib RCG'):
        Catalogue()


def test_include_public_without_public_rcg_raises(monkeypatch, tmp_path):
    monkeypatch.delenv(cat_mod.PUBLIC_RCG_ENV_VAR, raising=False)
    monkeypatch.setattr(cat_mod, 'PUBLIC_RCG_URL', None)
    with pytest.raises(ValueError, match='include_public'):
        Catalogue(remotes=['https://example.com/rcg'], cache=str(tmp_path), include_public=True)


def _write_fake_index(path, entries):
    with booklet.open(path, 'n', key_serializer='str', value_serializer='orjson', n_buckets=101) as blt:
        for key, value in entries.items():
            blt[key] = value


def test_catalogue_offline_fallback(tmp_path):
    """An unreachable remote with a cached index serves the cache offline
    (ebooklet's offline='auto' fallback), applying the 24-hex entry filter."""
    url = 'https://envlib-test-nonexistent.invalid/rcg'
    cache_path = tmp_path / f'{cat_mod._conn_cache_key(url)}.rcg'
    _write_fake_index(cache_path, {'a' * 24: make_entry(_grid_meta()), 'internal_meta_key': {'not': 'an entry'}})
    with pytest.warns(UserWarning, match='unreachable'):
        cat = Catalogue(remotes=[url], cache=str(tmp_path))
    assert len(cat.datasets) == 1
    assert cat.datasets[0].variable == 'temperature'


def test_catalogue_offline_without_cache_raises(tmp_path):
    url = 'https://envlib-test-nonexistent.invalid/rcg'
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        with pytest.raises(ebooklet.OfflineError):
            Catalogue(remotes=[url], cache=str(tmp_path))


def test_refresh_reraises_integrity_error_despite_cache(tmp_path, monkeypatch):
    # ebooklet.RemoteIntegrityError subclasses HTTPError but means the remote
    # contradicts its own index - neither envlib's dispatch nor ebooklet's
    # offline='auto' classifier may swallow it into the cache fallback.
    url = 'https://example.com/rcg'
    cache_path = tmp_path / f'{cat_mod._conn_cache_key(url)}.rcg'
    _write_fake_index(cache_path, {'a' * 24: make_entry(_grid_meta())})

    def raise_integrity(*args, **kwargs):
        raise ebooklet.RemoteIntegrityError("index claims key(s) whose object is missing (integrity failure)")

    monkeypatch.setattr(cat_mod.ebooklet, 'open_rcg', raise_integrity)
    with pytest.raises(ebooklet.RemoteIntegrityError):
        Catalogue(remotes=[url], cache=str(tmp_path))


def test_refresh_uuid_mismatch_warns_identity_not_bootstrap(tmp_path, monkeypatch):
    url = 'https://example.com/rcg'

    def raise_uuid(*args, **kwargs):
        raise ebooklet.UUIDMismatchError('The local file has a different UUID than the remote file.')

    monkeypatch.setattr(cat_mod.ebooklet, 'open_rcg', raise_uuid)
    with pytest.warns(UserWarning, match='identity mismatch'):
        cat = Catalogue(remotes=[url], cache=str(tmp_path))
    assert cat.datasets == []


def test_refresh_unsupported_format_propagates(tmp_path, monkeypatch):
    # PRE-FIX regression: the old blanket `except ValueError` swallowed
    # UnsupportedFormatError (a ValueError subclass) and mislabeled it
    # "RCG source not readable yet". A too-new remote format must raise loudly.
    url = 'https://example.com/rcg'

    def raise_format(*args, **kwargs):
        raise ebooklet.UnsupportedFormatError("The remote's format_version 99 is newer than this ebooklet supports.")

    monkeypatch.setattr(cat_mod.ebooklet, 'open_rcg', raise_format)
    with pytest.raises(ebooklet.UnsupportedFormatError):
        Catalogue(remotes=[url], cache=str(tmp_path))


def test_raise_on_push_failure():
    # Clean results pass silently; any failures raise.
    cat_mod._raise_on_push_failure(ebooklet.PushResult(updated=True, failures={}), 'ctx')
    cat_mod._raise_on_push_failure(ebooklet.PushResult(updated=False, failures={}), 'ctx')
    with pytest.raises(RuntimeError, match='partially failed'):
        cat_mod._raise_on_push_failure(
            ebooklet.PushResult(updated=True, failures={'_group_3': 'HTTPError: injected'}),
            'publish: pushing the dataset data',
        )


def test_version_key_orders_a_datasets_versions_as_latest_per_dataset_does():
    tie_a = _v('a', version='1', created_at='2026-01-01T00:00:00Z')
    tie_b = _v('b', version='2', created_at='2026-01-01T00:00:00Z')
    older = _v('f', version='3', created_at='2025-01-01T00:00:00Z')
    fraction = _v(
        '1', version='4', created_at='2026-01-01T00:00:00.5Z'
    )  # later than the tie, though it sorts lower as text
    metas = [tie_a, older, fraction, tie_b]
    ordered = sorted(metas, key=envlib.version_key, reverse=True)
    assert ordered == [fraction, tie_b, tie_a, older]
    assert envlib.latest_per_dataset(metas) == [ordered[0]]
