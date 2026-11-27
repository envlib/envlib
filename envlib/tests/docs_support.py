"""Support for the docs example tests (Sybil), wired from the repo-root ``conftest.py``.

Every Python block of ``README.md`` and ``docs/**/*.md`` runs, page by page, top to bottom in one
namespace (Sybil). Run them with ``uv run pytest README.md docs`` (add ``--docs-live`` for the
blocks that read the live public commons). Per page:

- the cwd and ``HOME`` are a fresh scratch directory, and envlib's vocabulary overlay points there;
- S3 examples reach a local moto server: the docs' placeholder endpoint ``https://s3.example.com``
  and placeholder keys are rewritten inside ``ebooklet.remote.S3Connection.__init__``;
- in an offline run, any non-loopback network connection fails the page;
- afterwards, any cfdb dataset still open fails the page (an unclosed dataset makes the next open
  of its file wait forever on the lock).

Nothing here uses pytest fixtures: Sybil requests fixtures per example and never runs autouse ones,
so every per-page step lives in ``page_setup``/``page_teardown``, which Sybil calls once per page.
"""

import ctypes
import functools
import gc
import inspect
import ipaddress
import os
import pathlib
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types
import urllib.request
import warnings
from doctest import NORMALIZE_WHITESPACE

import boto3
import cfdb
import ebooklet
import numpy as np
from sybil import Sybil
from sybil.integration import pytest as sybil_pytest
from sybil.parsers.markdown import ClearNamespaceParser, PythonCodeBlockParser, SkipParser

from envlib import Metadata, vocabularies

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Per-example time limit (s). Healthy examples take well under a second; a page that leaks a
#: dataset lock would otherwise hang for good.
EXAMPLE_TIMEOUT = 30

#: Refuse a ``.data`` read that would decode more than this many bytes.
DATA_LIMIT_BYTES = 500e6

PLACEHOLDER_ENDPOINT = 'https://s3.example.com'
PLACEHOLDER_KEYS = ('...', 'YOUR_KEY', 'YOUR_SECRET')
BUCKET = 'my-bucket'
_PUBLIC_READ = (
    '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":"*",'
    '"Action":["s3:GetObject","s3:HeadObject"],"Resource":"arn:aws:s3:::my-bucket/*"}]}'
)


class _State:
    def __init__(self):
        self.live = False
        self.real_home: pathlib.Path | None = None
        self.home_snapshot: dict | None = None
        self.moto_proc: subprocess.Popen | None = None
        self.moto_url: str | None = None
        self.pages_run = 0
        self.pages: dict = {}
        self.failed_pages: set = set()
        self.violations: list = []


STATE = _State()


# --- which files are docs ---------------------------------------------------------------------


def is_doc_file(path) -> bool:
    """README.md at the repo root, or any .md under docs/ (the one definition both conftest.py
    and the inventory test use)."""
    try:
        rel = pathlib.Path(path).resolve().relative_to(ROOT)
    except ValueError:
        return False
    return rel.suffix == '.md' and (rel == pathlib.Path('README.md') or rel.parts[0] == 'docs')


def doc_files() -> list[pathlib.Path]:
    return [ROOT / 'README.md', *sorted(p for p in (ROOT / 'docs').rglob('*.md') if is_doc_file(p))]


def make_sybil() -> Sybil:
    # No global NUMBER or ELLIPSIS: an example that needs one opts in with "# doctest: +ELLIPSIS".
    return Sybil(
        parsers=[
            PythonCodeBlockParser(doctest_optionflags=NORMALIZE_WHITESPACE),
            SkipParser(),
            ClearNamespaceParser(),
        ],
        patterns=['*.md'],
        path=str(ROOT),  # patterns are matched relative to this (default: this module's dir)
        setup=page_setup,
        teardown=page_teardown,
        name='docs',
    )


def is_docs_item(item) -> bool:
    return type(item).__name__ == 'SybilItem'


def page_key(item) -> str:
    return item.parent.nodeid


# --- session ----------------------------------------------------------------------------------


