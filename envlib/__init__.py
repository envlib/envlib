"""envlib: a distributed database and catalogue for environmental data."""

from envlib import vocabularies
from envlib.catalogue import (
    QUERYABLE_FIELDS,
    Catalogue,
    DatasetRef,
    distinct_values,
    latest_per_dataset,
    match_entries,
    validate_dataset,
    version_key,
)
from envlib.metadata import (
    Metadata,
    PublishIntegrityError,
    ValidationError,
    canonical_station_point,
    compute_station_id,
)

__version__ = '0.1.9'

__all__ = [
    'QUERYABLE_FIELDS',
    'Catalogue',
    'DatasetRef',
    'Metadata',
    'PublishIntegrityError',
    'ValidationError',
    'canonical_station_point',
    'compute_station_id',
    'distinct_values',
    'latest_per_dataset',
    'match_entries',
    'validate_dataset',
    'version_key',
    'vocabularies',
]
