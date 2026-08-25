"""
Local (no-S3) tests for the ts_forecast / grid_forecast dataset types in envlib.

Each of these pins a specific way the pre-change code was silently wrong: a forecast dataset
was rejected outright for lacking a 'time' coordinate; a grid_forecast was routed into the
station-geometry branch; a ts_forecast skipped the station-identity check entirely; and two
datasets differing only by dataset_type shared a catalogue key.
"""
import numpy as np
import pytest

from envlib.catalogue import ValidationError
from envlib.metadata import compute_station_id
from envlib.tests.conftest import (
    DEFAULT_FRT,
    DEFAULT_LEAD,
    DEFAULT_POINTS,
    build_grid_forecast,
    build_ts,
    build_ts_forecast,
)
from envlib.tests.test_catalogue import make_catalogue


# --------------------------------------------------------------------------------------
# The time-coordinate blocker: forecast types validate WITHOUT a 'time' coordinate.
# --------------------------------------------------------------------------------------

def test_ts_forecast_validates_without_a_time_coord(tmp_path):
    p = tmp_path / 'f.cfdb'
    build_ts_forecast(p)
    result = make_catalogue().validate(p)
    assert result['state']['dataset_type'] == 'ts_forecast'


def test_grid_forecast_validates_without_a_time_coord(tmp_path):
    p = tmp_path / 'gf.cfdb'
    build_grid_forecast(p)
    result = make_catalogue().validate(p)
    assert result['state']['dataset_type'] == 'grid_forecast'


def test_non_forecast_types_still_require_time(tmp_path):
    """The relaxation must be scoped to forecast types only."""
    from envlib.tests.conftest import build_grid
    build_grid(tmp_path / 'g.cfdb', with_time=False)
    with pytest.raises(ValidationError, match='time coordinate'):
        make_catalogue().validate(tmp_path / 'g.cfdb')


# --------------------------------------------------------------------------------------
# The time range is the VALID range, computed via the units attr (not naive addition).
# --------------------------------------------------------------------------------------

def test_time_range_is_the_valid_range(tmp_path):
    p = tmp_path / 'r.cfdb'
    build_ts_forecast(p)
    state = make_catalogue().validate(p)['state']
    # first init (00:00) + SHORTEST lead (1 h). Not 00:00 -- no value in the file is valid then.
    assert state['time_start'].startswith('2024-01-01T01:00')
    # ... last init (06:00) + longest lead (4 h) == 10:00, NOT 06:04
    assert state['time_end'].startswith('2024-01-01T10:00'), (
        f"got {state['time_end']!r}: a value of 06:04 means the lead was added as MINUTES "
        f"against the datetime64[m] axis instead of being read through its units attr"
    )


def test_time_range_respects_a_non_hour_unit(tmp_path):
    """The unit is data, not an assumption: the same integers mean something different in days."""
    p = tmp_path / 'd.cfdb'
    build_ts_forecast(p, period_units=None)          # then set it explicitly below
    import cfdb
    with cfdb.open_dataset(str(p), flag='w') as ds:
        ds['forecast_period'].attrs['units'] = 'days'
    state = make_catalogue().validate(p)['state']
    # last init 06:00 + 4 DAYS
    assert state['time_end'].startswith('2024-01-05T06:00'), state['time_end']


def test_missing_units_on_forecast_period_is_refused(tmp_path):
    p = tmp_path / 'u.cfdb'
    build_ts_forecast(p, period_units=None)
    with pytest.raises(ValidationError, match='units'):
        make_catalogue().validate(p)


