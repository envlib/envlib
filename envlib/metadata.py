"""envlib dataset metadata: validation, normalization, and identity hashing.

Implements the Identity/General metadata model from ``plans/architecture_plan.md``.
The serialization rules in :func:`compute_dataset_id` / :func:`compute_dataset_version_id` /
:func:`compute_station_id` are permanent public contracts — changing any aspect of
them (field order, the ``"None"`` sentinel, the ``\\x1f`` delimiter, the UTF-8
encoding, the keyless blake2b construction, the digest size, the WKB byte order,
the signed-zero normalization) would fork every existing id. Do not change them.
"""

from __future__ import annotations

import math
import re
from hashlib import blake2b
from typing import cast

import shapely
from shapely import wkt

from envlib import vocabularies

# Hash-internal field order — MUST NOT change (user-facing display order is free to differ).
IDENTITY_FIELDS = (
    'feature',
    'variable',
    'method',
    'product_code',
    'processing_level',
    'owner',
    'aggregation_statistic',
    'frequency_interval',
    'utc_offset',
    'spatial_resolution',
    'version',
)
GENERAL_FIELDS = ('license', 'attribution', 'description', 'derived_from', 'doi')

# Identity fields for which None is a legitimate value (not "unset").
NULLABLE_IDENTITY_FIELDS = frozenset({'product_code', 'frequency_interval', 'spatial_resolution'})

# Fields whose canonical value comes from a controlled vocabulary that can drift
# across vocabulary refreshes — validated on change only, never on re-read.
_CV_FIELDS = frozenset(
    {'feature', 'variable', 'method', 'processing_level', 'aggregation_statistic', 'frequency_interval', 'license'}
)

ATTR_PREFIX = 'envlib_'

ID_HEX_LEN = 24  # blake2b(digest_size=12).hexdigest()

_SLUG_RE = re.compile(r'[a-z0-9._-]+')
_SLUG_ALNUM_RE = re.compile(r'[a-z0-9]')
_UTC_OFFSET_RE = re.compile(r'([+-])([0-9]{2}):([0-9]{2})')
_UTC_OFFSET_SHORTHAND_RE = re.compile(r'([+-])([0-9]{2})')
_SPATIAL_RESOLUTION_RE = re.compile(r'(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?(?:m|km|deg)')
_HEX_ID_RE = re.compile(r'[0-9a-f]{24}')

_UTC_OFFSET_MIN_MINUTES = -12 * 60
_UTC_OFFSET_MAX_MINUTES = 14 * 60
_ALLOWED_OFFSET_MINUTES = frozenset({0, 15, 30, 45})

_DOI_URL_PREFIX = 'https://doi.org/'


class ValidationError(ValueError):
    """Raised when metadata or dataset content fails envlib validation.

    Subclasses ValueError so ``except ValueError`` keeps working for callers
    that don't import envlib's exception.
    """


###################################################
# Field validators (pure functions; return the normalized value or raise)


def _require_str(field: str, value) -> str:
    if not isinstance(value, str):
        msg = f'{field} must be a str, not {type(value).__name__}.'
        raise ValidationError(msg)
    return value.strip()


def validate_slug(field: str, value: str) -> str:
    """Normalize a free-form slug field (strip, reject non-ASCII, lowercase, grammar-check).

    Non-ASCII input is rejected *before* lowercasing so no locale-dependent case
    mapping ever reaches the hash.
    """
    v = _require_str(field, value)
    if not v.isascii():
        msg = f'{field} must be ASCII; got {value!r}.'
        raise ValidationError(msg)
    v = v.lower()
    if not _SLUG_RE.fullmatch(v):
        msg = f'{field} must match [a-z0-9._-]+ after lowercasing; got {value!r}.'
        raise ValidationError(msg)
    if not _SLUG_ALNUM_RE.search(v):
        # punctuation-only slugs ('.', '-', '...') are typo-class garbage that
        # would mint permanent identities (ruling 2026-07-07)
        msg = f'{field} must contain at least one letter or digit; got {value!r}.'
        raise ValidationError(msg)
    return v


