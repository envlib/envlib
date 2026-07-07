"""Tests for envlib.vocabularies: bundled files, lookup semantics, overlay, refresh."""

import json

import pytest

from envlib import vocabularies as voc


@pytest.fixture(autouse=True)
def _clean_cache():
    voc.clear_cache()
    yield
    voc.clear_cache()


def test_all_fields_load_nonempty():
    for field in voc.FIELDS:
        values = voc.list(field)
        assert values, field
        assert all(isinstance(v, str) for v in values)


def test_unknown_field_raises():
    with pytest.raises(ValueError):
        voc.list('nope')
    with pytest.raises(ValueError):
        voc.canonical('nope', 'x')


def test_feature_cv_exact():
    assert voc.list('feature') == [
        'atmosphere',
        'waterway',
        'still_water',
        'ocean',
        'groundwater',
        'glacier',
        'wetland',
        'soil',
        'coastline',
        'land',
    ]


def test_method_cv_exact():
    assert set(voc.list('method')) == {
        'derivation',
        'estimation',
        'field_activity',
        'simulation',
        'sample_analysis',
        'sensor_recording',
        'forecast',
    }


def test_processing_level_cv_exact():
    assert voc.list('processing_level') == ['raw', 'preliminary', 'quality_controlled']


def test_aggregation_statistic_cv_exact():
    assert set(voc.list('aggregation_statistic')) == {
        'point',
        'mean',
        'sum',
        'maximum',
        'minimum',
        'median',
        'mode',
        'mid_range',
        'variance',
        'standard_deviation',
        'range',
    }


def test_frequency_table_complete():
    codes = voc.list('frequency_interval')
    assert codes == ['1min', '5min', '10min', '15min', '30min', '1h', '3h', '6h', '12h', 'day', 'month', 'year']
    entry = voc.frequency_entry('day')
    assert entry == {'name': 'day', 'kind': 'fixed', 'seconds': 86400, 'aliases': ['24h']}
    assert voc.frequency_entry('1h')['aliases'] == ['60min']
    for code in ('month', 'year'):
        entry = voc.frequency_entry(code)
        assert entry['kind'] == 'calendar'
        assert entry['seconds'] is None
    # every fixed duration divides 24 h evenly (the admission rule)
    for code in codes:
        entry = voc.frequency_entry(code)
        if entry['kind'] == 'fixed':
            assert 86400 % entry['seconds'] == 0, code


def test_frequency_alias_resolution():
    assert voc.canonical('frequency_interval', '24h') == 'day'
    assert voc.canonical('frequency_interval', '60min') == '1h'
    assert voc.canonical('frequency_interval', '60MIN') == '1h'
    # aliases are input-only: never listed as canonical codes
    assert '24h' not in voc.list('frequency_interval')
    assert voc.is_valid('frequency_interval', '24h')
    with pytest.raises(ValueError):
        voc.canonical('frequency_interval', '2h')


def test_license_mixed_case_canonicalization():
    assert 'CC-BY-4.0' in voc.list('license')
    assert 'Copernicus-1.0' in voc.list('license')
    assert voc.canonical('license', 'cc-by-4.0') == 'CC-BY-4.0'
    assert voc.canonical('license', ' COPERNICUS-1.0 ') == 'Copernicus-1.0'


def test_no_case_insensitive_collisions_in_any_cv():
    for field in voc.FIELDS:
        names = voc.list(field)
        lowered = [n.lower() for n in names]
        assert len(set(lowered)) == len(names), field


def test_standard_name_table():
    names = voc.list('standard_name')
    assert len(names) > 5000
    assert voc.is_valid('standard_name', 'air_temperature')
    assert not voc.is_valid('standard_name', 'not_a_real_standard_name')
    data = voc._load('standard_name')
    assert data['names']['air_temperature'] == 'K'
    assert data['aliases']  # kept for future use; aliases are NOT valid input
    an_alias = next(iter(data['aliases']))
    if an_alias not in data['names']:
        assert not voc.is_valid('standard_name', an_alias)


def test_variable_cv_membership():
    names = voc.list('variable')
    assert len(names) > 950  # ODM2 (~993) plus extensions
    for name in ('temperature', 'streamflow', 'precipitation', 'snowfall', 'e_coli', 'particulate_matter_2.5'):
        assert name in names, name