def test_forecast_dataset_is_found_by_a_valid_time_query(tmp_path):
    """End-to-end form: the range must actually make the dataset visible to a date query."""
    from envlib.tests.test_catalogue import make_entry
    p = tmp_path / 'q.cfdb'
    meta = build_ts_forecast(p)
    result = make_catalogue().validate(p)
    um = {f: getattr(meta, f) for f in ('feature', 'variable', 'method', 'owner')}
    um.update({
        'dataset_type': 'ts_forecast',
        'time_start': result['state']['time_start'],
        'time_end': result['state']['time_end'],
        'bbox': result['state']['bbox'],
        'dataset_version_id': result['dataset_version_id'],
        'dataset_id': result['dataset_id'],
    })
    cat = make_catalogue({result['dataset_version_id']: make_entry(um)})
    # a window that only the LEAD reaches into -- after every init, before the last valid time
    hits = cat.query(start_date='2024-01-01T08:00', end_date='2024-01-01T09:00')
    assert len(hits) == 1, 'valid-range time_end should make the forecast visible here'
    assert not cat.query(start_date='2024-01-02T00:00', end_date='2024-01-03T00:00')


# --------------------------------------------------------------------------------------
# method='forecast' is required (it is the only identity field that separates the types).
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize('builder', [build_ts_forecast, build_grid_forecast])
def test_forecast_types_require_method_forecast(tmp_path, builder):
    p = tmp_path / 'm.cfdb'
    builder(p, meta_kwargs={'method': 'simulation'})
    with pytest.raises(ValidationError, match="method='forecast'"):
        make_catalogue().validate(p)


# --------------------------------------------------------------------------------------
# _check_stations must RUN for ts_forecast -- the forecast<->measured join depends on it.
# --------------------------------------------------------------------------------------

def test_ts_forecast_station_ids_are_verified(tmp_path):
    p = tmp_path / 's.cfdb'
    wrong = [compute_station_id(DEFAULT_POINTS[0])] * len(DEFAULT_POINTS)
    build_ts_forecast(p, station_ids=wrong)
    with pytest.raises(ValidationError, match='do not match the envlib derivation'):
        make_catalogue().validate(p)


def test_ts_forecast_requires_a_station_id_variable(tmp_path):
    p = tmp_path / 'n.cfdb'
    build_ts_forecast(p, station_ids=None)
    with pytest.raises(ValidationError, match='station_id'):
        make_catalogue().validate(p)


def test_ts_forecast_and_ts_ortho_derive_the_same_station_ids(tmp_path):
    """The join is that these two hashes collide; assert it rather than assume it."""
    fp, tp = tmp_path / 'fc.cfdb', tmp_path / 'ms.cfdb'
    build_ts_forecast(fp)
    build_ts(tp)
    import cfdb
    ids = []
    for path in (fp, tp):
        with cfdb.open_dataset(str(path)) as ds:
            ids.append([str(v) for v in ds['station_id'].data])
    assert ids[0] == ids[1]


# --------------------------------------------------------------------------------------
# grid_forecast must reach the GRID bbox branch, not the station-geometry branch.
# --------------------------------------------------------------------------------------

def test_grid_forecast_uses_the_grid_bbox_branch(tmp_path):
    p = tmp_path / 'b.cfdb'
    build_grid_forecast(p)
    state = make_catalogue().validate(p)['state']
    assert state['bbox'] == pytest.approx([170.0, -44.0, 172.0, -42.0])
    assert 'x_step' in state and 'y_step' in state, \
        'x_step/y_step are only set on the grid branch -- their absence means it fell through'


def test_ts_forecast_requires_point_spatial_resolution(tmp_path):
    p = tmp_path / 'sr.cfdb'
    build_ts_forecast(p, meta_kwargs={'spatial_resolution': '0.25deg'})
    with pytest.raises(ValidationError, match="spatial_resolution='point'"):
        make_catalogue().validate(p)


# --------------------------------------------------------------------------------------
# The identity collision: dataset_type is not hashed, so it must be guarded at the write path.
# --------------------------------------------------------------------------------------

def test_dataset_type_is_not_an_identity_field(tmp_path):
    """
    Documents WHY the upsert guard exists. Two datasets whose 11 identity fields agree hash
    identically no matter how differently they are shaped -- so the catalogue key alone cannot
    tell a ts_forecast from a grid_forecast.
    """
    from envlib.metadata import compute_dataset_version_id
    from envlib.tests.conftest import TS_FORECAST_META
    fields = {k: v for k, v in TS_FORECAST_META.items()
              if k not in ('license', 'attribution')}
    assert compute_dataset_version_id(fields) == compute_dataset_version_id(dict(fields))