def validate_utc_offset(value: str) -> str:
    """Validate/canonicalize a utc_offset to ``±HH:MM``.

    Accepts the ``±HH`` input shorthand (expanded to ``±HH:00``). ``-00:00``
    normalizes to ``+00:00``. The offset must lie within [-12:00, +14:00] with
    minutes in {00, 15, 30, 45}. The frequency-dependent reduction rule is
    applied separately (see ``Metadata``) because it needs ``frequency_interval``.
    """
    v = _require_str('utc_offset', value)
    m = _UTC_OFFSET_SHORTHAND_RE.fullmatch(v)
    if m is not None:
        v = f'{m.group(1)}{m.group(2)}:00'
    m = _UTC_OFFSET_RE.fullmatch(v)
    if m is None:
        msg = f'utc_offset must be ±HH:MM (or ±HH shorthand); got {value!r}.'
        raise ValidationError(msg)
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    if mm not in _ALLOWED_OFFSET_MINUTES:
        msg = f'utc_offset minutes must be one of 00/15/30/45; got {value!r}.'
        raise ValidationError(msg)
    total = (hh * 60 + mm) * (-1 if sign == '-' else 1)
    if not _UTC_OFFSET_MIN_MINUTES <= total <= _UTC_OFFSET_MAX_MINUTES:
        msg = f'utc_offset must lie within [-12:00, +14:00]; got {value!r}.'
        raise ValidationError(msg)
    if total == 0:
        return '+00:00'
    return f'{sign}{hh:02d}:{mm:02d}'


def _utc_offset_seconds(canonical_offset: str) -> int:
    m = _UTC_OFFSET_RE.fullmatch(canonical_offset)
    if m is None:  # unreachable for canonical offsets; guards type narrowing
        msg = f'not a canonical utc_offset: {canonical_offset!r}.'
        raise ValueError(msg)
    sign, hh, mm = m.group(1), int(m.group(2)), int(m.group(3))
    return (hh * 3600 + mm * 60) * (-1 if sign == '-' else 1)


def validate_spatial_resolution(value):
    """Validate spatial_resolution: ``<number><unit>`` | ``'point'`` | None.

    The numeric grammar admits exactly one spelling per value; non-canonical
    spellings (``.25deg``, ``00.25deg``, ``0.250deg``, ``1.0km``) are REJECTED,
    never rewritten. Only case and whitespace normalize.
    """
    if value is None:
        return None
    v = _require_str('spatial_resolution', value).lower()
    if v == 'point':
        return v
    if not _SPATIAL_RESOLUTION_RE.fullmatch(v):
        msg = (
            f'spatial_resolution must be <number><m|km|deg> in canonical spelling '
            f'(e.g. 0.25deg, 1km, 500m), the literal point, or None; got {value!r}.'
        )
        raise ValidationError(msg)
    return v


def validate_product_code(value):
    if value is None:
        return None
    v = validate_slug('product_code', value)
    if v == 'none':
        msg = "product_code 'none' is rejected to avoid confusion with the None sentinel; use None itself."
        raise ValidationError(msg)
    return v


def validate_derived_from(value):
    if value is None:
        return None
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        msg = f'derived_from must be a list of dataset_version_ids and/or DOI URLs, not {type(value).__name__}.'
        raise ValidationError(msg)
    out = []
    for item in value:
        v = _require_str('derived_from entry', item)
        if not (_HEX_ID_RE.fullmatch(v) or (v.startswith(_DOI_URL_PREFIX) and len(v) > len(_DOI_URL_PREFIX))):
            msg = (
                f'derived_from entries must be 24-char hex dataset_version_ids '
                f'or {_DOI_URL_PREFIX}... URLs; got {item!r}.'
            )
            raise ValidationError(msg)
        out.append(v)
    return out


def validate_doi(value):
    if value is None:
        return None
    v = _require_str('doi', value)
    if not (v.startswith(_DOI_URL_PREFIX) and len(v) > len(_DOI_URL_PREFIX)):
        msg = f'doi must be a full DOI URL ({_DOI_URL_PREFIX}...); got {value!r}.'
        raise ValidationError(msg)
    return v


def _validate_text(field: str, value):
    if value is None:
        return None
    return _require_str(field, value)


###################################################
# Identity hashing — permanent contract


def _serialize_identity_value(value) -> str:
    return 'None' if value is None else value


def compute_dataset_version_id(values: dict) -> str:
    """blake2b-12 hex of all 11 Identity fields — identifies one version of a dataset.

    This is the catalogue entry key. ``values`` must hold fully
    normalized/canonical values (as produced by ``Metadata`` — including the
    frequency-reduced ``utc_offset``); prefer ``Metadata.dataset_version_id``
    unless you are certain the inputs are canonical.
    """
    return _hash_fields([values[f] for f in IDENTITY_FIELDS])


