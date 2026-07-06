# tethys → envlib Variable Inventory (curation input)

The v1 scope for the `variable` → CF `standard_name` mapping curation (OPEN_WORK backlog item). Generated 2026-07-05 by a scripted sweep of the tethys production configs: **615 dataset blocks** across 68 `parameters*.yml` files (station/ts extraction repos) + 4 `virtual_parameters*.py` modules (era5, metservice moana v1/v2, tethys-wrf grids) → **47 distinct parameters**.

**Read the `tethys cf_standard_name` column as hints, not truth** — they were never validated against the CF table, and several are demonstrably wrong (see the buckets below). Curation decides fresh; tethys values are evidence of intent only.

**Upstream snapshots verified 2026-07-06**: ODM2 variablename JSON API live (`http://vocabulary.odm2.org/api/v1/variablename/?format=json`, 993 terms, unpaginated; `term` is camelCase → snake_case yields envlib spellings, so tethys names like `gage_height` ↔ `gageHeight` largely match already) and CF standard-name table **v94** (2026-06-09; 5071 names + 599 aliases; `https://cfconventions.org/Data/cf-standard-names/current/src/cf-standard-name-table.xml`). Every "likely correct" CF candidate named below was membership-checked against v94 and exists; `soil_moisture` and `water_use` confirmed NOT CF names, as claimed.

## Curation buckets

**A. Likely rubber-stamp (~20)** — tethys hint is plausibly the right CF name; verify against the CF table and accept: `temperature` (per-feature: `air_temperature` / `soil_temperature`; freshwater case → bucket D), `relative_humidity`, `specific_humidity`, `wind_speed`, `wind_direction` → `wind_from_direction`, `temperature_dew_point` → `dew_point_temperature`, `barometric_pressure` (`air_pressure` vs `air_pressure_at_mean_sea_level` — pick per dataset kind), `radiation_incoming_longwave`/`shortwave` → `surface_downwelling_*_flux_in_air`, `streamflow`/`naturalised_streamflow` → `water_volume_transport_in_river_channel`, `gage_height` → `water_surface_height_above_reference_datum`, `groundwater_depth`/`water_level`(gw) → `water_table_depth`, `precipitation` → `precipitation_amount` (mm cumulative; note `lwe_thickness_of_precipitation_amount` as the units-exact alternative), `evaporation` → `lwe_thickness_of_water_evaporation_amount`, `ground_heat_flux` → `downward_heat_flux_in_soil`, `surface_emissivity` → `surface_longwave_emissivity`, `albedo` → `surface_albedo`, `snow_cover` → `surface_snow_area_fraction`, `runoff` → `runoff_amount`.

**B. Tethys mapping visibly WRONG — must re-curate (8)**:
| parameter | tethys hint | why wrong | likely correct |
|---|---|---|---|
| `electrical_conductivity` | `water_surface_height_above_reference_datum` | copy-paste error | no exact freshwater CF name; nearest is sea-water EC (bucket D) |
| `latent_heat_flux` | `downward_heat_flux_in_soil` | copy-paste from ground_heat_flux | `surface_upward_latent_heat_flux` |
| `air_ventilation_index` | `air_pressure` | unrelated quantity | none applicable (no CF name for AVI) |
| `particulate_matter_10` | `mass_fraction_of_pm10_particulate_organic_matter_...` | wrong species (organic-only) AND wrong quantity kind for µg/m³ | `mass_concentration_of_pm10_ambient_aerosol_particles_in_air` |
| `particulate_matter_2.5` | (same pattern) | same | `mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air` |
| `snow_depth` | `thickness_of_snowfall_amount` | snowFALL-per-interval ≠ snow depth; era5 source variable needs checking | `surface_snow_thickness` OR keep snowfall semantics — ruling needed |
| `volumetric_water_content` | `soil_moisture` (not a CF name) / `mass_content_of_water_in_soil` (wrong kind for m³/m³) | invalid + kind mismatch | `volume_fraction_of_condensed_water_in_soil` |
| `water_use` | `water_use` | not a CF name | none applicable |

