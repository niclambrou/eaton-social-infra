# Data dictionary

## open/aggregates/care_facility_impacts_summary.csv
category, facilities_impacted, destroyed, capacity_beds_or_slots

## open/crosswalks/schools_damage_crosswalk.csv
school_name (public), enrollment, census_tract, match_method

## restricted/care_facilities_deidentified_crosswalk.csv
surrogate_id  — arbitrary within-category ID (not a license number)
category      — Eldercare | Adult Residential | Childcare
capacity_band — 1-6 | 7-14 | 15-29 | 30-49 | 50+
match_method  — how the facility was matched to DINS
damage_class  — DINS class (Destroyed (>50%), Major (25-50%), Affected (>0-10%))
census_tract  — 2020 census tract (from Census geocoder)
  (NO name, license number, address, or coordinates.)

## restricted/care_points_generalized.csv
As above, plus lat_generalized / lon_generalized rounded to ~1 km. Mapping only.

## open/dins/*.csv
CAL FIRE DINS records (public). Assessed parcel value removed. See CAL FIRE dictionary.

## open/aggregates/verified/table3_corrected.csv
infrastructure_type, operating_facilities_region, matched_to_DINS_parcel,
destroyed_operating, destroyed_capacity, notes — corrected aggregates (no PII)

## restricted/deidentified/verified_care_deidentified_crosswalk.csv
surrogate_id  — arbitrary within-category ID (independent of the retired
                proximity-era crosswalk's ID space; not a license number)
category      — Eldercare | Adult Residential | Childcare | Healthcare
capacity_band — 1-6 | 7-14 | 15-29 | 30-49 | 50-119 | 120+
operating_at_fire — operating on 2025-01-07 per licensing records
match_tier    — pass1 | pass2_nodir | adjudicated | unmatched
damage_class  — DINS worst-damage class, or "no inspection record at parcel"
license_flag  — corroboration/anomaly flag from license history
  (NO name, license number, address, or coordinates.)

## restricted/deidentified/verified_adjudication_log_deidentified.csv
surrogate_id, category, capacity_band, resolution, resolved_damage,
corroboration — evidence summary for each manual adjudication, written
without names, addresses, or license numbers.

## restricted/deidentified/verified_care_points_generalized.csv
surrogate_id, category, damage_class, lat/lon rounded to 2 dp (~1.1 km).
Mapping only.

## (local only, never deposited)
restricted/facility_damage_verified.csv, restricted/adjudications.csv,
restricted/adjudication_queue.csv, restricted/eaton_social_infra_verified.gpkg
— identified working files (names, license numbers, addresses, exact
coordinates). Gitignored; shared only under a data-use agreement.
