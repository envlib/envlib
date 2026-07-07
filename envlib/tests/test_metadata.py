"""Tests for envlib.metadata: golden-vector hashes, validators, Metadata class.

The golden vectors pin the permanent serialization contracts. Every expected
digest here was cross-checked against an independent stdlib-only
reimplementation (manual '\\x1f' join / struct-packed WKB) before being
committed — they must NEVER change.
"""

import struct
from hashlib import blake2b

import pytest
import shapely

from envlib.metadata import (
    IDENTITY_FIELDS,
    Metadata,
    ValidationError,
    compute_dataset_id,
    compute_dataset_version_id,
    compute_station_id,
    validate_slug,
    validate_spatial_resolution,
    validate_utc_offset,
)

# Golden vector A: all 11 identity fields set (the ERA5-style example).
VEC_A = {
    'feature': 'atmosphere',
    'variable': 'temperature',
    'method': 'simulation',
    'product_code': 'era5',
    'processing_level': 'quality_controlled',
    'owner': 'ecmwf',
    'aggregation_statistic': 'point',
    'frequency_interval': '1h',
    'utc_offset': '+00:00',
    'spatial_resolution': '0.25deg',
    'version': '2',
}
VEC_A_DATASET_VERSION_ID = '5fb10df86042d17bc646f5b7'
VEC_A_DATASET_ID = 'ce867e0bc92c80a58a39ef79'

# Golden vector B: all three nullable fields None (locks the "None" sentinel).
VEC_B = {
    'feature': 'waterway',
    'variable': 'streamflow',
    'method': 'sensor_recording',
    'product_code': None,
    'processing_level': 'raw',
    'owner': 'niwa',
    'aggregation_statistic': 'mean',
    'frequency_interval': None,
    'utc_offset': '+00:00',
    'spatial_resolution': None,
    'version': '1',
}
VEC_B_DATASET_VERSION_ID = 'c655970464bb569811ef6c64'
VEC_B_DATASET_ID = 'afd96ff1d282da0bc52e4ca0'

WELLINGTON = shapely.Point(174.7762, -41.2865)
WELLINGTON_STATION_ID = '032f5549c18f1c3ec87d4d74'
ZERO_LON_STATION_ID = 'f92630c38e30854bb6dd541a'  # Point(0.0, 51.5)


###################################################
# Golden vectors — permanent; never update these expected values


def test_golden_dataset_id_vector_a():
    assert compute_dataset_version_id(VEC_A) == VEC_A_DATASET_VERSION_ID
    assert compute_dataset_id(VEC_A) == VEC_A_DATASET_ID


def test_golden_dataset_id_vector_b_none_sentinel():
    assert compute_dataset_version_id(VEC_B) == VEC_B_DATASET_VERSION_ID
    assert compute_dataset_id(VEC_B) == VEC_B_DATASET_ID


def test_golden_ids_via_metadata_class():
    meta = Metadata(**VEC_A, license='Copernicus-1.0', attribution='C3S')
    assert meta.dataset_version_id == VEC_A_DATASET_VERSION_ID
    assert meta.dataset_id == VEC_A_DATASET_ID


def test_version_excluded_from_dataset_id_only():
    changed = dict(VEC_A, version='3')
    assert compute_dataset_version_id(changed) != VEC_A_DATASET_VERSION_ID
    assert compute_dataset_id(changed) == VEC_A_DATASET_ID


def test_hash_construction_is_keyless_blake2b12_utf8():
    joined = '\x1f'.join('None' if VEC_B[f] is None else VEC_B[f] for f in IDENTITY_FIELDS)
    assert blake2b(joined.encode('utf-8'), digest_size=12).hexdigest() == VEC_B_DATASET_VERSION_ID
    # UTF-8 is the pinned encoding: a different codec must produce a different id
    assert blake2b(joined.encode('utf-16-le'), digest_size=12).hexdigest() != VEC_B_DATASET_VERSION_ID