**C. Never mapped — mostly the water-quality tail (~15)**: `chloride_dissolved`, `coliform_fecal`, `coliform_total`, `e-coli`, `nitrogen_ammonia`, `nitrogen_ammonia_+_ammonium`, `nitrogen_nitrate`, `nitrogen_nitrite`, `nitrogen_total`, `oxygen_dissolved`, `phosphorus_orthophosphate`, `phosphorus_orthophosphate_dissolved`, `phosphorus_total`, `turbidity` (hint `sea_water_turbidity` — freshwater problem), `velocity`, `allocation`, `recharge_groundwater` (hint `subsurface_runoff_amount` is an approximation), `potential_et` (hint `water_evapotranspiration_flux` mismatches mm-cumulative units; v94 has `water_potential_evapotranspiration_amount` — the units-consistent candidate). CF chemistry names are sea-water-scoped (`mass_concentration_of_X_in_sea_water`), so expect many **"curated: none applicable"** entries here — the mapping's explicit empty-list case.

**D. Cross-cutting issues (affect multiple rows)**:
- **The freshwater gap**: CF scopes water-body names to `sea_water_*` (temperature, EC, oxygen, turbidity, chemistry). Confirmed empirically against v94: only 22 names contain river/lake/fresh, ALL transport/flux quantities (e.g. `water_volume_transport_in_river_channel`) — zero freshwater water-property names exist. For waterway/still_water/groundwater datasets the curation must pick a policy: use the sea_water name anyway (common community practice), or "none applicable". One ruling, applied consistently across ~12 rows.
- **Amount vs flux vs thickness**: mm-cumulative quantities (`precipitation`, `evaporation`, `potential_et`, `snow*`) must pick the units-consistent CF name kind; the mapping should carry canonical units per CF name as the disambiguator.
- **Feature CV drift**: tethys uses `pedosphere` and `still_waters`; envlib's feature CV has `soil` and `still_water`. Migration needs the feature rename map (add to the plan's migration notes when curation lands).
- **Unit oddities harvested** (config errors, not curation blockers): `relative_humidity` with units `m^3/m^3` in one config; `wind_direction` with units `m/s` in another; `gage_height` in `mm` in one repo.
- **tethys parameter → ODM2 variablename reconciliation**: several tethys spellings aren't ODM2 terms (`gage_height`, `e-coli`, `potential_et`, `temperature_dew_point`, `volumetric_water_content`, …) — each needs its envlib `variable` (ODM2 underscore_style) decided alongside the CF mapping.

## Curation review table (finalized 2026-07-06 — all rulings decided)

Evidence basis: every tethys parameter was reconciled against the live ODM2 list (30/47 are *exact* ODM2 terms after camelCase→snake_case), and every proposed CF name below exists in CF v94 with the stated canonical units. All rulings R0–R5 are decided (below); the table's status column reflects the final decisions.

### Rulings — DECIDED 2026-07-06 (Mike approved all recommendations)

- **R0 = drop (revised 2026-07-06)** — `sea_water_*` names are used **only** when `feature=ocean`. Every freshwater property whose only CF option is a `sea_water_*` name curates to "none applicable" (stamping an ocean name on a river is a false semantic assertion and contradicts envlib's own `feature`). Consequence: **CF `standard_name` is no longer required to register** — envlib derives it from the curated mapping where one exists and leaves it absent otherwise (see the plan's Data-variable requirements + Metadata sections). Non-ocean generic water names are unaffected and stay (`water_surface_height_above_reference_datum`, `water_volume_transport_in_river_channel`, `water_table_depth`).
- **R1 = (a)** variable CV = ODM2 ∪ flagged envlib extensions (refresh never touches extensions); architecture-plan variable-CV description updated to match.
- **R2 = clean spellings** (`nitrogen_nitrate`, …) with the exact `odm2_term` recorded per vocab entry.
- **R3 →** `snow_depth` renamed to `snowfall` (source is WRF `SNOWNC` accumulated snowfall), an R1 extension → `lwe_thickness_of_snowfall_amount`.
- **R4 = merge** the two ammonia params into `nitrogen_ammonia`.
- **R5:** `naturalised_streamflow`→`streamflow` + discriminators; `recharge_groundwater`→`subsurface_runoff_amount` proxy; river `velocity`→none.

