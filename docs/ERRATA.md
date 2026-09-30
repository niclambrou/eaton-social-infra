# ERRATA — correction of facility damage classifications (September 2026)

## Summary

An audit of the facility-to-DINS matching pipeline found that damage
classifications assigned by spatial proximity were unreliable in this fire,
in both directions. The original notebooks (03–05, 07) attributed damage by
(a) exact-address matching against an **impacted-only** DINS extract —
making "No Damage" unobservable — and (b) a **50 m buffer spatial join**
fallback. The Eaton Fire was ember-driven: destroyed and undamaged
structures interleave at parcel scale, so a geocoded facility point offset
by 10–40 m (normal for street-interpolated geocoding) routinely sits nearer
a neighbor's structure than its own. Proximity attribution therefore
inherited neighbors' damage — and, where a facility's parcel was absent
from the inspection data, silently substituted the nearest structure.

`code/verified_matching.py` replaces both steps with parcel-address-identity
matching against the full inspection file (all damage classes), a documented
manual-adjudication queue for non-matches, an operating-at-fire filter, and
license-history corroboration. See the module docstring.

Facilities are identified below by surrogate ID only (see
`docs/DATA_AVAILABILITY.md`): these are licensed care facilities, several of
them operating homes serving vulnerable residents, and this repository does
not publish facility-level identities. The identified adjudication log —
names, addresses, and parcel evidence for every determination — is
maintained in the restricted tier and is available to editors and reviewers
on request under a data-use agreement.

## Classifications overturned (previously "Destroyed" or "Affected")

| Facility (surrogate ID, capacity band) | Parcel-verified status | Corroboration |
|---|---|---|
| ADR-053 (Adult Residential, 7–14) | **No Damage** (both structures on its own parcel) | License active, no closure, 16 months post-fire; prior classification was a 50 m-buffer artifact (destroyed neighbors) |
| ADR-050 (Adult Residential, 1–6) | **No Damage** | License pending, never closed |
| ADR-030 (Adult Residential, 1–6) | **Affected (1–9%)** | Destroyed structures are neighboring parcels |
| ADR-014 (Adult Residential, 1–6) | **Minor (10–25%)** | Closed 2021 (pre-fire; excluded from operating counts regardless) |
| ADR-012 (Adult Residential, 50–119) | **Unverifiable** — no inspection record at its parcel; nearest destroyed structure is a neighbor | License active, no closure. Excluded from all counts pending site/imagery verification |
| ELD-059 (Eldercare, 1–6) | **Unverifiable** — street absent from inspection data | Closed 2021 (pre-fire) |
| ELD-065 / ELD-036 (Eldercare, 1–6 each; shared parcel) | **No Damage** at parcel (previously "Affected" via buffer) | — |

(The surrogate IDs above resolve in the restricted-tier crosswalk; ADR-053's
identified record is the case documented in the adjudication log's
"proximity false positive" entry.)

## Facilities the original pipeline missed (parcel-verified Destroyed, operating on 2025-01-07)

| Facility (surrogate ID) | Category | Capacity band | Evidence |
|---|---|---|---|
| ELD-074 | RCFE | 50–119 | Parcel exact match (commercial multi-story, Destroyed); contemporaneous reporting and state citation |
| CHC-037 | Childcare | 50–119 | Parcel exact match (religious-campus childcare); license closed post-fire |
| CHC-102 | Childcare | 30–49 | Parcel exact match; license closed post-fire |
| CHC-069 | Childcare | 50–119 | Parcel match (school campus; also counted under schools — overlap noted) |

The misses share one mechanism: the original address normalization failed on
directional/suffix variants, and the buffer fallback was only as good as the
Census geocoder's match — facilities the geocoder dropped or misplaced
disappeared from the analysis entirely. The largest miss (ELD-074) was
excluded when a 123 m geocoding offset placed its point 32 m outside the
fire perimeter polygon while its parcel lay 32 m inside.

## Corrected headline figures (destroyed while operating, parcel-verified or documented adjudication)

- Adult residential & group homes: **13 facilities, 102 beds** (was 18 / 184)
- Residential elder care (RCFE): **5 facilities, 140 beds** (was 3 / 22)
- Childcare centers: **7 facilities, 371 slots** (was 4 / 197) — 174 of the
  371 slots sit on school campuses also counted in the schools analysis
- Licensed health facilities: **2 facilities, 56 beds** (unchanged)
- **Total: 27 facilities, 669 licensed beds/slots** (was 25 / 403)

School figures were parcel/APN-based in the original analysis and are
unchanged by this correction.

## Method lesson

In ember-driven urban fires, spatial joins inherit the fire's discontinuity.
Facility-level damage claims require parcel-identity matching plus an
independent administrative signal (license closure dates, inspection visit
history); proximity generates hypotheses, never findings. Exact-address
matching is conservative — its residual error is under-matching where
licensing addresses and assessor parcel addresses diverge (shared parcels,
directional variants, unit addressing) — which is why non-matches route to
a documented adjudication queue instead of being dropped or guessed.
