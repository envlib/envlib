"""Live S3 tests for the envlib catalogue flows (config-gated; skipped without credentials).

Everything runs under a unique per-session prefix in the test bucket and is
swept in teardown (loud, verified by listing), so parallel/aborted runs can't
collide or leak objects.
"""

import uuid

import cfdb
import ebooklet
import pytest
import s3func

from envlib.catalogue import Catalogue, ValidationError
from envlib.tests.conftest import LIVE_BUCKET, build_grid, build_ts

RUN_PREFIX = f'envlib_pytest/{uuid.uuid4().hex[:12]}'


@pytest.fixture(scope='session')
def live(s3_config):
    """Connection factory bound to this run's unique prefix, with hardened teardown."""

    def make_conn(name, *, db_url=False):
        db_key = f'{RUN_PREFIX}/{name}'
        kwargs = dict(s3_config, bucket=LIVE_BUCKET, db_key=db_key)
        if db_url:
            kwargs['db_url'] = f'{s3_config["endpoint_url"].rstrip("/")}/{LIVE_BUCKET}/{db_key}'
        return ebooklet.S3Connection(**kwargs)

    yield make_conn

    # sweep everything under the run prefix; verify by listing
    session = s3func.S3Session(
        s3_config['access_key_id'], s3_config['access_key'], LIVE_BUCKET, endpoint_url=s3_config['endpoint_url']
    )
    try:
        session.delete_objects(prefix=RUN_PREFIX)
    except Exception as err:  # loud, then re-check below
        print(f'SWEEP WARNING: delete_objects raised {err!r}; re-listing')  # noqa: T201
    leftovers = [obj['key'] for obj in session.list_objects(prefix=RUN_PREFIX).iter_objects()]
    if leftovers:
        session.delete_objects(keys=leftovers)
        leftovers = [obj['key'] for obj in session.list_objects(prefix=RUN_PREFIX).iter_objects()]
    assert not leftovers, f'LEAKED REMOTE OBJECTS under {RUN_PREFIX}: {leftovers}'


@pytest.fixture()
def cache_dir(tmp_path):
    return tmp_path / 'cache'


def _catalogue(rcg_conn, cache_dir):
    return Catalogue(remotes=[rcg_conn], cache=str(cache_dir))


def test_publish_query_open_roundtrip(live, s3_config, tmp_path, cache_dir):
    data_conn = live('roundtrip/data.cfdb')
    rcg_conn = live('roundtrip/rcg')
    local = tmp_path / 'data.cfdb'
    meta = build_grid(local)

    with pytest.warns(UserWarning, match='treating as empty'):
        publisher = Catalogue(remotes=[rcg_conn], cache=str(cache_dir))
    assert publisher.datasets == []
    result = publisher.publish(local, data_conn, rcg_conn, num_groups=11)
    assert result['dataset_version_id'] == meta.dataset_version_id

    # a fresh consumer catalogue sees the entry
    cat = _catalogue(rcg_conn, cache_dir)
    refs = cat.query(variable='temperature', owner='ecmwf')
    assert len(refs) == 1
    ref = refs[0]
    assert ref.dataset_version_id == meta.dataset_version_id
    assert ref.standard_name == 'air_temperature'  # auto-populated at publish
    assert ref.entry['remote_conn'].get('access_key') is None  # creds never stored

    # open with injected credentials and read back
    ds = ref.open(
        file_path=tmp_path / 'consumer.cfdb',
        access_key_id=s3_config['access_key_id'],
        access_key=s3_config['access_key'],
    )
    try:
        assert ds.attrs['envlib_dataset_version_id'] == meta.dataset_version_id
        assert ds['temperature'].attrs['standard_name'] == 'air_temperature'
        assert float(ds['temperature'].data.max()) == 1.0
    finally:
        ds.close()


def test_republish_noop_keeps_modified_at(live, tmp_path, cache_dir):
    data_conn = live('noop/data.cfdb')
    rcg_conn = live('noop/rcg')
    local = tmp_path / 'data.cfdb'
    build_grid(local)

    with pytest.warns(UserWarning, match='treating as empty'):
        cat = Catalogue(remotes=[rcg_conn], cache=str(cache_dir))
    cat.publish(local, data_conn, rcg_conn, num_groups=11)
    first = cat.query(variable='temperature')[0].metadata

    cat.publish(local, data_conn, rcg_conn)
    second = cat.query(variable='temperature')[0].metadata
    assert second['modified_at'] == first['modified_at']
    assert second['created_at'] == first['created_at']

    # a real General Metadata change bumps modified_at and preserves created_at
    with cfdb.open_dataset(local, flag='w') as ds:
        ds.attrs['envlib_description'] = 'now with a description'
    cat.publish(local, data_conn, rcg_conn)
    third = cat.query(variable='temperature')[0].metadata
    assert third['description'] == 'now with a description'
    assert third['created_at'] == first['created_at']
    assert third['modified_at'] != first['modified_at']