def test_golden_station_id():
    assert compute_station_id(WELLINGTON) == WELLINGTON_STATION_ID


def test_station_id_rounds_to_5dp():
    assert compute_station_id(shapely.Point(174.776204999, -41.286500001)) == WELLINGTON_STATION_ID


def test_station_id_signed_zero_collapses():
    # -0.000001 rounds to '-0.00000' in WKT, parsing back as IEEE-754 -0.0;
    # the +0.0 normalization must collapse it to the same id as +0.0.
    assert compute_station_id(shapely.Point(-0.000001, 51.5)) == ZERO_LON_STATION_ID
    assert compute_station_id(shapely.Point(0.0, 51.5)) == ZERO_LON_STATION_ID


def test_station_id_z_stripped():
    assert compute_station_id(shapely.Point(174.7762, -41.2865, 99.0)) == WELLINGTON_STATION_ID


def test_station_id_wkb_is_little_endian():
    manual_wkb = b'\x01' + struct.pack('<I', 1) + struct.pack('<dd', 174.7762, -41.2865)
    rounded = shapely.wkt.loads(shapely.wkt.dumps(WELLINGTON, rounding_precision=5))
    assert shapely.to_wkb(shapely.Point(rounded.x + 0.0, rounded.y + 0.0), byte_order=1) == manual_wkb


def test_station_id_rejects_non_points():
    with pytest.raises(ValidationError):
        compute_station_id(shapely.LineString([(0, 0), (1, 1)]))
    with pytest.raises(ValidationError):
        compute_station_id('POINT (0 0)')


def test_station_id_rejects_empty_point():
    # review finding (Gemini, 2026-07-07): the WKT round-trip preserves POINT EMPTY
    # and the signed-zero step then crashed with a raw GEOSException.
    with pytest.raises(ValidationError, match='non-empty'):
        compute_station_id(shapely.Point())


def test_station_id_rejects_non_finite_coordinates():
    # review finding (Claude, 2026-07-07): NaN/inf hashed to valid-looking ids.
    for x, y in ((float('nan'), 51.5), (float('inf'), 51.5), (174.0, float('-inf'))):
        with pytest.raises(ValidationError, match='finite'):
            compute_station_id(shapely.Point(x, y))


###################################################
# Validators — acceptance/rejection tables


def test_slug_normalization():
    assert validate_slug('owner', '  ECMWF ') == 'ecmwf'
    assert validate_slug('owner', 'era5-land_v1.2') == 'era5-land_v1.2'


@pytest.mark.parametrize('bad', ['NIWA Ltd', 'İstanbul', 'a/b', 'a\x1fb', '', ' ', 'niño', '.', '-', '_', '...', '.-_'])
def test_slug_rejections(bad):
    # punctuation-only forms rejected per the 2026-07-07 ruling (review finding):
    # slugs must contain at least one letter or digit
    with pytest.raises(ValidationError):
        validate_slug('owner', bad)


def test_utc_offset_canonicalization():
    assert validate_utc_offset('+00:00') == '+00:00'
    assert validate_utc_offset('-00:00') == '+00:00'
    assert validate_utc_offset('+12') == '+12:00'
    assert validate_utc_offset('-05:30') == '-05:30'
    assert validate_utc_offset('+12:45') == '+12:45'
    assert validate_utc_offset('-12:00') == '-12:00'
    assert validate_utc_offset('+14:00') == '+14:00'


@pytest.mark.parametrize(
    'bad',
    ['Z', 'Pacific/Auckland', '12:00', '+24:00', '+13:60', '+12:10', '-12:15', '+14:15', '+1:00', '+ 12:00', '+5'],
)
def test_utc_offset_rejections(bad):
    with pytest.raises(ValidationError):
        validate_utc_offset(bad)


