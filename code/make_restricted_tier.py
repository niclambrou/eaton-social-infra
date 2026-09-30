#!/usr/bin/env python3
"""
make_restricted_tier.py — build the de-identified, on-request restricted-tier
files for the VERIFIED (parcel-address) pipeline outputs, following the same
conventions as prepare_deposit.py (surrogate IDs, capacity bands, generalized
coordinates; no names, license numbers, addresses, or exact coordinates).

Inputs  (restricted/, gitignored — identified working files)
    facility_damage_verified.csv
    adjudications.csv
    eaton_social_infra_verified.gpkg   (optional; for generalized points)

Outputs (restricted/deidentified/, gitignored — shared on request under DUA)
    verified_care_deidentified_crosswalk.csv
        surrogate_id, category, capacity_band, operating_at_fire, match_tier,
        damage_class, license_flag
    verified_adjudication_log_deidentified.csv
        surrogate_id (where the facility appears in the crosswalk), category,
        capacity_band, resolution, mechanism, corroboration
    verified_care_points_generalized.csv
        surrogate_id, category, damage_class, lat/lon rounded to 2 dp (~1.1 km)

Surrogate IDs are seeded-stable across runs of THIS script but are an
independent ID space from the original deposit's crosswalk (the original was
built from the superseded proximity pipeline and is retired by the errata).
"""
from __future__ import annotations

import random
from pathlib import Path

import pandas as pd

random.seed(42)

REPO = Path(__file__).resolve().parent.parent
RESTRICTED = REPO / "restricted"
OUT = RESTRICTED / "deidentified"

CAT_PREFIX = {"Eldercare": "ELD", "Adult Residential": "ADR",
              "Childcare": "CHC", "Healthcare": "HLT"}
BANDS = [(6, "1-6"), (14, "7-14"), (29, "15-29"), (49, "30-49"),
         (119, "50-119"), (10**9, "120+")]



def band(cap) -> str:
    try:
        c = float(cap)
    except (TypeError, ValueError):
        return "unknown"
    for hi, label in BANDS:
        if c <= hi:
            return label
    return "unknown"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fac = pd.read_csv(RESTRICTED / "facility_damage_verified.csv",
                      dtype={"facility_number": str})

    # stable, shuffled surrogate ids within category
    fac = fac.sort_values(["category", "facility_number"]).reset_index(drop=True)
    sur = {}
    for cat, grp in fac.groupby("category"):
        idx = list(grp.index)
        random.shuffle(idx)
        for n, i in enumerate(idx, 1):
            sur[fac.at[i, "facility_number"]] = f"{CAT_PREFIX.get(cat, 'FAC')}-{n:03d}"
    fac["surrogate_id"] = fac["facility_number"].map(sur)

    cross = pd.DataFrame({
        "surrogate_id": fac["surrogate_id"],
        "category": fac["category"],
        "capacity_band": fac["capacity"].map(band),
        "operating_at_fire": fac["operating_at_fire"],
        "match_tier": fac["match_tier"],
        "damage_class": fac["worst_damage"].fillna("no inspection record at parcel"),
        "license_flag": fac["license_flag"].fillna(""),
    }).sort_values(["category", "surrogate_id"])
    cross.to_csv(OUT / "verified_care_deidentified_crosswalk.csv", index=False)

    # The identified adjudication file carries pre-written de-identified
    # summary columns (resolution_deid, corroboration_deid) so that no
    # identifying key ever appears in this public script.
    adj = pd.read_csv(RESTRICTED / "adjudications.csv", dtype=str)
    rows = []
    for _, r in adj.iterrows():
        res = r.get("resolution_deid") or "see identified log"
        corrob = r.get("corroboration_deid") or "see identified log"
        capacity = fac.loc[fac["facility_number"] == r["facility_number"], "capacity"]
        rows.append({
            "surrogate_id": sur.get(r["facility_number"], "n/a"),
            "category": r["category"],
            "capacity_band": band(capacity.iloc[0]) if len(capacity) else "unknown",
            "resolution": res,
            "resolved_damage": ("" if pd.isna(r.get("resolved_damage"))
                                else r.get("resolved_damage")),
            "corroboration": corrob,
        })
    pd.DataFrame(rows).to_csv(
        OUT / "verified_adjudication_log_deidentified.csv", index=False)

    gpkg = RESTRICTED / "eaton_social_infra_verified.gpkg"
    if gpkg.exists():
        import geopandas as gpd
        g = gpd.read_file(gpkg)
        care = g[g["category"].isin(
            ["Elder care", "Adult residential/group home", "Childcare",
             "Healthcare"])].copy()
        name_to_sur = dict(zip(fac["facility_name"], fac["surrogate_id"]))
        care["surrogate_id"] = care["institution_name"].map(name_to_sur)
        pts = pd.DataFrame({
            "surrogate_id": care["surrogate_id"],
            "category": care["category"],
            "damage_class": care["damage_class"],
            "lat_generalized": care["latitude"].round(2),
            "lon_generalized": care["longitude"].round(2),
        })
        pts.to_csv(OUT / "verified_care_points_generalized.csv", index=False)

    print(f"wrote {len(cross)} crosswalk rows, {len(rows)} adjudication rows "
          f"to {OUT}")


if __name__ == "__main__":
    main()