def compute_dataset_id(values: dict) -> str:
    """blake2b-12 hex of the 10 Identity fields excluding ``version`` — the dataset identity, stable across versions."""
    return _hash_fields([values[f] for f in IDENTITY_FIELDS if f != 'version'])


def _hash_fields(field_values) -> str:
    joined = '\x1f'.join(_serialize_identity_value(v) for v in field_values)
    return blake2b(joined.encode('utf-8'), digest_size=12).hexdigest()


def compute_station_id(geometry) -> str:
    """Deterministic station id from a shapely Point in EPSG:4326.

    tethys-compatible derivation: z stripped if present; WKT round-trip with
    ``rounding_precision=5`` (~1 m at the equator); signed zero collapsed
    (``-0.0`` -> ``0.0``, reachable after reprojection); explicit little-endian
    WKB; keyless blake2b-12 hex. Same x/y at different z share a station_id.
    """
    if not isinstance(geometry, shapely.Point):
        msg = f'station geometry must be a shapely Point (v1 supports Points only), not {type(geometry).__name__}.'
        raise ValidationError(msg)
    if geometry.is_empty:
        msg = 'station geometry must be a non-empty Point.'
        raise ValidationError(msg)
    if not (math.isfinite(geometry.x) and math.isfinite(geometry.y)):
        # NaN/inf would hash to a "valid-looking" id (NaN has a fixed WKB bit
        # pattern), silently correlating unrelated corrupt stations.
        msg = f'station coordinates must be finite; got ({geometry.x}, {geometry.y}).'
        raise ValidationError(msg)
    if geometry.has_z:
        geometry = shapely.Point(geometry.x, geometry.y)
    rounded = cast('shapely.Point', wkt.loads(wkt.dumps(geometry, rounding_precision=5)))
    canonical_point = shapely.Point(rounded.x + 0.0, rounded.y + 0.0)
    return blake2b(shapely.to_wkb(canonical_point, byte_order=1), digest_size=12).hexdigest()


###################################################
# Metadata class


