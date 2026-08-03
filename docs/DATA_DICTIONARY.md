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
