# Invisible Losses — Eaton Fire social-infrastructure data & code

Cite this dataset: https://doi.org/10.5281/zenodo.21781686

Replication materials for the study of social-infrastructure loss in the January 2025
Eaton Fire (Altadena, California), using an institution-specific matching of licensed
facilities to CAL FIRE damage-inspection (DINS) records. 

## Tiers
- **open/** — publicly shareable: aggregate tables, school- and DINS-level data
  (already public sources), the fire perimeter, and analysis code (outputs cleared).
- **restricted/** — available on request under a data-use agreement: de-identified,
  generalized facility-level care data (no names, license numbers, addresses, or exact
  coordinates). Withheld here because Adult Residential, RCFE, and childcare facilities
  serve vulnerable and in some cases legally protected populations.
- **Not included** — raw statewide licensing pulls, geocoder inputs/outputs, ArcGIS
  project files, out-of-scope categories, and all interview material (see below).

## Provenance & licenses
- CAL FIRE DINS damage inspection data — CA Open Data, CC-BY. Snapshot accessed 2026-05-17.
- School locations & enrollment — CA Dept. of Education (CDE) school directory. Accessed 2026-05-17.
- Licensed care facilities — CA Dept. of Social Services (CDSS) Community Care Licensing
  and CA Dept. of Public Health (CDPH). Accessed 2026-05-17. Redistributed only in
  de-identified/aggregate form.
- Fire perimeter — CAL FIRE. Snapshot accessed 2026-05-17.

## Interviews
Semi-structured interview data are NOT included. They are human-subjects data held under
restricted, IRB-controlled access; contact the author. See DATA_AVAILABILITY.md.

## Reproducing
See open/code/ (run notebooks in numeric order) and open/code/requirements.txt.