**Why the freshwater water-quality tail is "none" — two layers**: Under the final R0 (ocean-only) rule, freshwater temperature/EC/DO/turbidity/phosphate are "none" simply because their only CF names are `sea_water_*` and envlib won't stamp an ocean name on a river. The *nitrogen species* would be "none" even under the rejected liberal policy, via two harder CF walls worth recording: (1) **no freshwater concentration medium exists at all** — every `*_concentration_of_X_in_Y` name is `in_air` (981), `in_sea_water` (173), `in_soil` (1), or sediment; there is no `in_river_water`/`in_freshwater`; (2) **nitrate/nitrite/ammonium in water are mole-concentration only** ([mol m-3]) while council data is mg/l (mass/volume) — CF requires the `units` attr to be UDUNITS-convertible to the standard name's canonical units, and UDUNITS has no molar masses, so mol⁻vs⁻kg are different dimensions; attaching a mole-concentration name to mg/l data is a CF *compliance error*. (This is also why, when the liberal policy was briefly on the table, phosphate and oxygen were mappable but the nitrogen species were not: CF has `mass_concentration_of_{phosphate,oxygen}_in_sea_water` [kg m-3] but no mass form for the nitrogen species.) `nitrogen_total`/`phosphorus_total` additionally fail on semantics (CF's `mass_concentration_of_inorganic_nitrogen_in_sea_water` is *inorganic*, not total; there's no total-P mass name). Net: CF's nutrient vocabulary targets the ocean-model mole-cycle, not freshwater mg/l monitoring.

### Original rulings (R0–R5) — rationale retained for the record