def configure(config, real_home):
    STATE.live = bool(config.getoption('--docs-live'))
    STATE.real_home = pathlib.Path(real_home)
    STATE.home_snapshot = _snapshot(STATE.real_home / '.envlib')


def session_finish(session):
    _stop_moto()
    if not STATE.pages_run or STATE.home_snapshot is None:
        return
    changed = _diff(STATE.home_snapshot, _snapshot(STATE.real_home / '.envlib'))
    if changed:
        sys.stderr.write(
            f'\nHOME GUARD: the docs run changed the real {STATE.real_home / ".envlib"}: {changed}\n'
            '(If another process on this machine wrote there meanwhile, this is a false alarm.)\n'
        )
        session.exitstatus = 1


def _snapshot(root: pathlib.Path) -> dict:
    if not root.exists():
        return {}
    out = {'.': 'dir'}
    for p in root.rglob('*'):
        try:
            st = p.lstat()
        except FileNotFoundError:
            continue
        out[str(p.relative_to(root))] = 'dir' if p.is_dir() else (st.st_size, st.st_mtime_ns)
    return out


def _diff(before: dict, after: dict) -> list[str]:
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))


# --- moto -------------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _die_with_parent():
    # Runs in the moto child before exec: the kernel sends it SIGTERM when pytest dies, even by
    # SIGTERM or SIGKILL, which skip pytest's own session-finish hook (Linux only).
    try:
        ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)  # 1 = PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