def test_upsert_refuses_a_dataset_type_change(tmp_path, monkeypatch):
    """
    The guard itself, exercised through _upsert_entry with the RCG stubbed out -- a live
    round-trip needs S3. Reachable today with a plain grid/ts_ortho pair, not just forecasts.
    """
    import contextlib

    from envlib import catalogue as cat_mod

    class _FakeRCG(dict):
        def get(self, k, default=None):
            return dict.get(self, k, default)

    stored = _FakeRCG({
        'abc123': {'user_meta': {'dataset_type': 'ts_ortho', 'created_at': '2024-01-01T00:00:00Z'}}
    })

    @contextlib.contextmanager
    def fake_open_rcg(*a, **k):
        yield stored

    monkeypatch.setattr(cat_mod.ebooklet, 'open_rcg', fake_open_rcg)
    monkeypatch.setattr(cat_mod, '_as_connection', lambda c: c)

    cat = make_catalogue()
    cat._rcg_cache_path = lambda conn: str(tmp_path / 'rcg')
    result = {'dataset_version_id': 'abc123', 'state': {'dataset_type': 'ts_forecast'}}

    with pytest.raises(ValidationError, match='already registered with dataset_type'):
        cat._upsert_entry(object(), object(), result)


# --------------------------------------------------------------------------------------
# Valid-range edge cases found by review round ecan-theta-code-1. Every one of these
# validated cleanly before the fix and produced a wrong catalogue range.
# --------------------------------------------------------------------------------------

def test_float_lead_is_refused_not_truncated(tmp_path):
    """A 1.5 h lead used to truncate to 1 h, understating time_end by 30 minutes silently."""
    p = tmp_path / 'fl.cfdb'
    build_ts_forecast(p, lead=np.array([0.5, 1.5], dtype='float32'), period_dtype='float32')
    with pytest.raises(ValidationError, match='must be an integer dtype'):
        make_catalogue().validate(p)


def test_negative_leads_do_not_invert_the_range(tmp_path):
    """
    Leads [-6, -3] against a single 06:00 init used to give time_start=06:00 > time_end=03:00.
    An inverted range makes _time_overlaps answer nonsensically -- invisible to some windows,
    wrongly matched by others.
    """
    p = tmp_path / 'neg.cfdb'
    build_ts_forecast(
        p,
        frt=np.array(['2024-01-01T06'], dtype='datetime64[m]'),
        lead=np.array([-6, -3], dtype='int32'),
    )
    state = make_catalogue().validate(p)['state']
    assert state['time_start'] < state['time_end'], 'range must not invert'
    assert state['time_start'].startswith('2024-01-01T00:00')   # 06:00 + (-6 h)
    assert state['time_end'].startswith('2024-01-01T03:00')     # 06:00 + (-3 h)


def test_time_start_accounts_for_the_minimum_lead(tmp_path):
    """
    A day-2-only product (leads 24-48 h, one init at 00:00) used to claim coverage from 00:00,
    a full day that does not exist in the file. The earliest valid time is init + min(lead).
    """
    p = tmp_path / 'd2.cfdb'
    build_ts_forecast(
        p,
        frt=np.array(['2024-01-01T00'], dtype='datetime64[m]'),
        lead=np.array([24, 48], dtype='int32'),
    )
    state = make_catalogue().validate(p)['state']
    assert state['time_start'].startswith('2024-01-02T00:00'), state['time_start']
    assert state['time_end'].startswith('2024-01-03T00:00'), state['time_end']


def test_bare_m_is_refused_as_ambiguous(tmp_path):
    """In CF/udunits 'm' is metres. Accepting it as minutes would misread a lead by 60x."""
    from envlib.catalogue import _cf_unit_to_np
    assert _cf_unit_to_np('min') == 'm'
    assert _cf_unit_to_np(' Hours ') == 'h'
    for bad in ('m', 'M', 'weeks', 'months', 'fortnight'):
        with pytest.raises(ValueError, match='unsupported time unit'):
            _cf_unit_to_np(bad)
