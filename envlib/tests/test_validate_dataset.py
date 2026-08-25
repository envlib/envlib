"""
The public, catalogue-free validation entry point (``envlib.validate_dataset``).

It exists for producers that build envlib-shaped datasets WITHOUT publishing them -- a private
EDataset archive, say. Every structural guard envlib applies lives inside ``Catalogue.publish``'s
call to ``_validate_dataset``, so such a dataset would otherwise never be checked at all. The
guard that usually matters is ``_check_stations``: it recomputes each ``station_id`` from the
geometry stored beside it, which is the entire basis of a forecast<->measured station join.

``Catalogue`` cannot serve that need -- constructing one requires a public RCG and performs a
network refresh -- so the no-network property below is the point of the function, not a detail.
"""

import socket

import cfdb
import numpy as np
import pytest

import envlib
from envlib.catalogue import ValidationError
from envlib.tests.conftest import DEFAULT_POINTS, build_ts_forecast


def test_validate_dataset_accepts_a_path(tmp_path):
    path = tmp_path / 'fc.cfdb'
    build_ts_forecast(str(path))
    result = envlib.validate_dataset(str(path))
    assert result['metadata'].method == 'forecast'
    assert result['state']['dataset_type'] == 'ts_forecast'
    assert result['dataset_version_id']


def test_validate_dataset_accepts_an_open_dataset(tmp_path):
    """The form the toolkit actually uses: it already has the dataset open, and reopening a
    remote-linked file would start a second session against the remote."""
    path = tmp_path / 'fc.cfdb'
    build_ts_forecast(str(path))
    with cfdb.open_dataset(str(path)) as ds:
        result = envlib.validate_dataset(ds)
    assert result['state']['dataset_type'] == 'ts_forecast'


def test_validate_dataset_makes_no_network_call(tmp_path, monkeypatch):
    """The whole reason this is not Catalogue.validate. Any socket use is a hard failure."""
    path = tmp_path / 'fc.cfdb'
    build_ts_forecast(str(path))

    def _no_network(*_args, **_kwargs):
        msg = 'validate_dataset attempted a network connection'
        raise AssertionError(msg)

    monkeypatch.setattr(socket.socket, 'connect', _no_network)
    monkeypatch.setattr(socket.socket, 'connect_ex', _no_network)
    monkeypatch.setattr(socket, 'create_connection', _no_network)
    result = envlib.validate_dataset(str(path))
    assert result['state']['dataset_type'] == 'ts_forecast'


def test_validate_dataset_runs_check_stations(tmp_path):
    """The guard a never-published dataset would otherwise skip entirely."""
    path = tmp_path / 'fc.cfdb'
    build_ts_forecast(str(path), station_ids=['deadbeef' * 3] * len(DEFAULT_POINTS))
    with pytest.raises(ValidationError, match='do not match the envlib derivation'):
        envlib.validate_dataset(str(path))


def test_validate_dataset_refuses_missing_period_units(tmp_path):
    """forecast_period carries no default units on purpose; the refusal must survive this path."""
    path = tmp_path / 'fc.cfdb'
    build_ts_forecast(str(path), period_units=None)
    with pytest.raises(ValidationError, match='units'):
        envlib.validate_dataset(str(path))


def test_validate_dataset_returns_the_valid_time_range(tmp_path):
    """time_end is last init + longest lead -- the arithmetic that silently adds MINUTES if the
    forecast_period units attr is ignored (the axis is datetime64[m])."""
    path = tmp_path / 'fc.cfdb'
    frt = np.array(['2024-01-01T00', '2024-01-01T03'], dtype='datetime64[m]')
    build_ts_forecast(str(path), frt=frt, lead=np.arange(1, 5, dtype='int32'))
    state = envlib.validate_dataset(str(path))['state']
    assert state['time_start'].startswith('2024-01-01T01')
    assert state['time_end'].startswith('2024-01-01T07')


def test_validate_dataset_is_exported():
    assert 'validate_dataset' in envlib.__all__
    assert envlib.validate_dataset is not None