class Metadata:
    """Structured envlib dataset metadata with validation and normalization on set.

    Construct all at once (``Metadata(feature=..., variable=..., ...)``) or
    incrementally (``meta = Metadata(); meta.feature = 'atmosphere'``). Every
    setter validates and normalizes; cross-field canonicalization (the
    utc_offset reduction rule, which depends on ``frequency_interval``) is
    applied lazily at every read point, so construction order never matters.

    ``feature``, ``variable``, ``method``, ``processing_level``,
    ``aggregation_statistic``, ``frequency_interval``, and ``license`` are
    CV-validated on set; per the validation-on-change-only rule, reading stored
    metadata back (``from_attrs(..., validate_cv=False)``) trusts the stored
    canonical values so vocabulary drift never orphans an existing dataset.
    """

    def __init__(self, **kwargs):
        self._values = dict.fromkeys(IDENTITY_FIELDS + GENERAL_FIELDS)
        for key, value in kwargs.items():
            if key not in self._values:
                msg = f'Unknown metadata field {key!r}.'
                raise ValidationError(msg)
            setattr(self, key, value)

    # -- CV-constrained identity fields ------------------------------------

    def _set_cv(self, field: str, value):
        if value is None:
            self._values[field] = None
            return
        try:
            self._values[field] = vocabularies.canonical(field, value)
        except (ValueError, TypeError) as err:
            # uniform error contract: every Metadata setter failure is a
            # ValidationError (vocabularies itself stays exception-agnostic)
            raise ValidationError(str(err)) from err

    feature = property(
        lambda self: self._values['feature'],
        lambda self, v: self._set_cv('feature', v),
        doc="Feature CV value (e.g. 'atmosphere', 'waterway').",
    )
    variable = property(
        lambda self: self._values['variable'],
        lambda self, v: self._set_cv('variable', v),
        doc='Variable CV value (ODM2-derived union envlib extensions).',
    )
    method = property(
        lambda self: self._values['method'],
        lambda self, v: self._set_cv('method', v),
        doc='Method CV value.',
    )
    processing_level = property(
        lambda self: self._values['processing_level'],
        lambda self, v: self._set_cv('processing_level', v),
        doc='Processing-level CV value (raw / preliminary / quality_controlled).',
    )
    aggregation_statistic = property(
        lambda self: self._values['aggregation_statistic'],
        lambda self, v: self._set_cv('aggregation_statistic', v),
        doc='CF cell_methods statistical subset value.',
    )
    license = property(
        lambda self: self._values['license'],
        lambda self, v: self._set_cv('license', v),
        doc='License CV value (canonical case preserved, e.g. CC-BY-4.0).',
    )

    @property
    def frequency_interval(self):
        """Canonical envlib frequency code, or None for irregular cadences."""
        return self._values['frequency_interval']

    @frequency_interval.setter
    def frequency_interval(self, value):
        self._set_cv('frequency_interval', value)

    # -- free-form / grammar-validated fields ------------------------------

    @property
    def owner(self):
        return self._values['owner']

    @owner.setter
    def owner(self, value):
        self._values['owner'] = None if value is None else validate_slug('owner', value)

    @property
    def product_code(self):
        return self._values['product_code']

    @product_code.setter
    def product_code(self, value):
        self._values['product_code'] = validate_product_code(value)

    @property
    def version(self):
        return self._values['version']

    @version.setter
    def version(self, value):
        self._values['version'] = None if value is None else validate_slug('version', value)

    @property
    def spatial_resolution(self):
        return self._values['spatial_resolution']

    @spatial_resolution.setter
    def spatial_resolution(self, value):
        self._values['spatial_resolution'] = validate_spatial_resolution(value)

    @property
    def utc_offset(self):
        """The canonical utc_offset, with the frequency reduction rule applied.

        For fixed-duration cadences an offset that divides the cadence evenly
        (identical binning to UTC) reduces to ``+00:00``; likewise when
        ``frequency_interval`` is None (no binning at all). Calendar cadences
        (month/year) always retain the stored offset.
        """
        return self._reduced_utc_offset()

    @utc_offset.setter
    def utc_offset(self, value):
        self._values['utc_offset'] = None if value is None else validate_utc_offset(value)

    @property
    def attribution(self):
        return self._values['attribution']

    @attribution.setter
    def attribution(self, value):
        self._values['attribution'] = _validate_text('attribution', value)

    @property
    def description(self):
        return self._values['description']

    @description.setter
    def description(self, value):
        self._values['description'] = _validate_text('description', value)

    @property
    def derived_from(self):
        return self._values['derived_from']

    @derived_from.setter
    def derived_from(self, value):
        self._values['derived_from'] = validate_derived_from(value)

    @property
    def doi(self):
        return self._values['doi']

    @doi.setter
    def doi(self, value):
        self._values['doi'] = validate_doi(value)

    # -- cross-field canonicalization ---------------------------------------

    def _reduced_utc_offset(self):
        stored = self._values['utc_offset']
        if stored is None:
            return None
        frequency = self._values['frequency_interval']
        if frequency is None:
            return '+00:00'
        try:
            entry = vocabularies.frequency_entry(frequency)
        except ValueError:
            # Stored frequency code no longer in the vocabulary (drift on a
            # re-read of old metadata): the stored offset was already reduced
            # at first registration, so returning it unchanged keeps the
            # dataset_version_id stable. New codes always resolve here.
            return stored
        if entry['kind'] == 'calendar':
            return stored
        if _utc_offset_seconds(stored) % entry['seconds'] == 0:
            return '+00:00'
        return stored

    # -- identity / completeness --------------------------------------------

    def missing_fields(self) -> list:
        """Identity fields still unset (nullable ones excepted) plus missing required General fields."""
        missing = [f for f in IDENTITY_FIELDS if self._values[f] is None and f not in NULLABLE_IDENTITY_FIELDS]
        missing += [f for f in ('license', 'attribution') if self._values[f] is None]
        return missing

    def _identity_values(self) -> dict:
        values = {f: self._values[f] for f in IDENTITY_FIELDS}
        values['utc_offset'] = self._reduced_utc_offset()
        return values

    def _require_identity_complete(self):
        missing = [f for f in IDENTITY_FIELDS if self._values[f] is None and f not in NULLABLE_IDENTITY_FIELDS]
        if missing:
            msg = f'Identity metadata incomplete; missing fields: {missing}.'
            raise ValidationError(msg)

    @property
    def dataset_version_id(self) -> str:
        """Deterministic id of this version of the dataset (all 11 Identity fields; the catalogue entry key)."""
        self._require_identity_complete()
        return compute_dataset_version_id(self._identity_values())

    @property
    def dataset_id(self) -> str:
        """Deterministic id of the dataset, stable across versions (Identity fields minus version)."""
        self._require_identity_complete()
        return compute_dataset_id(self._identity_values())

    # -- serialization --------------------------------------------------------

    def to_dict(self) -> dict:
        """Emit the ``envlib_``-prefixed attr dict for ``ds.attrs.update()``.

        Requires complete Identity metadata plus the required General fields
        (license, attribution). All 11 identity keys are always present
        (nullable ones as JSON null); optional General fields only when set;
        the computed dataset_version_id/dataset_id are included (self-identification).
        """
        missing = self.missing_fields()
        if missing:
            msg = f'Metadata incomplete; missing fields: {missing}.'
            raise ValidationError(msg)
        out = {ATTR_PREFIX + f: v for f, v in self._identity_values().items()}
        for f in GENERAL_FIELDS:
            value = self._values[f]
            if value is not None:
                out[ATTR_PREFIX + f] = value
        out[ATTR_PREFIX + 'dataset_version_id'] = self.dataset_version_id
        out[ATTR_PREFIX + 'dataset_id'] = self.dataset_id
        return out

    @classmethod
    def from_attrs(cls, attrs, *, validate_cv: bool = True) -> Metadata:
        """Rebuild Metadata from ``envlib_``-prefixed attrs (``ds.attrs`` or a dict).

        Non-envlib keys are ignored. When ``envlib_dataset_version_id`` /
        ``envlib_dataset_id`` are present, the hash is re-derived from the
        identity attrs and a mismatch raises (catches attrs hand-edited after
        first registration).

        Args:
            attrs: Mapping that may contain ``envlib_``-prefixed keys.
            validate_cv: When False (re-reads of already-registered metadata),
                CV-membership checks are skipped and stored canonical values are
                trusted — the validation-on-change-only rule, so vocabulary
                drift never orphans existing datasets. Grammar-validated fields
                are always re-checked (their rules never drift).
        """
        meta = cls()
        for field in IDENTITY_FIELDS + GENERAL_FIELDS:
            key = ATTR_PREFIX + field
            if key not in attrs:
                continue
            value = attrs[key]
            if not validate_cv and field in _CV_FIELDS:
                meta._values[field] = value
            else:
                setattr(meta, field, value)

        stored_id = attrs.get(ATTR_PREFIX + 'dataset_version_id')
        if stored_id is not None and stored_id != meta.dataset_version_id:
            msg = (
                f'Stored envlib_dataset_version_id {stored_id!r} does not match the id derived from the identity '
                f'attrs ({meta.dataset_version_id!r}) — identity attrs were modified after first registration.'
            )
            raise ValidationError(msg)
        stored_dataset_id = attrs.get(ATTR_PREFIX + 'dataset_id')
        if stored_dataset_id is not None and stored_dataset_id != meta.dataset_id:
            msg = (
                f'Stored envlib_dataset_id {stored_dataset_id!r} does not match the id derived from the '
                f'identity attrs ({meta.dataset_id!r}).'
            )
            raise ValidationError(msg)
        return meta

    def __repr__(self):
        set_fields = {f: v for f, v in self._values.items() if v is not None}
        if self._values['utc_offset'] is not None:
            set_fields['utc_offset'] = self._reduced_utc_offset()
        return f'Metadata({set_fields!r})'

    def __eq__(self, other):
        if not isinstance(other, Metadata):
            return NotImplemented
        mine = dict(self._values)
        theirs = dict(other._values)
        mine['utc_offset'] = self._reduced_utc_offset()
        theirs['utc_offset'] = other._reduced_utc_offset()
        return mine == theirs

    def __hash__(self):
        # must mirror __eq__: hash over the REDUCED utc_offset, or two equal
        # objects (e.g. '+12:00' vs '+00:00' at a 1h cadence) hash differently
        # and corrupt sets/dicts. Caveat: Metadata is mutable — mutating an
        # instance after using it as a dict/set member breaks lookup, as with
        # any value-hashed mutable object. Prefer dataset_version_id strings for dedup.
        values = dict(self._values)
        values['utc_offset'] = self._reduced_utc_offset()
        return hash(tuple(sorted((k, str(v)) for k, v in values.items())))