def _ensure_moto():
    if STATE.moto_proc is not None:
        return
    port = _free_port()
    proc = subprocess.Popen(  # noqa: S603 (a fixed command: this interpreter's moto server)
        [sys.executable, '-m', 'moto.server', '-H', '127.0.0.1', '-p', str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        preexec_fn=_die_with_parent if sys.platform.startswith('linux') else None,  # noqa: PLW1509
    )
    url = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + 30
    while True:
        try:
            urllib.request.urlopen(f'{url}/moto-api/', timeout=1).close()  # noqa: S310 (loopback http)
            break
        except OSError:
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                msg = 'the moto server did not start'
                raise RuntimeError(msg) from None
            time.sleep(0.1)
    STATE.moto_proc, STATE.moto_url = proc, url


def _stop_moto():
    proc = STATE.moto_proc
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(5)
    STATE.moto_proc = None


def _reset_moto():
    req = urllib.request.Request(f'{STATE.moto_url}/moto-api/reset', method='POST')  # noqa: S310 (loopback http)
    urllib.request.urlopen(req, timeout=10).close()  # noqa: S310
    s3 = boto3.client(
        's3',
        endpoint_url=STATE.moto_url,
        aws_access_key_id='test',
        aws_secret_access_key='test',
        region_name='us-east-1',
    )
    s3.create_bucket(Bucket=BUCKET)
    # public read, so a published entry's data_url opens credential-free (as on a real public bucket)
    s3.put_bucket_policy(Bucket=BUCKET, Policy=_PUBLIC_READ)


_ORIG_S3_INIT = ebooklet.remote.S3Connection.__init__


def _install_s3_rewrite():
    """Rewrite the docs' placeholders to the moto server inside S3Connection itself.

    Patched on the class (not the ``ebooklet.S3Connection`` name), because ebooklet builds its
    own connection for URL-string and dict remotes (``ebooklet/remote.py`` ``check_remote_conn``).
    """
    cls = ebooklet.remote.S3Connection
    if getattr(cls.__init__, '_docs_rewrite', False):
        return
    orig = _ORIG_S3_INIT
    sig = inspect.signature(orig)

    @functools.wraps(orig)
    def rewritten_init(self, *args, **kwargs):
        bound = sig.bind(self, *args, **kwargs)
        a = bound.arguments
        for k in ('endpoint_url', 'db_url'):
            v = a.get(k)
            if isinstance(v, str) and v.startswith(PLACEHOLDER_ENDPOINT):
                a[k] = STATE.moto_url + v[len(PLACEHOLDER_ENDPOINT) :]
        for k in ('access_key_id', 'access_key'):
            if a.get(k) in PLACEHOLDER_KEYS:
                a[k] = 'test'
        with warnings.catch_warnings():
            # the moto URL is plain http by necessity; the docs' own URLs are https
            warnings.filterwarnings('ignore', message='db_url uses plain http', category=UserWarning)
            orig(*bound.args, **bound.kwargs)

    rewritten_init._docs_rewrite = True
    cls.__init__ = rewritten_init


def _remove_s3_rewrite():
    ebooklet.remote.S3Connection.__init__ = _ORIG_S3_INIT


# --- guards -----------------------------------------------------------------------------------

_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_getaddrinfo = socket.getaddrinfo


def _is_loopback(host) -> bool:
    if host is None:
        return True
    if isinstance(host, bytes):
        host = host.decode()
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == 'localhost'


def _guarded_getaddrinfo(host, *args, **kwargs):
    # A name lookup fails before any connect, so a placeholder host the rewrite missed
    # (s3.example.com) would otherwise never reach the connect guard.
    if not _is_loopback(host):
        STATE.violations.append(f'name lookup of {host!r}')
        msg = f'docs offline run: name lookup of {host!r} refused'
        raise socket.gaierror(msg)
    return _orig_getaddrinfo(host, *args, **kwargs)


def _offline_check(sock, address):
    if sock.family not in (socket.AF_INET, socket.AF_INET6):
        return
    if not _is_loopback(address[0]):
        STATE.violations.append(str(address))
        msg = f'docs offline run: network connection to {address} refused (use --docs-live)'
        raise OSError(msg)


def _guarded_connect(self, address):
    _offline_check(self, address)
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    _offline_check(self, address)
    return _orig_connect_ex(self, address)


def _set_socket_guard(*, on: bool):
    socket.socket.connect = _guarded_connect if on else _orig_connect
    socket.socket.connect_ex = _guarded_connect_ex if on else _orig_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo if on else _orig_getaddrinfo


_orig_data = cfdb.support_classes.DataVariableView.data


def _guarded_data(self):
    n = int(np.prod(self.shape, dtype='int64'))
    try:
        itemsize = np.dtype(self.dtype.dtype).itemsize
    except Exception:  # an unusual dtype: assume the widest
        itemsize = 8
    if n * itemsize > DATA_LIMIT_BYTES:
        msg = (
            f'docs test guard: .data would decode {n:,} values (~{n * itemsize / 1e9:.1f} GB, shape '
            f'{self.shape}); select a smaller part first'
        )
        raise MemoryError(msg)
    return _orig_data.fget(self)


def _set_data_guard(*, on: bool):
    cfdb.support_classes.DataVariableView.data = property(_guarded_data) if on else _orig_data


# Sybil's traceback filter takes element [1] of the cut traceback, so a chained exception (raised
# inside an except clause) whose traceback is one frame turns the report into a pytest INTERNALERROR
# that hides the real error. Fall back to the uncut traceback.
_orig_traceback_filter = getattr(sybil_pytest.SybilItem, '_traceback_filter', None)


def _safe_traceback_filter(self, excinfo):
    try:
        return _orig_traceback_filter(self, excinfo)
    except IndexError:
        return excinfo.traceback


if _orig_traceback_filter is not None:
    sybil_pytest.SybilItem._traceback_filter = _safe_traceback_filter


# --- per page ---------------------------------------------------------------------------------


def page_setup(namespace):
    STATE.pages_run += 1
    scratch = pathlib.Path(tempfile.mkdtemp(prefix='docs-page-'))
    user_dir = scratch / '.envlib' / 'vocabularies'
    page = {
        'scratch': scratch,
        'user_dir': user_dir,
        'cwd': os.getcwd(),
        'home': os.environ.get('HOME'),
        'orig_user_dir': vocabularies.USER_DIR,
        'module': f'_docs_page_{STATE.pages_run}',
        'violations': len(STATE.violations),
    }
    STATE.pages[id(namespace)] = page

    _ensure_moto()  # before the chdir/HOME change: the server outlives this page
    os.chdir(scratch)
    os.environ['HOME'] = str(scratch)
    vocabularies.USER_DIR = user_dir
    vocabularies.clear_cache()

    _reset_moto()
    _install_s3_rewrite()
    _set_data_guard(on=True)
    _set_socket_guard(on=not STATE.live)

    namespace['docs_live'] = STATE.live
    # Functions defined on a page must pickle by reference for map(n_workers=...): give the page an
    # importable module whose attributes are the page's names.
    module = types.ModuleType(page['module'])

    def _getattr(name, _ns=namespace):
        try:
            return _ns[name]
        except KeyError:
            raise AttributeError(name) from None

    module.__getattr__ = _getattr
    sys.modules[page['module']] = module
    namespace['__name__'] = page['module']


def page_teardown(namespace):
    page = STATE.pages.pop(id(namespace))
    problems = []

    # The canary: the isolation really was in force for this page.
    if os.environ.get('HOME') != str(page['scratch']) or vocabularies.USER_DIR != page['user_dir']:
        problems.append('page isolation was not in force (HOME or the vocabulary overlay was not the scratch dir)')

    gc.collect()
    # type(o), not isinstance(o): gc also holds weakref proxies, which raise once their referent dies.
    left_open = [o for o in gc.get_objects() if issubclass(type(o), cfdb.main.Dataset) and o.is_open]
    for ds in left_open:
        try:
            ds.close()
        except Exception as e:  # report, keep closing the rest
            problems.append(f'closing {ds.file_path} raised {type(e).__name__}: {e}')
    if left_open:
        problems.append(f'dataset(s) left open: {sorted(str(ds.file_path.name) for ds in left_open)}')

    new_violations = STATE.violations[page['violations'] :]
    if new_violations:
        problems.append(f'network connections attempted in an offline run: {new_violations}')

    _set_socket_guard(on=False)
    _set_data_guard(on=False)
    _remove_s3_rewrite()
    sys.modules.pop(page['module'], None)
    os.chdir(page['cwd'])
    if page['home'] is None:
        os.environ.pop('HOME', None)
    else:
        os.environ['HOME'] = page['home']
    vocabularies.USER_DIR = page['orig_user_dir']
    vocabularies.clear_cache()
    shutil.rmtree(page['scratch'], ignore_errors=True)

    if problems:
        raise AssertionError('; '.join(problems))


# --- builders for invisible blocks ------------------------------------------------------------
# State a reader is assumed to already have (their own file, their own connections).


def make_era5_temp(path='era5_temp_v1.cfdb'):
    """The gridded dataset built on the Producing Datasets page."""
    meta = {
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
    lats = np.arange(-44.0, -41.75, 0.25)
    lons = np.arange(170.0, 172.25, 0.25)
    times = np.arange('2020-01-01T00', '2020-01-02T00', dtype='datetime64[h]')
    with cfdb.open_dataset(path, flag='n') as ds:
        ds.create.coord.lat(data=lats)
        ds.create.coord.lon(data=lons)
        ds.create.coord.time(data=times, dtype=times.dtype)
        ds.create.crs.from_user_input(4326, x_coord='longitude', y_coord='latitude')
        dv = ds.create.data_var.generic('temperature', ('latitude', 'longitude', 'time'), dtype='float32')
        dv.attrs['units'] = 'degC'
        dv[:] = np.zeros((len(lats), len(lons), len(times)), dtype='float32')
        ds.attrs.update(Metadata(**meta).to_dict())
    return path


def s3_conns(db_key='datasets/era5_temp_v1.cfdb'):
    """A member and a catalogue connection, in the docs' placeholder form."""
    data_conn = ebooklet.S3Connection(
        access_key_id='...',
        access_key='...',
        bucket=BUCKET,
        endpoint_url=PLACEHOLDER_ENDPOINT,
        db_key=db_key,
        db_url=f'{PLACEHOLDER_ENDPOINT}/{BUCKET}/{db_key}',
    )
    rcg_conn = ebooklet.S3Connection(
        access_key_id='...',
        access_key='...',
        bucket=BUCKET,
        endpoint_url=PLACEHOLDER_ENDPOINT,
        db_key='catalogue.rcg',
    )
    return data_conn, rcg_conn