def test_ts_ortho_publish_roundtrip(live, s3_config, tmp_path, cache_dir):
    data_conn = live('ts/data.cfdb')
    rcg_conn = live('ts/rcg')
    local = tmp_path / 'ts.cfdb'
    meta = build_ts(local)

    cat = Catalogue(remotes=[], cache=str(cache_dir))
    cat.publish(local, data_conn, rcg_conn, num_groups=11)

    consumer = _catalogue(rcg_conn, cache_dir / 'consumer')
    refs = consumer.query(dataset_type='ts_ortho')
    assert len(refs) == 1
    assert refs[0].dataset_version_id == meta.dataset_version_id
    assert refs[0].spatial_resolution == 'point'
    assert 'x_step' not in refs[0].metadata

    ds = refs[0].open(
        file_path=tmp_path / 'consumer_ts.cfdb',
        access_key_id=s3_config['access_key_id'],
        access_key=s3_config['access_key'],
    )
    try:
        sids = [str(v) for v in ds['station_id'].data]
        assert len(sids) == 2
        assert all(len(s) == 24 for s in sids)
        points = ds['point'].data
        assert all(p.geom_type == 'Point' for p in points)
    finally:
        ds.close()


def test_register_existing_remote(live, tmp_path, cache_dir):
    """Data pushed outside cat.publish() registers via cat.register() (no data push)."""
    data_conn = live('register/data.cfdb')
    rcg_conn = live('register/rcg')
    local = tmp_path / 'data.cfdb'
    meta = build_grid(local)

    # push the cfdb outside envlib (the pipeline-managed case)
    with cfdb.open_edataset(data_conn, local, flag='w', num_groups=11) as eds:
        eds.push()

    with pytest.warns(UserWarning, match='treating as empty'):
        cat = Catalogue(remotes=[rcg_conn], cache=str(cache_dir))
    result = cat.register(data_conn, rcg_conn)
    assert result['dataset_version_id'] == meta.dataset_version_id

    consumer = _catalogue(rcg_conn, cache_dir / 'consumer')
    refs = consumer.query(variable='temperature')
    assert len(refs) == 1
    # register wrote the self-identification attrs + standard_name to the remote
    assert refs[0].standard_name == 'air_temperature'


def test_deregister_guard_and_delete(live, s3_config, tmp_path, cache_dir):
    data_conn = live('dereg/data.cfdb')
    rcg_conn = live('dereg/rcg')
    local = tmp_path / 'a.cfdb'
    meta_a = build_grid(local)

    with pytest.warns(UserWarning, match='treating as empty'):
        cat = Catalogue(remotes=[rcg_conn], cache=str(cache_dir))
    cat.publish(local, data_conn, rcg_conn, num_groups=11)

    # the real shared-target trap: fix/bump the SAME file's identity (the
    # typo-correction flow: clear the stale self-identification attrs, change
    # version) and re-publish to the SAME remote target -> second entry, same data
    with cfdb.open_dataset(local, flag='w') as ds:
        ds.attrs['envlib_version'] = '2'
        del ds.attrs['envlib_dataset_version_id']
        del ds.attrs['envlib_dataset_id']
    cat.publish(local, data_conn, rcg_conn)
    meta_b = build_grid(tmp_path / 'reference_b.cfdb', meta_kwargs={'version': '2'})  # id reference only
    assert meta_a.dataset_version_id != meta_b.dataset_version_id

    # shared-target guard: deleting A's "data" would destroy B's data
    with pytest.raises(ValidationError, match='same remote target'):
        cat.deregister(
            meta_a.dataset_version_id,
            rcg_conn,
            delete_data=True,
            access_key_id=s3_config['access_key_id'],
            access_key=s3_config['access_key'],
        )

    # plain delist of A works and leaves the remote data up
    cat.deregister(meta_a.dataset_version_id, rcg_conn)
    refs = _catalogue(rcg_conn, cache_dir / 'c1').query(version=['1', '2'])
    assert [r.dataset_version_id for r in refs] == [meta_b.dataset_version_id]

    # retraction of B (now sole referent) deletes the remote data
    cat.deregister(
        meta_b.dataset_version_id,
        rcg_conn,
        delete_data=True,
        access_key_id=s3_config['access_key_id'],
        access_key=s3_config['access_key'],
    )
    assert _catalogue(rcg_conn, cache_dir / 'c2').datasets == []
    session = s3func.S3Session(
        s3_config['access_key_id'], s3_config['access_key'], LIVE_BUCKET, endpoint_url=s3_config['endpoint_url']
    )
    leftover = [obj['key'] for obj in session.list_objects(prefix=f'{RUN_PREFIX}/dereg/data.cfdb').iter_objects()]
    assert leftover == []


def test_deregister_missing_entry_raises(live, cache_dir, tmp_path):
    rcg_conn = live('missing/rcg')
    local = tmp_path / 'seed.cfdb'
    build_grid(local)
    with pytest.warns(UserWarning, match='treating as empty'):
        cat = Catalogue(remotes=[rcg_conn], cache=str(cache_dir))
    # seed the RCG so it exists remotely
    data_conn = live('missing/data.cfdb')
    cat.publish(local, data_conn, rcg_conn, num_groups=11)
    with pytest.raises(ValidationError, match='no catalogue entry'):
        cat.deregister('0' * 24, rcg_conn)
