"""envlib: a distributed database and catalogue for environmental data."""

from envlib import vocabularies
from envlib.catalogue import Catalogue, DatasetRef, validate_dataset
from envlib.metadata import (
    Metadata,
    PublishIntegrityError,
    ValidationError,
    canonical_station_point,
    compute_station_id,
)

__version__ = '0.1.8'

__all__ = [
    'Catalogue',
    'DatasetRef',
    'Metadata',
    'PublishIntegrityError',
    'ValidationError',
    'canonical_station_point',
    'compute_station_id',
    'validate_dataset',
    'vocabularies',
]