def test_spatial_resolution_accepted():
    assert validate_spatial_resolution('0.25deg') == '0.25deg'
    assert validate_spatial_resolution('0.25DEG ') == '0.25deg'
    assert validate_spatial_resolution('1km') == '1km'
    assert validate_spatial_resolution('500m') == '500m'
    assert validate_spatial_resolution('point') == 'point'
    assert validate_spatial_resolution(None) is None


@pytest.mark.parametrize(
    'bad',
    ['.25deg', '00.25deg', '0.250deg', '1.0km', '1.km', '0.25 deg', '0.25_deg', '25e-2deg', '5mm', '1mile', 'none'],
)
def test_spatial_resolution_rejections(bad):
    with pytest.raises(ValidationError):
        validate_spatial_resolution(bad)


###################################################
# Metadata class behavior


def _full_meta(**overrides):
    kwargs = dict(VEC_A, license='Copernicus-1.0', attribution='C3S')
    kwargs.update(overrides)
    return Metadata(**kwargs)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Metadata(nope='x')


def test_cv_fields_canonicalized_case_insensitively():
    meta = _full_meta()
    meta.license = 'cc-by-4.0'
    assert meta.license == 'CC-BY-4.0'
    meta.feature = ' Atmosphere '
    assert meta.feature == 'atmosphere'
    with pytest.raises(ValueError):
        meta.variable = 'not_a_variable'


def test_all_setter_failures_are_validation_errors():
    # review finding (Claude, 2026-07-07): CV setters leaked bare
    # TypeError/ValueError; the contract is ValidationError everywhere
    # (a ValueError subclass, so except ValueError still works).
    meta = _full_meta()
    with pytest.raises(ValidationError):
        meta.variable = 'not_a_variable'
    with pytest.raises(ValidationError):
        meta.feature = 123
    with pytest.raises(ValidationError):
        meta.license = 3.14
    assert issubclass(ValidationError, ValueError)


def test_hash_eq_contract_with_reduced_offset():
    # review finding (BOTH reviewers, 2026-07-07): __eq__ compared the reduced
    # utc_offset but __hash__ hashed the raw stored one, so equal objects
    # hashed differently and set/dict dedup silently kept both.
    a = _full_meta(frequency_interval='1h', utc_offset='+12:00')  # reduces to +00:00
    b = _full_meta(frequency_interval='1h', utc_offset='+00:00')
    assert a == b
    assert hash(a) == hash(b)
    assert len({a, b}) == 1
    assert a.dataset_version_id == b.dataset_version_id


def test_frequency_alias_normalized_before_storage():
    meta = _full_meta(frequency_interval='24h')
    assert meta.frequency_interval == 'day'
    assert meta.to_dict()['envlib_frequency_interval'] == 'day'


def test_product_code_none_literal_rejected():
    with pytest.raises(ValidationError):
        _full_meta(product_code='none')
    meta = _full_meta(product_code=None)
    assert meta.product_code is None


def test_utc_offset_reduction_fixed_cadence():
    meta = _full_meta(frequency_interval='1h', utc_offset='+12:00')
    assert meta.utc_offset == '+00:00'  # 12 h divides 1 h binning evenly
    assert meta.to_dict()['envlib_utc_offset'] == '+00:00'


def test_utc_offset_retained_when_not_dividing():
    meta = _full_meta(frequency_interval='day', utc_offset='+12:00')
    assert meta.utc_offset == '+12:00'
    meta2 = _full_meta(frequency_interval='1h', utc_offset='+05:30')
    assert meta2.utc_offset == '+05:30'  # 5.5 h does not divide hourly bins


def test_utc_offset_calendar_cadence_always_retained():
    meta = _full_meta(frequency_interval='month', utc_offset='+12:00')
    assert meta.utc_offset == '+12:00'
    meta = _full_meta(frequency_interval='year', utc_offset='+01:00')
    assert meta.utc_offset == '+01:00'


def test_utc_offset_reduced_when_frequency_none():
    meta = _full_meta(frequency_interval=None, utc_offset='+05:00')
    assert meta.utc_offset == '+00:00'
    expected = compute_dataset_version_id(dict(VEC_A, frequency_interval=None, utc_offset='+00:00'))
    assert meta.dataset_version_id == expected


