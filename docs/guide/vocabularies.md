# Vocabularies

Most identity fields are constrained to controlled vocabularies (CVs), bundled with envlib as JSON files. The `envlib.vocabularies` module answers "what is *valid*"; the catalogue's [browse properties](browsing-querying.md#browsing-whats-in-here) answer "what is *present*".

```python
from envlib import vocabularies

vocabularies.list('feature')             # all valid values of a field
vocabularies.is_valid('variable', 'streamflow')       # True
vocabularies.canonical('license', 'cc-by-4.0')        # 'CC-BY-4.0' (case-insensitive resolution)
```

## The vocabularies

**feature** — the environmental compartment, mapped to [ENVO](https://sites.google.com/site/environmentontology/) terms: `atmosphere`, `waterway`, `still_water`, `ocean`, `groundwater`, `glacier`, `wetland`, `soil`, `coastline`, `land`.

**variable** — what was measured or modeled: the [ODM2 variable-name vocabulary](http://vocabulary.odm2.org/variablename/) (~1000 terms, snake_cased: `temperature`, `streamflow`, `precipitation`, ...) plus a small set of flagged envlib extensions for quantities ODM2 lacks (`snowfall`, `specific_humidity`, `runoff`, ...). Note the medium lives in `feature`, not the variable: air temperature is `variable='temperature'` + `feature='atmosphere'`.

**method** — how the result was produced: `derivation`, `estimation`, `field_activity`, `simulation`, `sample_analysis`, `sensor_recording`, `forecast`.

**processing_level** — how settled the data is: `raw`, `preliminary`, `quality_controlled`. (Per-record QC codes belong in an ancillary flag variable, not here.)

**aggregation_statistic** — the CF cell_methods statistical subset: `point` (instantaneous), `mean`, `sum`, `maximum`, `minimum`, `median`, `mode`, `mid_range`, `variance`, `standard_deviation`, `range`.

**license** — a curated set of open-access data licenses: the Creative Commons family (`CC-BY-4.0`, `CC0-1.0`, ...), `ODbL-1.0`, plus envlib extensions for common non-SPDX data licenses (`Copernicus-1.0`). Only open-access licenses are accepted.

**frequency_interval** — envlib's own cadence codes (deliberately *not* pandas offset aliases, whose spellings have changed across pandas versions):

| Code | Duration | | Code | Duration |
|---|---|---|---|---|
| `1min` | 60 s | | `3h` | 3 h |
| `5min` | 5 min | | `6h` | 6 h |
| `10min` | 10 min | | `12h` | 12 h |
| `15min` | 15 min | | `day` | 24 h |
| `30min` | 30 min | | `month` | calendar |
| `1h` | 1 h | | `year` | calendar |

`None` (not a code) is the value for irregular cadences. Two input aliases are accepted and resolve to canonical: `24h` → `day`, `60min` → `1h`. Fixed cadences all divide 24 h evenly, so bins anchor unambiguously to the (offset-shifted) day — which is why there are no `week` or multi-day codes yet.

## CF standard names

`standard_name.json` bundles the full CF standard-name table (v94, ~5000 names), used to validate overrides and to back the curated mapping:

```python
vocabularies.get_cf_standard_names('temperature', feature='ocean')      # ['sea_water_temperature']
vocabularies.get_cf_standard_names('temperature', feature='waterway')   # [] — curated: none applicable
vocabularies.get_cf_standard_names('cadmium_dissolved', feature='soil') # None — not curated yet
```

Three distinct answers:

- **A list** — the ordered candidates; the first is what envlib auto-populates at publish.
- **An empty list** — curated "no applicable standard name". This is common and legitimate: CF's water-property names are ocean-scoped (`sea_water_*`), and envlib never stamps an ocean name on a river. The attribute stays absent — valid CF.
- **`None`** — nobody has curated this pair yet; envlib warns at validation but doesn't block. Set `standard_name` yourself if you know the right CF term.

## Keeping vocabularies fresh

```python
vocabularies.refresh()                   # ODM2 + the CF table
vocabularies.refresh('standard_name')    # just one
```

`refresh()` fetches the current upstream lists and writes them to a user-level overlay (`~/.envlib/vocabularies/`) that takes precedence over the bundled files — it never writes into the installed package. Two guarantees:

- **Curation is never regenerated.** The hand-maintained variable→CF mapping and the envlib extensions are untouched; upstream additions arrive as new (uncurated) terms and upstream *removals* are only reported, never deleted — so existing datasets can't be orphaned.
- **Validation happens on change only.** Values are validated when *set*; reading or re-registering existing datasets never re-validates against the current vocabulary, so a term that upstream later renames keeps working for the datasets that used it.
