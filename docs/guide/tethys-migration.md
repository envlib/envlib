# Migrating from tethys

envlib is the successor to the tethys metadata model. Most concepts carry over directly; this page lists what changes when migrating tethys datasets.

## Ids

- **`station_id` values carry over unchanged** — envlib uses tethys's derivation (5-decimal rounding, hashed location) byte-for-byte for 2D points, so the same physical station keeps its id.
- **Dataset ids do NOT carry over.** envlib's `dataset_id` matches tethys's *concept* (a version-less dataset identity) but is computed from different fields with a different serialization, so the hex values differ. Plan for an id re-mapping table if anything downstream stored tethys ids.
- **Always derive ids through `envlib.Metadata`** (never by hashing fields yourself): the class applies normalization — including the utc_offset reduction — before hashing.

## Field conversions

**`parameter` → `variable`**, with renames where tethys names were wrong or non-ODM2:

| tethys | envlib |
|---|---|
| `snow_depth` | `snowfall` (the source data was accumulated snowfall, misnamed) |
| `potential_et` | `evapotranspiration_potential` |
| `naturalised_streamflow` | `streamflow` (+ carry the naturalisation in `product_code`/`method`) |
| `nitrogen_ammonia_+_ammonium` | `nitrogen_ammonia` (merged) |
| `e-coli` | `e_coli` |

**`feature` renames**: `pedosphere` → `soil`, `still_waters` → `still_water`.

**`product_code` decomposition** — tethys overloaded it; envlib splits the axes:

| tethys product_code | envlib |
|---|---|
| `raw_data` | `processing_level='raw'`, `product_code=None` |
| `quality_controlled_data` | `processing_level='quality_controlled'`, `product_code=None` |
| `reanalysis-era5-land` | `product_code='era5-land'` (`method='simulation'` carries the reanalysis-ness) |
| free-text names | slugified discriminators (e.g. `stream_depletion_method_1`) |

**`frequency_interval`** — pandas offset strings become envlib codes: `T` → `1min`, `10min` → `10min`, `1H` → `1h`, `24H` → `day`, `None` → `None`.

**`utc_offset`** — pandas-style hour strings become `±HH:MM`: `'12H'` → `'+12:00'`, `'-3H'` → `'-03:00'`, `'0H'` → `'+00:00'`. envlib then applies its reduction rule automatically (a fixed cadence whose offset divides it evenly normalizes to `+00:00`).

**`aggregation_statistic`** — tethys's `instantaneous`/`continuous`/`sporadic` map to envlib's `point`; `cumulative` maps to `sum` (verify it's an interval sum, not a running total); `mean` stays `mean`.

## Timestamps

Tethys production data at sub-daily and daily cadences is already interval-start labeled, matching envlib's convention — no shifting needed. Any *other* source at a period-end-anchored pandas frequency (`M`, `Q`, `W`, `Y`) must be checked and shifted explicitly; pandas labels those on the right by default.