def test_reduction_is_construction_order_independent():
    a = Metadata()
    a.utc_offset = '+12:00'
    a.frequency_interval = '1h'
    b = Metadata()
    b.frequency_interval = '1h'
    b.utc_offset = '+12:00'
    assert a.utc_offset == b.utc_offset == '+00:00'


def test_dataset_id_incomplete_raises_listing_missing():
    meta = Metadata(feature='atmosphere', variable='temperature')
    with pytest.raises(ValidationError, match='owner'):
        _ = meta.dataset_version_id


def test_to_dict_requires_license_and_attribution():
    meta = Metadata(**VEC_A)
    with pytest.raises(ValidationError, match='license'):
        meta.to_dict()


def test_to_dict_emits_all_identity_keys_and_ids():
    meta = _full_meta(product_code=None)
    d = meta.to_dict()
    for field in IDENTITY_FIELDS:
        assert f'envlib_{field}' in d
    assert d['envlib_product_code'] is None
    assert d['envlib_dataset_version_id'] == meta.dataset_version_id
    assert d['envlib_dataset_id'] == meta.dataset_id
    assert 'envlib_description' not in d  # optional + unset -> absent


def test_from_attrs_round_trip():
    meta = _full_meta(description='ERA5 2m air temperature', derived_from=['https://doi.org/10.24381/cds.adbb2d47'])
    attrs = dict(meta.to_dict())
    attrs['history'] = 'non-envlib key ignored'
    rebuilt = Metadata.from_attrs(attrs)
    assert rebuilt == meta
    assert rebuilt.dataset_version_id == meta.dataset_version_id


def test_from_attrs_detects_hand_edited_identity():
    attrs = _full_meta().to_dict()
    attrs['envlib_owner'] = 'someone-else'
    with pytest.raises(ValidationError, match='dataset_version_id'):
        Metadata.from_attrs(attrs)


def test_from_attrs_without_cv_validation_tolerates_vocab_drift():
    # A dataset registered under a CV term that later vanished from the
    # vocabulary must stay readable and keep its dataset_version_id (validation on
    # change only). frequency code unknown -> offset used as stored.
    values = dict(VEC_A, variable='retired_term', frequency_interval='fortnight', utc_offset='+03:00')
    attrs = {f'envlib_{k}': v for k, v in values.items()}
    attrs['envlib_license'] = 'CC-BY-4.0'
    attrs['envlib_attribution'] = 'x'
    attrs['envlib_dataset_version_id'] = compute_dataset_version_id(values)
    with pytest.raises(ValueError):
        Metadata.from_attrs(attrs)  # validate_cv=True: unknown CV terms fail
    meta = Metadata.from_attrs(attrs, validate_cv=False)
    assert meta.dataset_version_id == attrs['envlib_dataset_version_id']
    assert meta.utc_offset == '+03:00'


def test_derived_from_and_doi_format_validation():
    meta = _full_meta(derived_from=[VEC_A_DATASET_VERSION_ID, 'https://doi.org/10.1000/xyz'])
    assert meta.derived_from == [VEC_A_DATASET_VERSION_ID, 'https://doi.org/10.1000/xyz']
    with pytest.raises(ValidationError):
        _full_meta(derived_from=['not-an-id'])
    with pytest.raises(ValidationError):
        _full_meta(derived_from='abc')  # must be a list
    with pytest.raises(ValidationError):
        _full_meta(doi='10.1000/xyz')  # must be the full URL form
    assert _full_meta(doi='https://doi.org/10.1000/xyz').doi == 'https://doi.org/10.1000/xyz'


def test_version_string_is_the_identity():
    ids = {compute_dataset_version_id(dict(VEC_A, version=v)) for v in ('1', '1.0', '01')}
    assert len(ids) == 3
