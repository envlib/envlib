"""envlib Catalogue: RCG-backed dataset discovery, validation, publish/register/deregister.

The Catalogue wraps one or more ebooklet RemoteConnGroups (RCGs). Each RCG entry
is keyed by ``dataset_version_id`` and carries envlib's Identity/General/State/Provenance
metadata in ``user_meta`` (plain, unprefixed keys) plus the credential-free
member connection details. The cfdb file's ``ds.attrs`` (``envlib_``-prefixed)
is the authoritative metadata store; RCG entries are a derived index.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import urllib.parse
import warnings
from hashlib import blake2b

import booklet
import cfdb
import ebooklet
import pyproj
import shapely
import urllib3

from envlib import vocabularies
from envlib.metadata import (
    GENERAL_FIELDS,
    IDENTITY_FIELDS,
    Metadata,
    ValidationError,
    compute_station_id,
)

# The hardcoded public RCG URL. None until the public commons is hosted —
# overridable (and currently only usable) via the env var below.
PUBLIC_RCG_URL: str | None = None
PUBLIC_RCG_ENV_VAR = 'ENVLIB_PUBLIC_RCG_URL'
DEFAULT_CACHE_DIR = '~/.envlib/cache'

STATION_ID_VAR = 'station_id'

_HEX24_RE = re.compile(r'[0-9a-f]{24}')
_EPSG_4326 = pyproj.CRS.from_epsg(4326)
_FULL_CIRCLE_DEG = 360.0

_QUERYABLE_FIELDS = frozenset(IDENTITY_FIELDS) | {'license', 'dataset_type', 'dataset_version_id', 'dataset_id'}

# Errors that indicate the remote endpoint is unreachable (offline), as opposed
# to a well-formed remote answer like 404: urllib3 raises MaxRetryError and
# friends (all HTTPError subclasses) on DNS/connect/timeout failures.
_OFFLINE_ERRORS = (urllib3.exceptions.HTTPError, ConnectionError, TimeoutError)


def _public_rcg_url() -> str | None:
    return os.environ.get(PUBLIC_RCG_ENV_VAR) or PUBLIC_RCG_URL


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _dt64_to_iso(value) -> str:
    """numpy datetime64 (UTC by convention) -> ISO8601 Z string.

    Whole-second when there is no sub-second component, otherwise a fractional
    suffix with trailing zeros stripped. Sub-microsecond precision truncates.
    """
    micros = int(value.astype('datetime64[us]').astype('int64'))
    dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(microseconds=micros)
    if dt.microsecond == 0:
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    frac = f'{dt.microsecond:06d}'.rstrip('0')
    return dt.strftime('%Y-%m-%dT%H:%M:%S') + f'.{frac}Z'


def _parse_iso(value) -> datetime.datetime:
    """Parse an ISO8601 string (Z-suffixed or naive-as-UTC) or pass a datetime through."""
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        dt = datetime.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _as_connection(remote_conn) -> ebooklet.S3Connection:
    if isinstance(remote_conn, ebooklet.S3Connection):
        return remote_conn
    if isinstance(remote_conn, dict):
        return ebooklet.S3Connection(**remote_conn)
    if isinstance(remote_conn, str):
        return ebooklet.S3Connection(db_url=remote_conn)
    msg = f'remote_conn must be an ebooklet.S3Connection, dict, or URL str, not {type(remote_conn).__name__}.'
    raise TypeError(msg)


def _conn_cache_key(remote_conn) -> str:
    if isinstance(remote_conn, str):
        key = remote_conn
    else:
        conn = _as_connection(remote_conn)
        key = f'{conn.endpoint_url}|{conn.bucket}|{conn.db_key}|{conn.db_url}'
    return blake2b(key.encode('utf-8'), digest_size=8).hexdigest()


def _validate_data_url(db_url) -> str | None:
    """Validate a member db_url as a plain public http(s) URL for the catalogue entry.

    No userinfo (user:pass@) and no query string — a presigned URL's signature
    must never ride into the public catalogue. Returns None when db_url is None.
    """
    if db_url is None:
        return None
    parsed = urllib.parse.urlsplit(db_url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        msg = f'data_url must be a plain http(s) URL; got {db_url!r}.'
        raise ValidationError(msg)
    if parsed.username is not None or parsed.password is not None:
        msg = f'data_url must not carry userinfo (user:pass@); got {db_url!r}.'
        raise ValidationError(msg)
    if parsed.query:
        msg = f'data_url must not carry a query string (presigned URLs are not public URLs); got {db_url!r}.'
        raise ValidationError(msg)
    return db_url


###################################################
# bbox helpers (EPSG:4326, GeoJSON antimeridian convention: min_lon > max_lon
# means the box crosses 180°)


def _wrap_lon(lon: float) -> float:
    half_circle = _FULL_CIRCLE_DEG / 2
    wrapped = ((lon + half_circle) % _FULL_CIRCLE_DEG) - half_circle
    # keep the east edge at +180 rather than wrapping it to -180
    if wrapped == -half_circle and lon > 0:
        return half_circle
    return wrapped


def _wrap_lon_extent(west: float, east: float, x_step: float | None) -> tuple:
    """Wrap a native-geographic lon extent into [-180, 180] preserving crossing structure.

    A full-circle source (e.g. ERA5 cell centers 0..359.75 with 0.25 step)
    stores [-180, 180]; a regional 170..190 grid stores (170, -170) — the
    crossing convention — NOT the naive min/max of the wrapped corners.
    """
    span = east - west + (x_step or 0.0)
    if span >= _FULL_CIRCLE_DEG - 1e-9:
        return -180.0, 180.0
    w = _wrap_lon(west)
    e = _wrap_lon(east)
    return w, e


def _split_bbox(bbox) -> list:
    """Split an antimeridian-crossing bbox into 1-2 conventional boxes."""
    min_lon, min_lat, max_lon, max_lat = bbox
    if min_lon > max_lon:
        return [(min_lon, min_lat, 180.0, max_lat), (-180.0, min_lat, max_lon, max_lat)]
    return [(min_lon, min_lat, max_lon, max_lat)]


def _boxes_intersect(a, b) -> bool:
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _bbox_intersects(stored, query) -> bool:
    return any(_boxes_intersect(s, q) for s in _split_bbox(stored) for q in _split_bbox(query))


def _geometry_intersects(stored, geometry) -> bool:
    return any(shapely.box(*part).intersects(geometry) for part in _split_bbox(stored))


_GEOD = pyproj.Geod(ellps='WGS84')


def _bbox_within_radius(stored, lon: float, lat: float, radius_km: float) -> bool:
    """Great-circle distance from a point to the nearest edge/corner of the bbox.

    Longitude candidates at ±360 handle proximity across the antimeridian
    (clamping in linear lon space alone would pick the wrong side).
    """
    for min_lon, min_lat, max_lon, max_lat in _split_bbox(stored):
        near_lat = min(max(lat, min_lat), max_lat)
        for cand in (lon, lon - 360.0, lon + 360.0):
            near_lon = min(max(cand, min_lon), max_lon)
            _, _, dist_m = _GEOD.inv(cand, lat, near_lon, near_lat)
            if dist_m <= radius_km * 1000.0:
                return True
    return False


###################################################
# Dataset validation + State Metadata extraction


def _sys_dataset_type(ds) -> str:
    # cfdb 0.9.0 has no public dataset_type property (and open_edataset always
    # returns the EGrid class), so the sys-metadata slot is the reliable source.
    return ds._sys_meta.dataset_type.value


def _coord_by_axis(ds, axis: str):
    for coord in ds.coords:
        ax = coord.axis
        if ax is not None and ax.value == axis:
            return coord
    return None


def _reproject_points(points, crs) -> list:
    if crs.equals(_EPSG_4326):
        return list(points)
    transformer = pyproj.Transformer.from_crs(crs, _EPSG_4326, always_xy=True)
    out = []
    for p in points:
        x, y = transformer.transform(p.x, p.y)
        out.append(shapely.Point(x, y))
    return out


def _extract_state(ds, meta: Metadata) -> dict:
    """Extract State Metadata (bbox, time range, steps, dataset_type) from an open dataset."""
    dataset_type = _sys_dataset_type(ds)
    crs = ds.crs

    time_coord = ds.get('time') if 'time' in ds.coord_names else None
    if time_coord is None or len(time_coord.data) == 0:
        msg = 'every envlib dataset must have a time coordinate with at least one value.'
        raise ValidationError(msg)
    if time_coord.dtype.kind != 'M':
        msg = f'the time coordinate must be datetime64, not {time_coord.dtype.name!r}.'
        raise ValidationError(msg)
    time_values = time_coord.data
    state: dict = {
        'dataset_type': dataset_type,
        'time_start': _dt64_to_iso(time_values[0]),
        'time_end': _dt64_to_iso(time_values[-1]),
    }

    x_step = y_step = None
    if dataset_type == 'grid':
        x_coord = _coord_by_axis(ds, 'x')
        y_coord = _coord_by_axis(ds, 'y')
        if x_coord is None or y_coord is None:
            msg = 'grid datasets must have x and y axis coordinates (set via create.crs.from_user_input).'
            raise ValidationError(msg)
        x_data = x_coord.data
        y_data = y_coord.data
        if len(x_data) == 0 or len(y_data) == 0:
            msg = 'grid x/y coordinates must be non-empty.'
            raise ValidationError(msg)
        west, east = float(x_data.min()), float(x_data.max())
        south, north = float(y_data.min()), float(y_data.max())
        if x_coord.step is not None:
            x_step = float(x_coord.step)
        if y_coord.step is not None:
            y_step = float(y_coord.step)
    else:
        geom_coord = _geometry_coord(ds)
        points = geom_coord.data
        if len(points) == 0:
            msg = 'ts_ortho datasets must have at least one station point.'
            raise ValidationError(msg)
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        west, east = float(min(xs)), float(max(xs))
        south, north = float(min(ys)), float(max(ys))

    if crs.is_geographic:
        # native-geographic source: transform_bounds is an identity no-op for
        # longitude conventions, so apply envlib's own structure-preserving
        # wrap (0-360 grids -> [-180, 180] / the crossing convention).
        if not crs.equals(_EPSG_4326):
            transformer = pyproj.Transformer.from_crs(crs, _EPSG_4326, always_xy=True)
            west, south, east, north = transformer.transform_bounds(west, south, east, north, densify_pts=21)
        min_lon, max_lon = _wrap_lon_extent(west, east, x_step)
        min_lat, max_lat = south, north
    else:
        transformer = pyproj.Transformer.from_crs(crs, _EPSG_4326, always_xy=True)
        min_lon, min_lat, max_lon, max_lat = transformer.transform_bounds(west, south, east, north, densify_pts=21)

    state['bbox'] = [min_lon, min_lat, max_lon, max_lat]
    if x_step is not None:
        state['x_step'] = x_step
    if y_step is not None:
        state['y_step'] = y_step

    # identity cross-checks that involve state
    if dataset_type == 'ts_ortho' and meta.spatial_resolution != 'point':
        msg = "ts_ortho datasets must use spatial_resolution='point'."
        raise ValidationError(msg)
    return state


def _geometry_coord(ds):
    coord = _coord_by_axis(ds, 'xy')
    if coord is None:
        msg = (
            "ts_ortho datasets must have a point geometry coordinate with the 'xy' axis "
            '(create.coord.point + create.crs.from_user_input(xy_coord=...)).'
        )
        raise ValidationError(msg)
    if coord.dtype.kind != 'G':
        msg = f'the xy coordinate {coord.name!r} is not a geometry coordinate.'
        raise ValidationError(msg)
    return coord


def _check_stations(ds):
    """ts_ortho: station_id attribute variable must exist and match recomputation."""
    geom_coord = _geometry_coord(ds)
    if STATION_ID_VAR not in ds.data_var_names:
        msg = f'ts_ortho datasets must carry a {STATION_ID_VAR!r} station attribute variable (shape (geometry,)).'
        raise ValidationError(msg)
    sid_var = ds[STATION_ID_VAR]
    if tuple(sid_var.coord_names) != (geom_coord.name,):
        msg = (
            f'{STATION_ID_VAR!r} must be aligned to the geometry coordinate '
            f'({geom_coord.name!r},); got {tuple(sid_var.coord_names)}.'
        )
        raise ValidationError(msg)
    points = _reproject_points(geom_coord.data, ds.crs)
    expected = [compute_station_id(p) for p in points]
    stored = [str(v) for v in sid_var.data]
    if stored != expected:
        first_bad = next(i for i, (s, e) in enumerate(zip(stored, expected, strict=True)) if s != e)
        msg = (
            f'{STATION_ID_VAR!r} values do not match the envlib derivation (first mismatch at index '
            f'{first_bad}: stored {stored[first_bad]!r}, derived {expected[first_bad]!r}). '
            f'Use envlib.compute_station_id on the EPSG:4326 station points.'
        )
        raise ValidationError(msg)


def _decide_standard_name(ds, meta: Metadata) -> dict:
    """Decide the standard_name action for the primary variable (never writes).

    Returns {'action': 'keep'|'populate'|'absent'|'uncurated', 'value': str|None}.
    """
    dv = ds[meta.variable]
    current = dv.attrs.get('standard_name')
    if current is not None:
        if not vocabularies.is_valid('standard_name', current):
            msg = f'standard_name {current!r} on {meta.variable!r} is not a valid CF standard name.'
            raise ValidationError(msg)
        return {'action': 'keep', 'value': current}
    try:
        candidates = vocabularies.get_cf_standard_names(meta.variable, meta.feature)
    except ValueError:
        candidates = None  # variable/feature not in the current vocabulary (drift) -> treat as uncurated
    if candidates is None:
        warnings.warn(
            f'({meta.variable!r}, {meta.feature!r}) has no curated CF standard_name mapping yet; '
            f'standard_name left unset. Set it explicitly if a CF name applies.',
            stacklevel=3,
        )
        return {'action': 'uncurated', 'value': None}
    if not candidates:
        return {'action': 'absent', 'value': None}  # curated: no applicable standard name
    return {'action': 'populate', 'value': candidates[0]}


def _validate_dataset(ds, *, validate_cv: bool) -> dict:
    """Validate an open cfdb dataset against envlib requirements; extract everything.

    Returns {'metadata', 'dataset_version_id', 'dataset_id', 'state', 'standard_name'}.
    Raises ValidationError on any failure. Never modifies the dataset.
    """
    meta = Metadata.from_attrs(ds.attrs, validate_cv=validate_cv)
    missing = meta.missing_fields()
    if missing:
        msg = f'dataset attrs are missing required envlib metadata fields: {missing}.'
        raise ValidationError(msg)

    if ds.crs is None:
        msg = 'every envlib dataset must have a CRS (ds.create.crs.from_user_input(...)).'
        raise ValidationError(msg)

    if meta.variable not in ds.data_var_names:
        msg = (
            f'the primary data variable must be named after Metadata.variable '
            f'({meta.variable!r}); data variables present: {list(ds.data_var_names)}.'
        )
        raise ValidationError(msg)
    dv = ds[meta.variable]
    units = dv.attrs.get('units') or dv.units
    if not units:
        msg = f'the primary data variable {meta.variable!r} must carry a units attribute.'
        raise ValidationError(msg)

    ancillary = dv.attrs.get('ancillary_variables')
    if ancillary:
        for name in str(ancillary).split():
            if name not in ds.data_var_names:
                msg = f'declared ancillary variable {name!r} is not a data variable in the dataset.'
                raise ValidationError(msg)

    if _sys_dataset_type(ds) == 'ts_ortho':
        _check_stations(ds)

    state = _extract_state(ds, meta)
    standard_name = _decide_standard_name(ds, meta)

    return {
        'metadata': meta,
        'dataset_version_id': meta.dataset_version_id,
        'dataset_id': meta.dataset_id,
        'state': state,
        'standard_name': standard_name,
    }


def _apply_derived_attrs(ds, result: dict) -> bool:
    """Write self-identification ids + the auto-populated standard_name. Returns True if anything changed."""
    changed = False
    meta = result['metadata']
    id_attrs = (
        ('envlib_dataset_version_id', result['dataset_version_id']),
        ('envlib_dataset_id', result['dataset_id']),
    )
    for key, value in id_attrs:
        if ds.attrs.get(key) != value:
            ds.attrs[key] = value
            changed = True
    sn = result['standard_name']
    if sn['action'] == 'populate':
        dv = ds[meta.variable]
        if dv.attrs.get('standard_name') != sn['value']:
            dv.attrs['standard_name'] = sn['value']
            changed = True
    return changed


###################################################
# DatasetRef


class DatasetRef:
    """A catalogue entry: metadata plus how to open the dataset."""

    def __init__(self, dataset_version_id: str, entry: dict, cache_dir: pathlib.Path):
        self._dataset_id = dataset_version_id
        self._entry = entry
        self._cache_dir = cache_dir

    @property
    def metadata(self) -> dict:
        """The full envlib metadata dict stored in the catalogue entry."""
        return dict(self._entry.get('user_meta') or {})

    @property
    def entry(self) -> dict:
        """The raw RCG entry (entry schema v1: remote_conn, remote_meta, user_meta, ...)."""
        return self._entry

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        user_meta = self._entry.get('user_meta') or {}
        if name in user_meta:
            return user_meta[name]
        msg = f'{type(self).__name__} has no attribute or metadata field {name!r}.'
        raise AttributeError(msg)

    def __repr__(self):
        return repr(self.metadata)

    def open(self, file_path=None, access_key_id=None, access_key=None):
        """Open the dataset as a cfdb EDataset (read-only).

        Entries never store credentials. Public-HTTPS datasets open via their
        ``data_url`` with no credentials; for private buckets inject
        ``access_key_id``/``access_key``. Only inject credentials for entries
        whose endpoint/bucket you trust — injected keys sign requests against
        the entry's stored endpoint.
        """
        conn_dict = dict(self._entry.get('remote_conn') or {})
        if access_key_id is not None or access_key is not None:
            conn_dict['access_key_id'] = access_key_id
            conn_dict['access_key'] = access_key
        elif not conn_dict.get('db_url'):
            msg = (
                'this entry has no public db_url; the dataset lives on a private bucket — '
                'inject access_key_id/access_key to open it.'
            )
            raise ValidationError(msg)
        else:
            # url-only read session; drop the S3 fields so no signing is attempted
            conn_dict = {'db_url': conn_dict['db_url']}
        conn = ebooklet.S3Connection(**conn_dict)
        if file_path is None:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            file_path = self._cache_dir / f'{self._dataset_id}.cfdb'
        return cfdb.open_edataset(conn, file_path, flag='r')


###################################################
# Catalogue


class Catalogue:
    """RCG-backed catalogue of envlib datasets.

    ``Catalogue()`` connects to the public envlib RCG (read-only). Pass
    ``remotes=[...]`` (S3Connection | dict | URL str) to use your own RCGs —
    this replaces the public default unless ``include_public=True``.

    The catalogue snapshots all entries at construction; call :meth:`refresh`
    to re-pull after new registrations. When a remote is unreachable and a
    previously pulled local index exists, the catalogue degrades to the cached
    copy (with a warning) instead of failing.
    """

    def __init__(self, remotes=None, cache: str = DEFAULT_CACHE_DIR, *, include_public: bool = False):
        self._cache_dir = pathlib.Path(cache).expanduser()
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        sources = []
        if remotes is None:
            public = _public_rcg_url()
            if public is None:
                msg = (
                    'the public envlib RCG is not hosted yet — pass remotes=[...] '
                    f'or set the {PUBLIC_RCG_ENV_VAR} environment variable.'
                )
                raise ValueError(msg)
            sources.append(public)
        else:
            if isinstance(remotes, (ebooklet.S3Connection, str, dict)):
                remotes = [remotes]
            sources.extend(remotes)
            if include_public:
                public = _public_rcg_url()
                if public is None:
                    msg = f'include_public=True but no public RCG is configured ({PUBLIC_RCG_ENV_VAR}).'
                    raise ValueError(msg)
                sources.append(public)
        self._sources = sources
        self._entries: dict = {}
        self.refresh()

    # -- index management ----------------------------------------------------

    def _rcg_cache_path(self, source) -> pathlib.Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        return self._cache_dir / f'{_conn_cache_key(source)}.rcg'

    def refresh(self):
        """Re-pull the RCG index from all configured remotes."""
        entries: dict = {}
        for source in self._sources:
            path = self._rcg_cache_path(source)
            try:
                with ebooklet.open_rcg(source, path, flag='r') as rcg:
                    source_entries = {k: v for k, v in rcg.items() if _HEX24_RE.fullmatch(str(k))}
            except ValueError as err:
                # ebooklet raises ValueError when the RCG does not exist on the
                # remote yet (and no local copy exists) — the bootstrap case: a
                # producer constructs the Catalogue before the first publish
                # creates the RCG. Treat as an empty source, loudly.
                warnings.warn(f'RCG source not readable yet ({err}); treating as empty.', stacklevel=2)
                source_entries = {}
            except _OFFLINE_ERRORS as err:
                if not path.exists():
                    raise
                warnings.warn(
                    f'RCG remote unreachable ({err!r}); operating offline from the cached index at {path}.',
                    stacklevel=2,
                )
                source_entries = _read_cached_index(path)
            for key, entry in source_entries.items():
                entries.setdefault(key, entry)  # first configured source wins on duplicates
        self._entries = entries

    @property
    def datasets(self) -> list:
        """All catalogue entries as DatasetRef objects."""
        return [DatasetRef(key, entry, self._cache_dir) for key, entry in self._entries.items()]

    # -- value discovery -------------------------------------------------------

    def distinct(self, field: str, *, counts: bool = False):
        """Distinct stored values of a queryable field across the catalogue.

        The browse companion to :meth:`query`: ``cat.distinct('variable')``
        tells you what is actually *in* this catalogue (the vocabularies module
        lists what is *valid*, and can't help at all for the free-form fields
        ``owner``/``product_code``/``version``).

        Args:
            field: Any queryable field (identity fields, ``license``,
                ``dataset_type``, ...).
            counts: When False (default), return a sorted list of the distinct
                values, excluding None. When True, return a ``{value: count}``
                dict that DOES include a None key when some entries lack the
                field (e.g. datasets with no ``product_code``).
        """
        if field not in _QUERYABLE_FIELDS:
            msg = f'unknown field {field!r}; queryable fields are {sorted(_QUERYABLE_FIELDS)}.'
            raise ValueError(msg)
        tally: dict = {}
        for entry in self._entries.values():
            value = (entry.get('user_meta') or {}).get(field)
            tally[value] = tally.get(value, 0) + 1
        if counts:
            return dict(sorted(tally.items(), key=lambda kv: (kv[0] is None, str(kv[0]))))
        return sorted(v for v in tally if v is not None)

    @property
    def features(self) -> list:
        """Distinct feature values present in the catalogue (sorted)."""
        return self.distinct('feature')

    @property
    def variables(self) -> list:
        """Distinct variable values present in the catalogue (sorted)."""
        return self.distinct('variable')

    @property
    def methods(self) -> list:
        """Distinct method values present in the catalogue (sorted)."""
        return self.distinct('method')

    @property
    def product_codes(self) -> list:
        """Distinct product_code values present in the catalogue (sorted; None excluded — see distinct())."""
        return self.distinct('product_code')

    @property
    def processing_levels(self) -> list:
        """Distinct processing_level values present in the catalogue (sorted)."""
        return self.distinct('processing_level')

    @property
    def owners(self) -> list:
        """Distinct owner values present in the catalogue (sorted)."""
        return self.distinct('owner')

    @property
    def aggregation_statistics(self) -> list:
        """Distinct aggregation_statistic values present in the catalogue (sorted)."""
        return self.distinct('aggregation_statistic')

    @property
    def frequency_intervals(self) -> list:
        """Distinct frequency_interval codes present in the catalogue (sorted; None excluded)."""
        return self.distinct('frequency_interval')

    @property
    def utc_offsets(self) -> list:
        """Distinct utc_offset values present in the catalogue (sorted)."""
        return self.distinct('utc_offset')

    @property
    def spatial_resolutions(self) -> list:
        """Distinct spatial_resolution values present in the catalogue (sorted; None excluded)."""
        return self.distinct('spatial_resolution')

    @property
    def versions(self) -> list:
        """Distinct version strings present in the catalogue (sorted).

        Version spellings are per-dataset conventions, so this global list
        mixes unrelated series — mostly useful after narrowing with query().
        """
        return self.distinct('version')

    @property
    def licenses(self) -> list:
        """Distinct license values present in the catalogue (sorted)."""
        return self.distinct('license')

    @property
    def dataset_types(self) -> list:
        """Distinct dataset_type values present in the catalogue (sorted)."""
        return self.distinct('dataset_type')

    # -- query ----------------------------------------------------------------

    def query(
        self,
        *,
        bbox=None,
        within_radius=None,
        geometry=None,
        start_date=None,
        end_date=None,
        **fields,
    ) -> list:
        """Filter the catalogue; kwargs are AND'd, a list value means any-of.

        Spatial filters (mutually exclusive, EPSG:4326): ``bbox`` (intersects),
        ``within_radius`` (((lon, lat), km) great-circle), ``geometry``
        (shapely, intersects). Temporal: ``start_date``/``end_date`` overlap
        the dataset's time range. Without an explicit ``version=`` kwarg the
        latest version (greatest created_at) of each matching dataset is
        returned.
        """
        unknown = set(fields) - _QUERYABLE_FIELDS
        if unknown:
            msg = f'unknown query fields: {sorted(unknown)}; queryable fields are {sorted(_QUERYABLE_FIELDS)}.'
            raise ValueError(msg)
        spatial_kwargs = (('bbox', bbox), ('within_radius', within_radius), ('geometry', geometry))
        spatial = [kw for kw, v in spatial_kwargs if v is not None]
        if len(spatial) > 1:
            msg = f'spatial filters are mutually exclusive; got {spatial}.'
            raise ValueError(msg)

        results = []
        for ref in self.datasets:
            user_meta = ref.metadata
            if not all(_field_matches(user_meta.get(name), wanted) for name, wanted in fields.items()):
                continue
            stored_bbox = user_meta.get('bbox')
            if bbox is not None and (stored_bbox is None or not _bbox_intersects(stored_bbox, bbox)):
                continue
            if geometry is not None and (stored_bbox is None or not _geometry_intersects(stored_bbox, geometry)):
                continue
            if within_radius is not None:
                (lon, lat), radius_km = within_radius
                if stored_bbox is None or not _bbox_within_radius(stored_bbox, lon, lat, radius_km):
                    continue
            if (start_date is not None or end_date is not None) and not _time_overlaps(
                user_meta.get('time_start'), user_meta.get('time_end'), start_date, end_date
            ):
                continue
            results.append(ref)

        if 'version' not in fields:
            results = _latest_per_dataset(results)
        return results

    # -- validate / publish / register / deregister ---------------------------

    def validate(self, local_cfdb_path) -> dict:
        """Validate a local cfdb file against envlib's requirements (no RCG or S3 changes).

        Returns a summary dict ({'metadata', 'dataset_version_id', 'dataset_id', 'state',
        'standard_name'}); raises ValidationError on invalid input.
        """
        with cfdb.open_dataset(local_cfdb_path) as ds:
            return _validate_dataset(ds, validate_cv=True)

    def publish(self, local_cfdb_path, remote_conn, rcg_remote_conn, num_groups=None, **open_kwargs) -> dict:
        """Validate, push the cfdb data to its S3 remote, then register it in the RCG.

        The cfdb data is pushed BEFORE the RCG entry so the catalogue never
        references incomplete remote data. Re-running after a partial failure
        is safe (the push is idempotent; the entry write is an upsert).
        """
        member_conn = _as_connection(remote_conn)
        edataset_kwargs = dict(open_kwargs)
        if num_groups is not None:
            edataset_kwargs['num_groups'] = num_groups
        # validate INSIDE the edataset session: for a re-publish of an
        # already-pushed (possibly partially materialized) local file, plain
        # open_dataset would read local chunks only and could extract wrong
        # extents; the EDataset pulls transparently. A ValidationError aborts
        # before anything is pushed.
        with cfdb.open_edataset(member_conn, local_cfdb_path, flag='w', **edataset_kwargs) as eds:
            # attrs carrying a dataset_version_id mean this dataset was validated/registered
            # before: skip CV re-validation (validation on change only).
            first_time = eds.attrs.get('envlib_dataset_version_id') is None
            result = _validate_dataset(eds, validate_cv=first_time)
            _apply_derived_attrs(eds, result)
            eds.push()

        self._upsert_entry(rcg_remote_conn, member_conn, result)
        return result

    def register(self, remote_conn, rcg_remote_conn, **open_kwargs) -> dict:
        """Register an already-remote cfdb dataset in the catalogue (no data push).

        ``remote_conn`` must be writable (credentials): first registration
        writes the self-identification attrs (and any auto-populated
        standard_name) into the dataset, pushing that metadata-only change.
        """
        member_conn = _as_connection(remote_conn)
        local_path = self._cache_dir / f'{_conn_cache_key(member_conn)}.cfdb'
        with cfdb.open_edataset(member_conn, local_path, flag='w', **open_kwargs) as eds:
            first_time = eds.attrs.get('envlib_dataset_version_id') is None
            result = _validate_dataset(eds, validate_cv=first_time)
            if _apply_derived_attrs(eds, result):
                eds.push()

        self._upsert_entry(rcg_remote_conn, member_conn, result)
        return result

    def deregister(
        self,
        dataset_version_id: str,
        rcg_remote_conn,
        *,
        delete_data: bool = False,
        access_key_id=None,
        access_key=None,
    ):
        """Remove a dataset's catalogue entry; optionally delete the hosted data.

        Plain deregistration only delists — the hosted data stays up for
        existing consumers. ``delete_data=True`` (retraction) additionally
        deletes the remote cfdb via ebooklet, after verifying no OTHER entry
        references the same remote target (the shared-target guard); it needs
        the data owner's credentials injected.
        """
        rcg_conn = _as_connection(rcg_remote_conn)
        with ebooklet.open_rcg(rcg_conn, self._rcg_cache_path(rcg_conn), flag='w') as rcg:
            entry = rcg.get(dataset_version_id)
            if entry is None:
                msg = f'no catalogue entry for dataset_version_id {dataset_version_id!r}.'
                raise ValidationError(msg)
            if delete_data:
                target_conn = entry.get('remote_conn') or {}
                target = (target_conn.get('endpoint_url'), target_conn.get('bucket'), target_conn.get('db_key'))
                # list() first: fetching entries while iterating keys() would
                # deadlock on the underlying booklet thread lock (see
                # _read_cached_index).
                for other_key in list(rcg.keys()):
                    if other_key == dataset_version_id or not _HEX24_RE.fullmatch(str(other_key)):
                        continue
                    other = rcg.get(other_key) or {}
                    other_conn = other.get('remote_conn') or {}
                    if (other_conn.get('endpoint_url'), other_conn.get('bucket'), other_conn.get('db_key')) == target:
                        msg = (
                            f'refusing delete_data=True: entry {other_key!r} references the same remote '
                            f'target ({target[2]!r} in bucket {target[1]!r}); deleting would destroy its data. '
                            f'Deregister without delete_data, or resolve the shared target first.'
                        )
                        raise ValidationError(msg)
                if access_key_id is None or access_key is None:
                    msg = 'delete_data=True needs the data owner credentials (access_key_id/access_key).'
                    raise ValidationError(msg)
                member_conn = ebooklet.S3Connection(
                    access_key_id=access_key_id,
                    access_key=access_key,
                    db_key=target_conn.get('db_key'),
                    bucket=target_conn.get('bucket'),
                    endpoint_url=target_conn.get('endpoint_url'),
                )
                with member_conn.open('w') as session:
                    session.delete_remote()
            del rcg[dataset_version_id]
            rcg.changes().push()
        self.refresh()

    # -- entry construction ----------------------------------------------------

    def _upsert_entry(self, rcg_remote_conn, member_conn: ebooklet.S3Connection, result: dict):
        rcg_conn = _as_connection(rcg_remote_conn)
        dataset_version_id = result['dataset_version_id']
        with ebooklet.open_rcg(rcg_conn, self._rcg_cache_path(rcg_conn), flag='c') as rcg:
            existing = rcg.get(dataset_version_id)
            existing_meta = (existing or {}).get('user_meta') or {}
            now = _utc_now_iso()
            user_meta = _build_user_meta(result, member_conn)
            user_meta['created_at'] = existing_meta.get('created_at') or now

            comparable_new = {k: v for k, v in user_meta.items() if k != 'modified_at'}
            comparable_old = {k: v for k, v in existing_meta.items() if k != 'modified_at'}
            stored_conn = (existing or {}).get('remote_conn') or {}
            conn_changed = stored_conn != member_conn.to_dict()
            if existing is not None and comparable_new == comparable_old and not conn_changed:
                return  # true no-op: do not bump modified_at, do not push

            user_meta['modified_at'] = now
            rcg.add(member_conn, key=dataset_version_id, user_meta=user_meta)
            rcg.changes().push()
        self.refresh()


def _build_user_meta(result: dict, member_conn: ebooklet.S3Connection) -> dict:
    meta = result['metadata']
    values = {f: getattr(meta, f) for f in IDENTITY_FIELDS}
    user_meta = dict(values)
    for f in GENERAL_FIELDS:
        value = getattr(meta, f)
        if value is not None:
            user_meta[f] = value
    user_meta['dataset_version_id'] = result['dataset_version_id']
    user_meta['dataset_id'] = result['dataset_id']
    user_meta.update(result['state'])
    user_meta['data_url'] = _validate_data_url(member_conn.db_url)
    sn = result['standard_name']
    if sn['value'] is not None:
        user_meta['standard_name'] = sn['value']
    return user_meta


###################################################
# query helpers


def _field_matches(stored, wanted) -> bool:
    if isinstance(wanted, (list, tuple, set)):
        return any(_field_matches(stored, w) for w in wanted)
    if wanted is None:
        return stored is None
    if stored is None:
        return False
    return str(stored).lower() == str(wanted).strip().lower()


def _time_overlaps(time_start, time_end, start_date, end_date) -> bool:
    if time_start is None or time_end is None:
        return False
    t0 = _parse_iso(time_start)
    t1 = _parse_iso(time_end)
    if start_date is not None and t1 < _parse_iso(start_date):
        return False
    return not (end_date is not None and t0 > _parse_iso(end_date))


def _latest_per_dataset(refs: list) -> list:
    by_dataset: dict = {}
    no_dataset_id = []
    for ref in refs:
        user_meta = ref.metadata
        dataset_id = user_meta.get('dataset_id')
        if dataset_id is None:
            no_dataset_id.append(ref)
            continue
        current = by_dataset.get(dataset_id)
        if current is None or _created_at(ref) > _created_at(current):
            by_dataset[dataset_id] = ref
    return list(by_dataset.values()) + no_dataset_id


def _created_at(ref: DatasetRef) -> datetime.datetime:
    value = ref.metadata.get('created_at')
    if value is None:
        return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    return _parse_iso(value)


def _read_cached_index(path: pathlib.Path) -> dict:
    """Offline fallback: read a previously pulled RCG index directly with booklet.

    Booklet files are self-describing (serializers stored in-file), so entries
    decode without parameters. envlib entries are keyed by 24-hex dataset_ids;
    everything else (ebooklet-internal keys) is skipped. Values that fail to
    decode as entry dicts are skipped too.
    """
    entries: dict = {}
    with booklet.open(path, 'r') as blt:
        # materialize keys() BEFORE fetching: booklet's keys() generator holds
        # the file's thread lock across yields, so a get() inside the loop
        # deadlocks (single-threaded) — found via the hung offline test.
        for key in list(blt.keys()):
            key_str = key.decode() if isinstance(key, bytes) else str(key)
            if not _HEX24_RE.fullmatch(key_str):
                continue
            try:
                value = blt[key]
            except (KeyError, ValueError):
                continue
            if isinstance(value, bytes):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            if isinstance(value, dict) and 'remote_conn' in value:
                entries[key_str] = value
    return entries
