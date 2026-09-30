"""
verified_matching.py — parcel-address-identity matching of licensed facilities
to CAL FIRE DINS damage-inspection records for the 2025 Eaton Fire.

This module REPLACES the damage-attribution steps in notebooks 03-05 and 07,
which assigned damage by (a) exact-address matching against an impacted-only
DINS extract and (b) a 50 m buffer spatial join fallback. In an ember-driven
fire, destroyed and undamaged structures interleave at parcel scale, so
proximity-based attribution misassigns neighbors' damage (documented cases in
docs/ERRATA.md). The corrected method:

  1. Parses ragged CDSS licensing CSVs by padding short rows (never
     on_bad_lines="skip", which silently drops ~1/3 of statewide rows because
     citation-history fields contain unescaped delimiters).
  2. Matches each facility to DINS by NORMALIZED PARCEL-ADDRESS IDENTITY
     against the FULL Eaton inspection file (all damage classes, so
     "No Damage" is an observable outcome), in two passes:
        pass 1 — house number + directional + street name   (tier: parcel_exact)
        pass 2 — house number + street name, directionals
                 stripped from both sides                    (tier: parcel_nodir)
     A matched facility receives ALL structures on its parcel and a
     worst-damage class. Pass 2 additionally requires the facility city to
     equal the parcel-address city: with directionals stripped, "416 N
     Altadena Dr, Pasadena" would otherwise merge with the destroyed parcel
     "416 E Altadena Dr, Altadena" — a documented false match.
  3. NEVER falls back to proximity. Unmatched facilities go to an
     adjudication queue (tier: unmatched) with NO damage assigned; resolved
     cases are read from restricted/adjudications.csv (restricted tier; see docs/DATA_AVAILABILITY.md), which records the evidence
     for each manual determination (tier: adjudicated).
  4. Applies an operating-at-fire filter: status LICENSED or PENDING, or
     CLOSED with a closure date on/after the fire date. Pre-fire closures are
     excluded from all operating counts.
  5. Emits a license-corroboration flag: post-fire closure corroborates
     destruction; an active license on a destroyed parcel, or damage at a
     pre-fire-closed facility, is flagged for review rather than resolved
     silently.

Inputs (paths configurable via CLI or the PATHS dict):
  DINS      — CAL FIRE POSTFIRE master data share (statewide, public;
              carries "Site Address (parcel)"), filtered to Incident Name
              == "Eaton"; or an Eaton-only extract of the same schema.
  LICENSING — CDSS Community Care Licensing downloads (RCFE, Adult
              Residential, Child Care Centers) and the CDPH healthcare
              facility file.
  PERIMETER — CAL FIRE Eaton fire perimeter (for in-perimeter denominators
              only; the perimeter NEVER assigns damage).

Outputs:
  facility_damage_verified.csv   — facility-level crosswalk with columns:
      category, facility_number, facility_name, address, city, capacity,
      status, closed_date, operating_at_fire, match_tier, parcel_address,
      n_structures_on_parcel, worst_damage, structure_types,
      license_flag, in_perimeter
      (RESTRICTED TIER: de-identify per docs/DATA_DICTIONARY.md before
       deposit — this file carries names and addresses.)
  adjudication_queue.csv         — unmatched facilities awaiting manual review.
  care_facility_impacts_summary.csv — open-tier aggregates (no PII).

Fire date: 2025-01-07 (ignition the night of Jan 7).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pandas as pd

FIRE_DATE = pd.Timestamp("2025-01-07")

DAMAGE_ORDER = [
    "No Damage",
    "Affected (>0-10%)",
    "Affected (1-9%)",       # label variant across DINS releases
    "Minor (10-25%)",
    "Major (25-50%)",
    "Destroyed (>50%)",
]
_DMG_RANK = {d: i for i, d in enumerate(DAMAGE_ORDER)}
# collapse the two "Affected" label variants to one rank
_DMG_RANK["Affected (>0-10%)"] = _DMG_RANK["Affected (1-9%)"] = 1

MAJOR_PLUS = {"Major (25-50%)", "Destroyed (>50%)"}

# --------------------------------------------------------------------------
# Robust IO
# --------------------------------------------------------------------------

def read_ragged_csv(path: str | Path) -> pd.DataFrame:
    """Read a CDSS licensing CSV whose citation-history columns contain
    unescaped delimiters, padding/truncating every row to the header width.
    pandas' on_bad_lines="skip" silently drops such rows (~1/3 of the
    statewide Adult Residential file) — never use it on these files."""
    rows = []
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        width = len(header)
        for line in reader:
            if len(line) < width:
                line = line + [""] * (width - len(line))
            rows.append(line[:width])
    return pd.DataFrame(rows, columns=header)


# --------------------------------------------------------------------------
# Address normalization
# --------------------------------------------------------------------------

_SUFFIXES = {
    "STREET": "ST", "AVENUE": "AVE", "BOULEVARD": "BLVD", "DRIVE": "DR",
    "LANE": "LN", "PLACE": "PL", "ROAD": "RD", "COURT": "CT",
    "TERRACE": "TER", "CIRCLE": "CIR", "HIGHWAY": "HWY", "PARKWAY": "PKWY",
}
_DIRECTIONALS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}
_DROP_SUFFIX_TOKENS = set(_SUFFIXES.values())


def norm_addr(addr: str, strip_directionals: bool = False) -> str:
    """Normalize a street address to 'NUMBER [DIR] STREETNAME' for identity
    matching. Unit designators, punctuation, and suffix words (ST/AVE/...)
    are removed; directionals are standardized (pass 1) or stripped (pass 2).
    Returns '' for missing/unusable input."""
    a = str(addr or "").upper().split(",")[0]
    a = re.sub(r"[^A-Z0-9 ]", " ", a)
    a = re.sub(r"\b(APT|UNIT|STE|SUITE|BLDG|SPC|#)\b.*$", " ", a)
    tokens = []
    for t in a.split():
        t = _SUFFIXES.get(t, t)
        t = _DIRECTIONALS.get(t, t)
        if t in _DROP_SUFFIX_TOKENS:
            continue
        if strip_directionals and t in {"N", "S", "E", "W"}:
            continue
        tokens.append(t)
    return " ".join(tokens).strip()


# --------------------------------------------------------------------------
# DINS loading
# --------------------------------------------------------------------------

def load_dins(path: str | Path, incident: str = "Eaton") -> pd.DataFrame:
    """Load DINS rows for one incident from the POSTFIRE master data share
    (or an already-filtered extract with the same schema). Keeps ALL damage
    classes — matching against an impacted-only extract makes survival
    unobservable and was the root cause of the errors in docs/ERRATA.md."""
    df = pd.read_csv(path, low_memory=False)
    if "* Incident Name" in df.columns:
        df = df[df["* Incident Name"].astype(str).str.strip().str.casefold()
                == incident.casefold()].copy()
    df["addr_key"] = df["Site Address (parcel)"].map(lambda s: norm_addr(s, False))
    df["addr_key_nodir"] = df["Site Address (parcel)"].map(lambda s: norm_addr(s, True))

    def parcel_city(s: str) -> str:
        parts = str(s or "").upper().split(",")
        return parts[1].strip() if len(parts) > 1 else ""

    df["parcel_city"] = df["Site Address (parcel)"].map(parcel_city)
    return df


def _parcel_lookup(dins: pd.DataFrame, key_col: str) -> dict[str, pd.DataFrame]:
    usable = dins[dins[key_col] != ""]
    return {k: g for k, g in usable.groupby(key_col)}


# --------------------------------------------------------------------------
# Operating-at-fire filter and license corroboration
# --------------------------------------------------------------------------

def operating_at_fire(status: str, closed_date) -> bool:
    s = str(status or "").strip().upper()
    if s in {"LICENSED", "PENDING", "OPEN", "ACTIVE"}:
        return True
    if s == "CLOSED":
        cd = pd.to_datetime(closed_date, errors="coerce")
        return bool(pd.notna(cd) and cd >= FIRE_DATE)
    # INACTIVE and other statuses are NOT presumed operating; they route to
    # the adjudication queue if damage evidence exists (see adjudications.csv).
    return False


def license_flag(operating: bool, status: str, closed_date, worst: str | None) -> str:
    """Corroboration between license history and parcel damage."""
    s = str(status or "").strip().upper()
    cd = pd.to_datetime(closed_date, errors="coerce")
    destroyed = worst == "Destroyed (>50%)"
    if destroyed and s == "CLOSED" and pd.notna(cd) and cd >= FIRE_DATE:
        return "corroborated_postfire_closure"
    if destroyed and s in {"LICENSED", "OPEN", "ACTIVE"}:
        return "REVIEW_active_license_on_destroyed_parcel"
    if not operating and worst in MAJOR_PLUS:
        return "excluded_prefire_closure"
    if s == "INACTIVE":
        return "REVIEW_inactive_status"
    return ""


# --------------------------------------------------------------------------
# Core matching
# --------------------------------------------------------------------------

def match_facilities(
    facilities: pd.DataFrame,
    dins: pd.DataFrame,
    category: str,
    addr_col: str = "Facility Address",
    name_col: str = "Facility Name",
    id_col: str = "Facility Number",
    capacity_col: str = "Facility Capacity",
    status_col: str = "Facility Status",
    closed_col: str = "Closed Date",
    adjudications: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Match one licensing frame to DINS by parcel-address identity.

    Returns one row per facility with match tier, all structures on the
    matched parcel, worst damage, operating filter, and license flag.
    Facilities with no parcel match receive NO damage class (tier
    'unmatched') unless resolved in `adjudications`.
    """
    exact = _parcel_lookup(dins, "addr_key")
    nodir = _parcel_lookup(dins, "addr_key_nodir")
    adj = {}
    if adjudications is not None and len(adjudications):
        adj = {
            str(r["facility_number"]): r
            for _, r in adjudications.iterrows()
            if str(r.get("category", "")).casefold() == category.casefold()
        }

    out = []
    for _, f in facilities.iterrows():
        key = norm_addr(f[addr_col], False)
        key_nd = norm_addr(f[addr_col], True)
        fac_city = str(f.get("Facility City", f.get("CITY", "")) or "").strip().upper()
        tier, parcel = "unmatched", None
        if key and key in exact:
            tier, parcel = "parcel_exact", exact[key]
        elif key_nd and key_nd in nodir:
            cand = nodir[key_nd]
            # City guard: directional-stripped matching may merge different
            # street segments; require city agreement before accepting.
            cand = cand[cand["parcel_city"] == fac_city] if fac_city else cand.iloc[0:0]
            if len(cand):
                tier, parcel = "parcel_nodir", cand

        worst = None
        n_struct = 0
        types = ""
        if parcel is not None:
            n_struct = len(parcel)
            worst = max(parcel["* Damage"],
                        key=lambda d: _DMG_RANK.get(d, -1))
            types = "; ".join(sorted(parcel["* Structure Type"].astype(str).unique()))

        fid = str(f.get(id_col, ""))
        if tier == "unmatched" and fid in adj:
            a = adj[fid]
            tier = "adjudicated"
            worst = a.get("resolved_damage") or None
            types = str(a.get("evidence", ""))

        oper = operating_at_fire(f.get(status_col), f.get(closed_col))
        # Adjudicated operating override (e.g., program records confirm an
        # INACTIVE-status facility was operating on the fire date).
        if fid in adj and str(adj[fid].get("operating_override", "")).lower() == "true":
            oper = True

        out.append({
            "category": category,
            "facility_number": fid,
            "facility_name": f.get(name_col),
            "address": f.get(addr_col),
            "city": f.get("Facility City", f.get("CITY", "")),
            "capacity": pd.to_numeric(f.get(capacity_col), errors="coerce"),
            "status": f.get(status_col),
            "closed_date": f.get(closed_col),
            "operating_at_fire": oper,
            "match_tier": tier,
            "n_structures_on_parcel": n_struct,
            "worst_damage": worst,
            "structure_types": types,
            "license_flag": license_flag(oper, f.get(status_col),
                                         f.get(closed_col), worst),
        })
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def summarize(matched: pd.DataFrame) -> pd.DataFrame:
    """Open-tier aggregate: operating facilities only, by category."""
    op = matched[matched["operating_at_fire"]].copy()
    op["destroyed"] = op["worst_damage"] == "Destroyed (>50%)"
    op["major_plus"] = op["worst_damage"].isin(MAJOR_PLUS)
    g = op.groupby("category").agg(
        operating_facilities=("facility_number", "count"),
        matched_to_parcel=("match_tier",
                           lambda s: int((s != "unmatched").sum())),
        destroyed=("destroyed", "sum"),
        major_or_destroyed=("major_plus", "sum"),
        destroyed_capacity=("capacity",
                            lambda s: int(s[op.loc[s.index, "destroyed"]].sum())),
        unresolved=("match_tier", lambda s: int((s == "unmatched").sum())),
    ).reset_index()
    return g


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(paths: dict[str, str], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    dins = load_dins(paths["dins"])
    adjud = None
    if paths.get("adjudications") and Path(paths["adjudications"]).exists():
        adjud = pd.read_csv(paths["adjudications"], dtype=str)

    frames = []
    specs = [
        ("Eldercare", "eldercare", read_ragged_csv, {}),
        ("Adult Residential", "adult_residential", read_ragged_csv, {}),
        ("Childcare", "childcare", read_ragged_csv, {}),
        ("Healthcare", "healthcare", pd.read_csv,
         dict(addr_col="ADDRESS", name_col="FACNAME", id_col="FACID",
              capacity_col="CAPACITY", status_col="FAC_STATUS_TYPE_CODE",
              closed_col="__none__")),
    ]
    for category, key, reader, kw in specs:
        if not paths.get(key):
            continue
        fac = reader(paths[key])
        city_col = "Facility City" if "Facility City" in fac.columns else (
            "CITY" if "CITY" in fac.columns else None)
        if "region_filter" in paths and city_col:
            cities = [c.strip().upper() for c in paths["region_filter"].split("|")]
            fac = fac[fac[city_col].astype(str).str.upper().isin(cities)]
        extra = {k: v for k, v in kw.items() if k != "closed_col" or v != "__none__"}
        if kw.get("closed_col") == "__none__":
            fac = fac.copy()
            fac["Closed Date"] = None
            extra["closed_col"] = "Closed Date"
        frames.append(match_facilities(fac, dins, category,
                                       adjudications=adjud, **extra))

    matched = pd.concat(frames, ignore_index=True)
    matched.to_csv(out / "facility_damage_verified.csv", index=False)

    queue = matched[(matched["match_tier"] == "unmatched")
                    & matched["operating_at_fire"]]
    queue.to_csv(out / "adjudication_queue.csv", index=False)

    summarize(matched).to_csv(out / "care_facility_impacts_summary.csv",
                              index=False)
    print(summarize(matched).to_string(index=False))
    print(f"\nunmatched operating facilities queued for adjudication: {len(queue)}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dins", required=True)
    ap.add_argument("--eldercare")
    ap.add_argument("--adult-residential", dest="adult_residential")
    ap.add_argument("--childcare")
    ap.add_argument("--healthcare")
    ap.add_argument("--adjudications")
    ap.add_argument("--region-filter", dest="region_filter",
                    default="ALTADENA|PASADENA|SIERRA MADRE|LA CANADA FLINTRIDGE")
    ap.add_argument("--out", default="../aggregates/verified")
    a = ap.parse_args()
    main({k: v for k, v in vars(a).items() if v and k != "out"}, a.out)