def test_temperature_per_feature_tristate():
    assert voc.get_cf_standard_names('temperature', 'atmosphere') == ['air_temperature']
    assert voc.get_cf_standard_names('temperature', 'soil') == ['soil_temperature']
    assert voc.get_cf_standard_names('temperature', 'ocean') == ['sea_water_temperature']
    # curated "none applicable" (freshwater: CF has only sea_water_*)
    assert voc.get_cf_standard_names('temperature', 'waterway') == []
    assert voc.get_cf_standard_names('temperature', 'still_water') == []
    assert voc.get_cf_standard_names('temperature', 'groundwater') == []
    # not curated for this feature
    assert voc.get_cf_standard_names('temperature', 'glacier') is None


def test_uncurated_variable_returns_none():
    assert voc.get_cf_standard_names('cadmium_dissolved', 'waterway') is None


def test_candidate_order_default_first():
    assert voc.get_cf_standard_names('barometric_pressure', 'atmosphere') == [
        'air_pressure',
        'air_pressure_at_mean_sea_level',
    ]
    assert voc.get_cf_standard_names('water_level', 'groundwater') == [
        'water_table_depth',
        'water_surface_height_above_reference_datum',
    ]
    assert voc.get_cf_standard_names('precipitation', 'atmosphere') == [
        'precipitation_amount',
        'lwe_thickness_of_precipitation_amount',
    ]


def test_ocean_only_names_never_on_freshwater():
    assert voc.get_cf_standard_names('electrical_conductivity', 'ocean') == ['sea_water_electrical_conductivity']
    assert voc.get_cf_standard_names('electrical_conductivity', 'waterway') == []
    assert voc.get_cf_standard_names('turbidity', 'waterway') == []
    assert voc.get_cf_standard_names('oxygen_dissolved', 'groundwater') == []


def test_get_cf_standard_names_validates_inputs():
    with pytest.raises(ValueError):
        voc.get_cf_standard_names('not_a_variable', 'atmosphere')
    with pytest.raises(ValueError):
        voc.get_cf_standard_names('temperature', 'not_a_feature')


def test_extensions_flagged_and_odm2_terms_recorded():
    entries = voc._load('variable')['entries']
    assert entries['snowfall']['source'] == 'envlib'
    assert entries['snowfall']['odm2_term'] is None
    assert entries['snowfall']['rationale']
    assert entries['nitrogen_nitrate']['source'] == 'odm2'
    assert entries['nitrogen_nitrate']['odm2_term'] == 'nitrogenNitrate_NO3'
    assert entries['gage_height']['odm2_term'] == 'gageHeight'


def test_curated_candidates_carry_canonical_units():
    entries = voc._load('variable')['entries']
    for candidate_list in entries['temperature']['cf'].values():
        for candidate in candidate_list:
            assert 'canonical_units' in candidate
    assert entries['temperature']['cf']['atmosphere'][0]['canonical_units'] == 'K'


def test_curated_cf_names_all_exist_in_cf_table():
    cf_names = voc._load('standard_name')['names']
    entries = voc._load('variable')['entries']
    for name, entry in entries.items():
        for feature, candidates in (entry.get('cf') or {}).items():
            for candidate in candidates:
                assert candidate['standard_name'] in cf_names, f'{name}/{feature}'


def test_user_dir_overlay_precedence(tmp_path, monkeypatch):
    monkeypatch.setattr(voc, 'USER_DIR', tmp_path)
    voc.clear_cache()
    assert voc.list('processing_level') == ['raw', 'preliminary', 'quality_controlled']
    overlay = {
        '_meta': {'vocabulary': 'processing_level'},
        'entries': [{'name': 'raw', 'description': 'overlay sentinel'}],
    }
    (tmp_path / 'processing_level.json').write_text(json.dumps(overlay))
    voc.clear_cache()
    assert voc.list('processing_level') == ['raw']
    # other fields still fall back to the bundled files
    assert len(voc.list('feature')) == 10


def test_refresh_rejects_nonrefreshable_fields():
    with pytest.raises(ValueError):
        voc.refresh('method')
    with pytest.raises(ValueError):
        voc.refresh('nope')


def test_refresh_network(tmp_path):
    """Live refresh against ODM2 + CF (auto-skipped when offline)."""
    try:
        report = voc.refresh(_target_dir=tmp_path)
    except Exception as err:  # any transport failure means offline
        pytest.skip(f'network unavailable: {err}')
    assert report['standard_name']['names'] > 5000
    assert report['variable']['total'] > 950
    assert not report['variable']['removed']
    assert (tmp_path / 'standard_name.json').exists()
    assert (tmp_path / 'variable.json').exists()
    # refresh must never touch curated fields or extensions
    with open(tmp_path / 'variable.json', encoding='utf-8') as f:
        refreshed = json.load(f)
    assert refreshed['entries']['snowfall']['source'] == 'envlib'
    assert refreshed['entries']['temperature']['cf']['waterway'] == []