- **R0 — freshwater policy** (~9 rows): CF has `sea_water_*` names only. Options: (a) use `sea_water_*` names for waterway/still_water/groundwater properties (common community practice; keeps EC, DO, phosphate, turbidity mappable), or (b) "none applicable" for all freshwater properties. **Recommend (a)** — the mapping is advisory, and a slightly-misscoped CF name beats none for discoverability.
- **R1 — variable-CV extension policy** (9 rows): `specific_humidity`, `runoff`, `snow_cover`, `surface_emissivity`, `particulate_matter_10`/`2.5`, `air_ventilation_index`, `allocation`, `water_use` have **no ODM2 term** (mostly grid/model quantities). Options: (a) variable CV = ODM2 ∪ **flagged envlib extensions** (extensions never touched by `refresh()` — the license-CV pattern), or (b) ODM2-only and these params get renamed/dropped. **Recommend (a)**; requires a small architecture-plan edit to the variable CV description.
- **R2 — formula-bearing ODM2 spellings** (4 rows): ODM2 terms like `nitrogenNitrate_NO3` snake-case horribly (`nitrogen_nitrate_n_o3`). **Recommend**: envlib spelling = the clean tethys-style name (`nitrogen_nitrate`), with the exact `odm2_term` recorded in the vocab entry (hash uses the envlib spelling; ODM2 linkage preserved as data).
- **R3 — `snow_depth` semantics — RESOLVED by source check (2026-07-06)**: all three grid modules (era5, tethys-wrf, metservice moana v2) compute it from WRF `SNOWNC` = *accumulated snowfall* in mm water-equivalent (the compute function is named `snowfall`). It is snowfall accumulation misnamed as depth. **Recommend**: envlib variable = `snowfall` (an R1 extension — ODM2 has `snowDepth`/`snowWaterEquivalent` but no snowfall term) mapped to `lwe_thickness_of_snowfall_amount` [m] (mm LWE ✓); migration renames `snow_depth` → `snowfall`. Keeping the name `snow_depth` would collide with ODM2's true meaning (snowpack depth) and poison future snowpack datasets.
- **R4 — ammonia twins**: `nitrogen_ammonia` and `nitrogen_ammonia_+_ammonium` both best-match ODM2's combined `nitrogenDissolved_Free_Ionized_Ammonia_NH3_NH4`. **Recommend** merging to one envlib variable (`nitrogen_ammonia`) unless the source data genuinely distinguishes NH₃-only.
- **R5 — three singles**: `naturalised_streamflow` → **recommend** variable=`streamflow` with `product_code`/`method` carrying the naturalisation (no ODM2 term; it's the same quantity, differently produced); `recharge_groundwater` → accept `subsurface_runoff_amount` as the land-model-drainage proxy or curate none — **recommend the proxy** for the grid products; `velocity` (river) → **recommend none applicable** (`sea_water_speed` is a stretch even under R0a).

### The table

Status: ✔ = final. "none" = curated empty list ("no applicable standard name"). "R#" markers in the status column note which ruling drove the row (all now decided).

**Encoding convention for step 1**: where a row lists more than one CF name, the **first listed is the auto-populate default** and the rest are override candidates (ordered). Feature-dependent rows (`temperature`) are keyed `(variable, feature)` → its own candidate list. Carry each CF name's canonical units (shown in `[…]`) into `variable.json` as the disambiguator, and flag each variable's `source` (`odm2` with `odm2_term`, or `envlib` extension).

| tethys parameter | envlib `variable` (proposed) | ODM2 term | CF standard_name (proposed) [canonical units] | status |
|---|---|---|---|---|
| `albedo` | `albedo` | `albedo` | `surface_albedo` [1] | ✔ |
| `barometric_pressure` | `barometric_pressure` | `barometricPressure` | `air_pressure` [Pa] for station/instant; `air_pressure_at_mean_sea_level` for MSL-reduced products | ✔ (per-dataset pick) |
| `evaporation` | `evaporation` | `evaporation` | `lwe_thickness_of_water_evaporation_amount` [m] (mm ✓) | ✔ |
| `gage_height` | `gage_height` | `gageHeight` | `water_surface_height_above_reference_datum` [m] | ✔ |
| `ground_heat_flux` | `ground_heat_flux` | `groundHeatFlux` | `downward_heat_flux_in_soil` [W m-2] | ✔ |
| `groundwater_depth` | `groundwater_depth` | `groundwaterDepth` | `water_table_depth` [m] | ✔ |
| `latent_heat_flux` | `latent_heat_flux` | `latentHeatFlux` | `surface_upward_latent_heat_flux` [W m-2] (fixes tethys copy-paste) | ✔ |
| `potential_et` | `evapotranspiration_potential` | `evapotranspirationPotential` | `water_potential_evapotranspiration_amount` [kg m-2] (mm ✓) | ✔ (note the variable rename) |
| `precipitation` | `precipitation` | `precipitation` | `precipitation_amount` [kg m-2] (mm ✓; `lwe_thickness_of_precipitation_amount` the alternative) | ✔ |
| `radiation_incoming_longwave` | `radiation_incoming_longwave` | `radiationIncomingLongwave` | `surface_downwelling_longwave_flux_in_air` [W m-2] | ✔ |
| `radiation_incoming_shortwave` | `radiation_incoming_shortwave` | `radiationIncomingShortwave` | `surface_downwelling_shortwave_flux_in_air` [W m-2] | ✔ |
| `relative_humidity` | `relative_humidity` | `relativeHumidity` | `relative_humidity` [1] (% ✓) | ✔ |
| `streamflow` | `streamflow` | `streamflow` | `water_volume_transport_in_river_channel` [m3 s-1] (configs listing `m^3` should be m³/s) | ✔ |
| `temperature` | `temperature` | `temperature` | atmosphere→`air_temperature` [K]; soil→`soil_temperature`; ocean→`sea_water_temperature`; freshwater bodies (waterway/still_water/groundwater)→**none** (CF has only `sea_water_*`) | ✔ (per-feature) |
| `temperature_dew_point` | `temperature_dew_point` | `temperatureDewPoint` | `dew_point_temperature` [K] | ✔ |
| `volumetric_water_content` | `volumetric_water_content` | `volumetricWaterContent` | `volume_fraction_of_condensed_water_in_soil` [1] (m³/m³ ✓) | ✔ |
| `water_level` (groundwater) | `water_level` | `waterLevel` | `water_table_depth` [m] for depth-to-water datasets; elevation datasets should use `water_surface_height_above_reference_datum` — per-dataset care | ✔ (note) |
| `wind_direction` | `wind_direction` | `windDirection` | `wind_from_direction` [degree] | ✔ |
| `wind_speed` | `wind_speed` | `windSpeed` | `wind_speed` [m s-1] | ✔ |
| `chloride_dissolved` | `chloride_dissolved` | `chlorideDissolved` | none — CF has no chloride-in-water name (salinity is the ocean concept) | ✔ (none) |
| `coliform_fecal` | `coliform_fecal` | `coliformFecal` | none | ✔ (none) |
| `coliform_total` | `coliform_total` | `coliformTotal` | none | ✔ (none) |
| `e-coli` | `e_coli` | `e_coli` | none | ✔ (none; hyphen→underscore) |
| `nitrogen_total` | `nitrogen_total` | `nitrogenTotal` | none — CF dissolved-N is mole-only [mol m-3], not convertible from mg/l | ✔ (none) |
| `phosphorus_total` | `phosphorus_total` | `phosphorusTotal` | none — same mole-only issue | ✔ (none) |
| `electrical_conductivity` | `electrical_conductivity` | `electricalConductivity` | none for freshwater (only `sea_water_electrical_conductivity` exists → ocean-only); atmosphere rows in configs are errors | ✔ (none; `sea_water_electrical_conductivity` only if feature=ocean) |
| `oxygen_dissolved` | `oxygen_dissolved` | `oxygenDissolved` | none for freshwater (only `mass_concentration_of_oxygen_in_sea_water` / `fractional_saturation_..._in_sea_water` exist → ocean-only) | ✔ (none; ocean-only names) |
| `phosphorus_orthophosphate` | `phosphorus_orthophosphate` | `phosphorusOrthophosphate` | none for freshwater (only `mass_concentration_of_phosphate_in_sea_water` → ocean-only) | ✔ (none) |
| `phosphorus_orthophosphate_dissolved` | `phosphorus_orthophosphate_dissolved` | `phosphorusOrthophosphateDissolved` | none for freshwater (same ocean-only name) | ✔ (none) |
| `turbidity` | `turbidity` | `turbidity` | none for freshwater (only `sea_water_turbidity` → ocean-only) | ✔ (none) |
| `velocity` | `velocity` | `velocity` | none (only `sea_water_speed`/`flood_water_speed` → ocean-only) | ✔ (none) |
| `nitrogen_nitrate` | `nitrogen_nitrate` | `nitrogenNitrate_NO3` | none — CF nitrate is mole-only | R2 (spelling) |
| `nitrogen_nitrite` | `nitrogen_nitrite` | `nitrogenNitrite_NO2` | none — same | R2 |
| `nitrogen_ammonia` | `nitrogen_ammonia` | `nitrogenDissolved_Free_Ionized_Ammonia_NH3_NH4` | none — CF ammonium is mole-only | R2 + R4 |
| `nitrogen_ammonia_+_ammonium` | merge → `nitrogen_ammonia` | (same term) | none | R4 |
| `specific_humidity` | `specific_humidity` | — (extension) | `specific_humidity` [1] (g/kg ✓) | R1 |
| `runoff` | `runoff` | — (extension) | `runoff_amount` [kg m-2] (mm ✓) | R1 |
| `snow_cover` | `snow_cover` | — (extension) | `surface_snow_area_fraction` [1] | R1 |
| `surface_emissivity` | `surface_emissivity` | — (extension) | `surface_longwave_emissivity` [1] | R1 |
| `particulate_matter_10` | `particulate_matter_10` | — (extension) | `mass_concentration_of_pm10_ambient_aerosol_particles_in_air` [kg m-3] (µg/m³ ✓) | R1 |
| `particulate_matter_2.5` | `particulate_matter_2.5` | — (extension) | `mass_concentration_of_pm2p5_ambient_aerosol_particles_in_air` [kg m-3] | R1 |
| `air_ventilation_index` | `air_ventilation_index` | — (extension) | none | R1 |
| `allocation` | `allocation` | — (extension) | none | R1 |
| `water_use` | `water_use` | — (ODM2 has only `waterUse<Sector>` subcategories) | none | R1 |
| `snow_depth` | → `snowfall` (rename; misnamed in tethys — source is WRF `SNOWNC` accumulated snowfall) | — (extension; ODM2 `snowDepth` means the *other* thing) | `lwe_thickness_of_snowfall_amount` [m] (mm LWE ✓) | R3→R1 |
| `naturalised_streamflow` | → `streamflow` + `product_code`/`method` discriminators | — | `water_volume_transport_in_river_channel` [m3 s-1] | R5 |
| `recharge_groundwater` | `recharge_groundwater` | `rechargeGroundwater` | `subsurface_runoff_amount` [kg m-2] as land-model-drainage proxy (or none) | R5 |

## Full inventory (auto-generated — do not hand-edit; regenerate via the sweep script)

| tethys parameter | features | units | tethys cf_standard_name (hint, unvalidated) | agg stats | used by |
|---|---|---|---|---|---|
| `air_ventilation_index` | atmosphere | m^2/s | `air_pressure` | instantaneous | 2: era5(grid), tethys-wrf(grid) |
| `albedo` | pedosphere |  | `surface_albedo` | instantaneous | 2: era5(grid), tethys-wrf(grid) |
| `allocation` | groundwater, waterway | m^3 | — | cumulative, mean | 1: es-hilltop |
| `barometric_pressure` | atmosphere | hPa | `air_pressure`, `air_pressure_at_mean_sea_level` | instantaneous, mean | 5: era5(grid), metservice(grid), tethys-wrf(grid), weather-api-forecasts, yr-forecasts |
| `chloride_dissolved` | groundwater, still_waters, waterway | mg/l | — | sporadic | 3: ecan-env, gdc, gwrc |
| `coliform_fecal` | groundwater, still_waters, waterway | cfu/100ml | — | sporadic | 3: ecan-env, gdc, gwrc |
| `coliform_total` | groundwater, still_waters, waterway | MPN/100mL, number/100ml | — | sporadic | 4: ecan-env, gdc, gwrc, niwa-sos |
| `e-coli` | groundwater, still_waters, waterway | MPN/100mL, MPN/100ml | — | sporadic | 4: ecan-env, gdc, gwrc, niwa-sos |
| `electrical_conductivity` | atmosphere, groundwater, still_waters, waterway | mS/m, uS/cm | `water_surface_height_above_reference_datum` | cumulative, mean, sporadic | 5: ecan-env, gdc, gwrc, hbrc, niwa-sos |
| `evaporation` | atmosphere | mm | `lwe_thickness_of_water_evaporation_amount` | cumulative | 1: era5(grid) |
| `gage_height` | waterway | m, mm | `water_surface_height_above_reference_datum` | continuous, instantaneous, mean, sporadic | 11: ecan-env, es-hilltop, gdc, gwrc, hbrc, hrc, mdc, niwa-sos, orc-env, tasman-dc, trc |
| `ground_heat_flux` | pedosphere | W/m^2 | `downward_heat_flux_in_soil` | cumulative | 2: era5(grid), tethys-wrf(grid) |
| `groundwater_depth` | groundwater | m | `water_table_depth` | mean, sporadic | 6: ecan-env, gdc, hbrc, mdc, tasman-dc, trc |
| `latent_heat_flux` | pedosphere | W/m^2 | `downward_heat_flux_in_soil` | cumulative | 2: era5(grid), tethys-wrf(grid) |
| `naturalised_streamflow` | waterway | m^3 | `water_volume_transport_in_river_channel` | mean | 1: es-hilltop |
| `nitrogen_ammonia` | groundwater | mg/l | — | sporadic | 2: gdc, gwrc |
| `nitrogen_ammonia_+_ammonium` | still_waters, waterway | mg/l | — | sporadic | 2: gdc, gwrc |
| `nitrogen_nitrate` | groundwater, still_waters, waterway | mg/l | — | continuous, mean, sporadic | 7: ecan-env, gdc, gwrc, hrc, mdc, niwa-sos, tasman-dc |
| `nitrogen_nitrite` | groundwater, still_waters, waterway | mg/l | — | sporadic | 1: gwrc |
| `nitrogen_total` | groundwater, still_waters, waterway | mg/l | — | sporadic | 3: gdc, gwrc, niwa-sos |
| `oxygen_dissolved` | groundwater, still_waters, waterway | mg/l | — | continuous, mean, sporadic | 9: ecan-env, gdc, gwrc, hbrc, hrc, mdc, niwa-sos, tasman-dc, trc |
| `particulate_matter_10` | atmosphere | ug/m^3 | `mass_fraction_of_pm10_particulate_organic_matter_dry_aerosol_particles_in_air` | instantaneous, mean | 1: ecan-env |
| `particulate_matter_2.5` | atmosphere | ug/m^3 | `mass_fraction_of_pm2p5_particulate_organic_matter_dry_aerosol_particles_in_air` | instantaneous, mean | 1: ecan-env |
| `phosphorus_orthophosphate` | groundwater, still_waters, waterway | mg/l | — | sporadic | 2: gdc, gwrc |
| `phosphorus_orthophosphate_dissolved` | groundwater, still_waters, waterway | mg/l | — | sporadic | 2: ecan-env, niwa-sos |
| `phosphorus_total` | groundwater, still_waters, waterway | mg/l | — | sporadic | 4: ecan-env, gdc, gwrc, niwa-sos |
| `potential_et` | atmosphere | mm | `water_evapotranspiration_flux` | cumulative | 1: era5(grid) |
| `precipitation` | atmosphere | mm | `precipitation_amount` | cumulative | 22: bop-env, ecan-env, ecmwf-forecasts, era5(grid), es-hilltop, fenz, gdc, gwrc, hbrc, hrc, mdc, metservice, metservice(grid), ms-hutt, niwa-sos, orc-env, tasman-dc, tethys-wrf(grid), trc, weather-api-forecasts, west-coast-env, yr-forecasts |
| `radiation_incoming_longwave` | atmosphere | W/m^2 | `surface_downwelling_longwave_flux_in_air` | cumulative | 3: era5(grid), metservice(grid), tethys-wrf(grid) |
| `radiation_incoming_shortwave` | atmosphere | W/m^2 | `surface_downwelling_shortwave_flux_in_air` | cumulative | 3: era5(grid), metservice(grid), tethys-wrf(grid) |
| `recharge_groundwater` | pedosphere | mm | `subsurface_runoff_amount` | cumulative | 2: era5(grid), tethys-wrf(grid) |
| `relative_humidity` | atmosphere | %, m^3/m^3 | `relative_humidity` | instantaneous, mean | 9: ecan-env, era5(grid), fenz, metservice, metservice(grid), niwa-sos, tethys-wrf(grid), weather-api-forecasts, yr-forecasts |
| `runoff` | pedosphere | mm | `runoff_amount` | cumulative | 2: era5(grid), tethys-wrf(grid) |
| `snow_cover` | atmosphere | m^2/m^2 | `surface_snow_area_fraction` | cumulative | 1: metservice(grid) |
| `snow_depth` | atmosphere | mm | `thickness_of_snowfall_amount` | cumulative | 3: era5(grid), metservice(grid), tethys-wrf(grid) |
| `specific_humidity` | atmosphere | g/kg | `specific_humidity` | instantaneous | 3: era5(grid), metservice(grid), tethys-wrf(grid) |
| `streamflow` | waterway | m^3, m^3/s | `water_volume_transport_in_river_channel` | continuous, instantaneous, mean, sporadic | 16: bop-env, ccc, ecan-env, es-hilltop, gdc, gwrc, hbrc, hrc, manawa, mdc, niwa-sos, niwa-web-portal, orc-env, tasman-dc, trc, west-coast-env |
| `surface_emissivity` | pedosphere |  | `surface_longwave_emissivity` | instantaneous | 2: era5(grid), tethys-wrf(grid) |
| `temperature` | atmosphere, groundwater, pedosphere, still_waters, waterway | degC | `air_temperature`, `sea_water_temperature`, `soil_temperature` | continuous, instantaneous, mean, sporadic | 15: ecan-env, era5(grid), fenz, gwrc, hbrc, hrc, mdc, metservice, metservice(grid), niwa-sos, tasman-dc, tethys-wrf(grid), trc, weather-api-forecasts, yr-forecasts |
| `temperature_dew_point` | atmosphere | degC | `dew_point_temperature` | instantaneous | 3: era5(grid), metservice(grid), tethys-wrf(grid) |
| `turbidity` | still_waters, waterway | FNU, NTU | `sea_water_turbidity` | continuous, mean, sporadic | 8: gdc, gwrc, hbrc, hrc, mdc, niwa-sos, tasman-dc, trc |
| `velocity` | waterway | m/s | — | sporadic | 4: es-hilltop, hbrc, hrc, tasman-dc |
| `volumetric_water_content` | pedosphere | m^3/m^3 | `mass_content_of_water_in_soil`, `soil_moisture` | instantaneous, mean | 6: era5(grid), fenz, metservice, metservice(grid), niwa-sos, tethys-wrf(grid) |
| `water_level` | groundwater | m | `water_table_depth` | mean, sporadic | 4: es-hilltop, gdc, hbrc, hrc |
| `water_use` | groundwater, waterway | m^3 | `water_use` | cumulative, mean | 1: es-hilltop |
| `wind_direction` | atmosphere | deg, m/s | `wind_from_direction` | instantaneous, mean | 9: ecan-env, era5(grid), fenz, metservice, metservice(grid), niwa-sos, tethys-wrf(grid), weather-api-forecasts, yr-forecasts |
| `wind_speed` | atmosphere | m/s | `wind_speed` | instantaneous, mean | 9: ecan-env, era5(grid), fenz, metservice, metservice(grid), niwa-sos, tethys-wrf(grid), weather-api-forecasts, yr-forecasts |
