# Browsing & Querying

## Connecting a Catalogue

The default catalogue is the public envlib commons — shared, credential-free, zero configuration:

```python
import envlib

cat = envlib.Catalogue()
```

!!! note
    The public commons is **not hosted yet**; until it is, a bare `Catalogue()` raises with instructions, and the `ENVLIB_PUBLIC_RCG_URL` environment variable can point at any stand-in.

Any other catalogue — an agency's, a research group's, your own — is addressed by location. For a publicly hosted index that's just its HTTPS URL, still credential-free:

```python
cat = envlib.Catalogue(remotes=['https://s3.example.com/some-bucket/catalogue.rcg'])
```

Passing `remotes=` *replaces* the public default; add `include_public=True` to merge your remotes with the commons. (A remote can also be an `ebooklet.S3Connection` or a dict of its parameters, for indexes on private buckets that need credentials.)

The catalogue snapshots all entries at construction. After new registrations land upstream, call `cat.refresh()` to re-pull.

**Offline behavior**: if a remote is unreachable but you have pulled its index before, the catalogue warns and serves the cached copy read-only. Only first-ever use requires connectivity. (A catalogue whose RCG doesn't exist remotely *yet* — the producer bootstrap case — is treated as empty, with a warning.)

## Browsing: what's in here?

The plural properties answer "what does this catalogue actually contain" — one per identity field, plus `licenses` and `dataset_types`:

```python
cat.variables            # ['precipitation', 'streamflow', 'temperature']
cat.owners               # ['ecan', 'ecmwf', 'niwa']
cat.features             # ['atmosphere', 'waterway']
cat.product_codes        # ['era5', 'vcsn']
cat.dataset_types        # ['grid', 'ts_ortho']
```

They all wrap `cat.distinct(field, counts=False)`, which additionally gives you counts (including how many entries *lack* an optional field):

```python
cat.distinct('product_code', counts=True)    # {'era5': 3, 'vcsn': 1, None: 12}
```

This is a different question from what's *valid* — for that, see the [vocabularies module](vocabularies.md). For the free-form fields (`owner`, `product_code`, `version`), browsing the catalogue is the *only* way to discover values.

## Querying

All entries, filtered. Field kwargs are AND-ed together; a list value means "any of these":

```python
results = cat.query(
    variable='temperature',
    owner=['niwa', 'ecmwf'],            # either owner
    processing_level='quality_controlled',
    dataset_type='grid',
)
```

Matching is **case-insensitive on both sides** — `owner='NIWA'` matches stored `niwa`, `license='cc-by-4.0'` matches stored `CC-BY-4.0`. It is exact-match only: no globs, substrings, or regex. `query(product_code=None)` matches entries with no product code.

### The latest-version default

Without an explicit `version=` kwarg, the results contain **the latest version of each matching dataset** (grouped by `dataset_id`; "latest" is the greatest `created_at`). Pin `version='2'` to get a specific version, or pass `version=['1', '2']` to see several.

!!! warning "Back-fill caveat"
    "Latest" is decided by *first registration time*, not by parsing version strings. If someone back-fills version 1 *after* registering version 2, the back-filled v1 becomes "latest". When exact versions matter, pin `version=` explicitly.

### Spatial filters

At most one of these per query; all in EPSG:4326 (WGS84 lon/lat), all *intersects* semantics against each dataset's stored bounding box:

```python
cat.query(bbox=[166, -47, 179, -34])                  # [min_lon, min_lat, max_lon, max_lat]
cat.query(within_radius=((174.0, -41.0), 50))          # ((lon, lat), km) great-circle
cat.query(geometry=shapely.Polygon(...))               # any shapely geometry
```

Bounding boxes use the GeoJSON antimeridian convention: `min_lon > max_lon` means the box crosses 180° (a domain spanning 166°E–172°W is `[166, -47, -172, -34]`, not a near-global box). Both stored and query boxes may cross; envlib handles the wraparound, including for `within_radius` distances across the dateline.

The stored bbox is a coarse, never-too-small filter — for precise spatial selection, open the dataset and use cfdb's native selection against its actual coordinates.

### Temporal filters

`start_date` / `end_date` (ISO strings or datetimes) use *overlaps* semantics against each dataset's recorded time range; either bound may be omitted:

```python
cat.query(variable='streamflow', start_date='2015-01-01', end_date='2020-01-01')
```

!!! warning "Quasi-static data"
    Temporal filters match *recorded timestamps*, not validity periods. A DEM registered with a single 2013 survey date is a zero-width interval — a `start_date='2020-01-01'` query will not return it even though the terrain is still current. Don't temporally filter quasi-static features.

## Results

`query()` returns a list of `DatasetRef` objects — each prints as its metadata dict, exposes every field as an attribute (`ref.variable`, `ref.owner`, `ref.dataset_version_id`, ...), and knows how to open itself. See [Opening Data](opening-data.md).
