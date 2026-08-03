#!/usr/bin/env python3
"""
prepare_deposit.py  —  Build a clean, tiered data/code deposit for the
"Invisible Losses" (Eaton Fire social-infrastructure) study.

WHAT IT DOES
  1. Sorts every input file into: open / restricted / excluded (with reasons).
  2. Clears ALL outputs from the notebooks you keep (their saved outputs embed
     administrator names, phone numbers, addresses, complaint histories).
  3. Drops out-of-scope categories (churches, foster/adoption) and raw statewide
     licensing pulls, geocoder I/O, ArcGIS project files, and scratch notebooks.
  4. Builds the OPEN aggregates and a public schools crosswalk.
  5. Builds the RESTRICTED de-identified care crosswalk + generalized points
     (name / license number / address / exact coordinates removed; tract kept).
  6. Writes requirements.txt, README, data dictionary, data-availability
     statement, license note, and a manifest.
  7. Runs a final PII leak scan over everything staged for public release and
     ABORTS if anything sensitive slipped through.

USAGE
  Put a COPY of all project files in one folder, then:
      python3 prepare_deposit.py --input /path/to/your/copy --output DEPOSIT
  (defaults: --input .  --output DEPOSIT)

Nothing is deleted from your inputs; everything is written under --output.
"""

import argparse, csv, json, os, re, shutil, sys, random
from pathlib import Path

random.seed(42)  # stable surrogate-id shuffling

# ----------------------------------------------------------------------------- config
DROP_ASSESSED_VALUE = True     # drop per-home assessed value from DINS (data minimization)
COORD_ROUND = 2                # decimal places for generalized care coords (~1.1 km)

# Category -> geocoder output file (headerless Census geocoder; col0=facility#, col10=tract)
GEOCODE_FILES = {
    "Eldercare":         "eldercare_eaton_geocoded.csv",
    "Adult Residential": "adult_res_eaton_geocoded.csv",
    "Childcare":         "childcare_eaton_geocoded.csv",
}
# Per-category impacted facility file + its capacity column name
CARE_FILES = {
    "Eldercare":         ("eldercare_impacted_facilities_mappable.csv", "Facility Capacity"),
    "Adult Residential": ("adult_residential_impacted_facilities.csv",  "Facility Capacity"),
    "Childcare":         ("childcare_impacted_facilities.csv",          "Facility Capacity"),
}
HEALTHCARE_FILE = ("healthcare_impacted_facilities.csv", "CAPACITY")  # aggregate-only (n small)

MATCH_METHOD = {
    "School":            "parcel match + enrollment (CDE x CAL FIRE DINS)",
    "Eldercare":         "address linkage (CDSS licensing x DINS)",
    "Adult Residential": "address linkage (CDSS licensing x DINS)",
    "Childcare":         "address linkage (CDSS licensing x DINS)",
    "Healthcare":        "coordinate intersection (CDPH x DINS)",
}
CAT_PREFIX = {"Eldercare": "ELD", "Adult Residential": "ADR", "Childcare": "CHC"}

# ---- file classification (exact names / patterns) ----
EXCLUDE = {
    # out-of-scope for the paper
    "01_church_analysis.ipynb": "out of scope (churches not in final paper)",
    "06_foster_family_agencies.ipynb": "out of scope (foster/adoption not in final paper)",
    "churches_map.gpkg": "out of scope (churches)",
    "Untitled.ipynb": "scratch notebook; leaks local paths + another study's named data",
    # raw statewide pulls / full-detail with admin names, phones, complaint histories
    "eldercare_clean.csv": "raw statewide CDSS pull (administrator names, phones, complaints)",
    "eldercare_inside_eaton_perimeter.csv": "full-detail licensing (admin/phone/complaints)",
    # combined layers that embed care names + exact coordinates (regenerated, generalized)
    "eaton_social_infra.gpkg": "combined layer with care names/coords (regenerated generalized)",
    "eaton_social_infra_v2.gpkg": "superseded combined layer with care names/coords",
    "eaton_social_infra_v4.gpkg": "superseded combined layer with care names/coords",
    "eaton_social_infra_v5.gpkg": "combined layer with care names/coords (regenerated generalized)",
    # ArcGIS project/toolbox may embed local filesystem paths
    "eaton.aprx": "ArcGIS project may embed local paths; not needed for reproducibility",
    "eaton.atbx": "ArcGIS toolbox; not needed for reproducibility",
}
EXCLUDE_PATTERNS = [
    (re.compile(r"_geocoded\.csv$"),            "geocoder output (address + coordinates)"),
    (re.compile(r"_census_input\.csv$"),        "geocoder input (address list)"),
    (re.compile(r"_census_geocode_input\.csv$"),"geocoder input (address list)"),
    (re.compile(r"eldercare_eaton_addresses\.csv$"), "address list"),
    (re.compile(r"^FosterFamilyAgencies.*\.csv$"),   "raw statewide foster/adoption pull (PII)"),
    (re.compile(r"^eaton_social_infra\.(shp|dbf|shx|prj|cpg)$"),
                                                "combined shapefile with care names/coords"),
    # per-category facility microdata (names/license#/address/coords) -> not copied; generalized instead
    (re.compile(r"_impacted_facilities\.(csv|geojson)$"), "facility microdata (generalized instead)"),
    (re.compile(r"_destroyed_facilities\.(csv|geojson)$"),"facility microdata (generalized instead)"),
    (re.compile(r"_impacted_facilities_mappable\.csv$"),  "facility microdata (generalized instead)"),
    (re.compile(r"^healthcare_impacted_facilities\."),    "facility microdata (aggregate only)"),
    (re.compile(r"^schools_map\.gpkg$"),        "regenerated as schools points csv"),
]

OPEN_AGGREGATES = [
    "eaton_broad_category_counts.csv", "eaton_percent_impacted_by_category.csv",
    "eaton_structure_type_counts.csv", "school_impact_summary.csv",
]
OPEN_SCHOOLS = [
    "calfire_assessed_school_structures.csv", "calfire_school_major_destroyed.csv",
    "calfire_school_major_parcels.csv", "calfire_school_parcels.csv",
]
OPEN_DINS = [
    "eaton_fire_only.csv", "eaton_impacted_structures.csv",
    "eaton_inaccessible_structures.csv", "eaton_major_impacts.csv",
]
OPEN_PERIMETER = ["eaton_perimeter.shp","eaton_perimeter.dbf","eaton_perimeter.shx",
                  "eaton_perimeter.prj","eaton_perimeter.cpg","eaton_perimeter.gpkg"]
NOTEBOOKS_KEEP = ["02_school_analysis.ipynb","03_elder_care_analysis.ipynb",
                  "04_adult_residential_facilities.ipynb","05_child_care_centers.ipynb",
                  "07_healthcare_analysis.ipynb","08_mapping_outputs.ipynb","fire_analysis.ipynb"]

# ----------------------------------------------------------------------------- helpers
def capacity_band(v):
    try: n = int(float(v))
    except (TypeError, ValueError): return "unknown"
    if n <= 6:  return "1-6"
    if n <= 14: return "7-14"
    if n <= 29: return "15-29"
    if n <= 49: return "30-49"
    return "50+"

def norm_facnum(s):
    s = str(s).strip().strip('"').strip()
    return s[:-2] if s.endswith(".0") else s

def load_tracts(input_dir, fname):
    """facility_number -> census tract, from headerless Census geocoder output."""
    out = {}
    p = input_dir / fname
    if not p.exists(): return out
    with open(p, newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 11:
                out[norm_facnum(row[0])] = row[10].strip()
    return out

def log(msg): print(msg)

# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=".")
    ap.add_argument("--output", default="DEPOSIT")
    ap.add_argument("--access-date", default="YYYY-MM-DD",
                    help="date you downloaded the public source snapshots")
    args = ap.parse_args()

    IN = Path(args.input).resolve()
    OUT = Path(args.output).resolve()
    if OUT.exists(): shutil.rmtree(OUT)
    open_d   = OUT / "open"
    rest_d   = OUT / "restricted"
    code_d   = OUT / "open" / "code"
    docs_d   = OUT / "open" / "docs"
    for d in [open_d/"aggregates", open_d/"crosswalks", open_d/"dins", open_d/"schools",
              open_d/"spatial", code_d, docs_d, rest_d]:
        d.mkdir(parents=True, exist_ok=True)

    manifest = []   # (path_in_deposit, tier, description)
    excluded = []   # (filename, reason)

    present = {p.name for p in IN.iterdir() if p.is_file()}

    # ---- 1. explicit + pattern exclusions -------------------------------------------
    def is_excluded(name):
        if name in EXCLUDE: return EXCLUDE[name]
        for pat, reason in EXCLUDE_PATTERNS:
            if pat.search(name): return reason
        return None

    # ---- 2. OPEN: aggregates, schools, perimeter (copied as-is) ---------------------
    for name in OPEN_AGGREGATES:
        if name in present:
            shutil.copy2(IN/name, open_d/"aggregates"/name)
            manifest.append((f"open/aggregates/{name}", "open", "aggregate counts (no PII)"))
    for name in OPEN_SCHOOLS + ["schools_inside_eaton_perimeter.csv"]:
        if name in present:
            shutil.copy2(IN/name, open_d/"schools"/name)
            manifest.append((f"open/schools/{name}", "open", "school-level (public institutions)"))
    for name in OPEN_PERIMETER:
        if name in present:
            shutil.copy2(IN/name, open_d/"spatial"/name)
            manifest.append((f"open/spatial/{name}", "open", "CAL FIRE fire perimeter (public snapshot)"))

    # ---- 3. OPEN: DINS snapshots (optionally drop assessed value) -------------------
    for name in OPEN_DINS:
        if name not in present: continue
        dst = open_d/"dins"/name
        with open(IN/name, newline="") as f:
            r = csv.reader(f); rows = list(r)
        header = rows[0]
        drop_idx = {i for i,h in enumerate(header)
                    if DROP_ASSESSED_VALUE and h.strip() == "Assessed Improved Value (parcel)"}
        with open(dst, "w", newline="") as f:
            w = csv.writer(f)
            for row in rows:
                w.writerow([c for i,c in enumerate(row) if i not in drop_idx])
        note = "DINS derivative (public, CC-BY)" + ("; assessed value dropped" if drop_idx else "")
        manifest.append((f"open/dins/{name}", "open", note))

    # ---- 4. Clear notebook outputs -> open/code ------------------------------------
    for name in NOTEBOOKS_KEEP:
        if name not in present: continue
        nb = json.load(open(IN/name))
        for c in nb.get("cells", []):
            if c.get("cell_type") == "code":
                c["outputs"] = []
                c["execution_count"] = None
        json.dump(nb, open(code_d/name, "w"), indent=1)
        manifest.append((f"open/code/{name}", "open", "analysis notebook (outputs cleared)"))

    # ---- 5. OPEN: care aggregate + schools crosswalk -------------------------------
    agg_rows = []
    def summarize(path, capcol, category):
        rows = list(csv.DictReader(open(IN/path)))
        n = len(rows)
        destroyed = sum(1 for r in rows if "Destroyed" in (r.get("* Damage","")))
        cap = 0
        for r in rows:
            try: cap += int(float(r.get(capcol) or 0))
            except ValueError: pass
        agg_rows.append({"category": category, "facilities_impacted": n,
                         "destroyed": destroyed, "capacity_beds_or_slots": cap})
    for cat,(fn,capcol) in CARE_FILES.items():
        if fn in present: summarize(fn, capcol, cat)
    if HEALTHCARE_FILE[0] in present: summarize(*HEALTHCARE_FILE, "Healthcare")
    if agg_rows:
        with open(open_d/"aggregates"/"care_facility_impacts_summary.csv","w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(agg_rows[0].keys())); w.writeheader(); w.writerows(agg_rows)
        manifest.append(("open/aggregates/care_facility_impacts_summary.csv","open",
                         "care impacts by category (aggregate, no PII)"))

    # public schools crosswalk (schools ARE public institutions)
    sp = "schools_inside_eaton_perimeter.csv"
    if sp in present:
        srows = list(csv.DictReader(open(IN/sp)))
        with open(open_d/"crosswalks"/"schools_damage_crosswalk.csv","w",newline="") as f:
            w = csv.writer(f); w.writerow(["school_name","enrollment","census_tract","match_method"])
            for r in srows:
                w.writerow([r.get("Name",""), r.get("Enrollment",""), "", MATCH_METHOD["School"]])
        manifest.append(("open/crosswalks/schools_damage_crosswalk.csv","open",
                         "school-level damage crosswalk (public institutions)"))

    # ---- 6. RESTRICTED: de-identified care crosswalk + generalized points ----------
    tracts = {cat: load_tracts(IN, GEOCODE_FILES[cat]) for cat in GEOCODE_FILES}
    xwalk, gpts = [], []
    for cat,(fn,capcol) in CARE_FILES.items():
        if fn not in present: continue
        rows = list(csv.DictReader(open(IN/fn)))
        idx = list(range(len(rows))); random.shuffle(idx)   # break source ordering
        for k, i in enumerate(idx, 1):
            r = rows[i]
            sid = f"{CAT_PREFIX[cat]}-{k:02d}"
            tract = tracts.get(cat, {}).get(norm_facnum(r.get("Facility Number","")), "")
            band = capacity_band(r.get(capcol))
            dmg  = r.get("* Damage","")
            xwalk.append({"surrogate_id": sid, "category": cat, "capacity_band": band,
                          "match_method": MATCH_METHOD[cat], "damage_class": dmg,
                          "census_tract": tract})
            try:
                lat = round(float(r.get("latitude")), COORD_ROUND)
                lon = round(float(r.get("longitude")), COORD_ROUND)
            except (TypeError, ValueError):
                lat = lon = ""
            gpts.append({"surrogate_id": sid, "category": cat, "capacity_band": band,
                         "damage_class": dmg, "lat_generalized": lat, "lon_generalized": lon,
                         "census_tract": tract})
    if xwalk:
        with open(rest_d/"care_facilities_deidentified_crosswalk.csv","w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(xwalk[0].keys())); w.writeheader(); w.writerows(xwalk)
        manifest.append(("restricted/care_facilities_deidentified_crosswalk.csv","restricted",
                         "care facilities: no name/license#/address/coords; tract + capacity band"))
    if gpts:
        with open(rest_d/"care_points_generalized.csv","w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(gpts[0].keys())); w.writeheader(); w.writerows(gpts)
        manifest.append(("restricted/care_points_generalized.csv","restricted",
                         f"care points rounded to {COORD_ROUND} dp (~1 km); names removed"))

    # ---- 7. docs ------------------------------------------------------------------
    write_docs(docs_d, OUT, args.access_date, agg_rows)
    # requirements.txt at deposit root of code
    (code_d/"requirements.txt").write_text(
        "pandas>=2.0\ngeopandas>=0.14\nshapely>=2.0\npyogrio>=0.7\n", encoding="utf-8")
    manifest.append(("open/code/requirements.txt","open","python environment"))

    # ---- 8. log excluded ----------------------------------------------------------
    for name in sorted(present):
        reason = is_excluded(name)
        if reason: excluded.append((name, reason))

    with open(OUT/"MANIFEST.csv","w",newline="") as f:
        w = csv.writer(f); w.writerow(["path","tier","description"]); w.writerows(manifest)
    with open(OUT/"EXCLUDED.csv","w",newline="") as f:
        w = csv.writer(f); w.writerow(["filename","reason_not_deposited"]); w.writerows(excluded)

    # ---- 9. leak scan over PUBLIC material ----------------------------------------
    hits = leak_scan(open_d)
    print("\n=== SUMMARY ===")
    print(f"open files:       {sum(1 for m in manifest if m[1]=='open')}")
    print(f"restricted files: {sum(1 for m in manifest if m[1]=='restricted')}")
    print(f"excluded files:   {len(excluded)}")
    if hits:
        print("\n!!! LEAK SCAN FAILED — do not publish open/ until resolved:")
        for h in hits[:20]: print("   ", h)
        sys.exit(1)
    print("leak scan: PASS (no phones / admin / licensee / local paths in open/)")
    print(f"\nDeposit written to: {OUT}")

# ----------------------------------------------------------------------------- leak scan
def leak_scan(open_dir):
    """Abort conditions:
       - phone-number values or local '/Users/' paths anywhere (real values/paths)
       - CDSS PII column-NAMES appearing with data: in any non-notebook file, or in
         notebook OUTPUTS (their presence in notebook code is a benign column reference).
    """
    phone = re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}")
    always = re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}|/Users/")   # real values / local paths
    pii_cols = ["Facility Administrator","Licensee","Facility Telephone","Complaint Info"]
    hits = []
    for p in open_dir.rglob("*"):
        if not p.is_file(): continue
        if p.suffix.lower() in {".gpkg",".shp",".dbf",".shx",".prj",".cpg"}: continue
        try: txt = p.read_text(errors="ignore")
        except Exception: continue

        if always.search(txt):
            hits.append(f"phone/local-path value in {p.name}")

        if p.suffix.lower() == ".ipynb":
            # only OUTPUT text matters for PII-column leakage (code refs are fine)
            try: nb = json.loads(txt)
            except Exception: nb = {"cells": []}
            otext = ""
            for c in nb.get("cells", []):
                for o in c.get("outputs", []):
                    if "text" in o: otext += "".join(o["text"])
                    for v in (o.get("data") or {}).values():
                        otext += "".join(v) if isinstance(v, list) else str(v)
            for col in pii_cols:
                if col in otext: hits.append(f"'{col}' in OUTPUT of {p.name} (outputs not cleared)")
        else:
            for col in pii_cols:
                if col in txt: hits.append(f"'{col}' column in {p.name}")
    return hits

# ----------------------------------------------------------------------------- docs
def write_docs(docs_d, OUT, access_date, agg_rows):
    readme = f"""# Invisible Losses — Eaton Fire social-infrastructure data & code

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
- CAL FIRE DINS damage inspection data — CA Open Data, CC-BY. Snapshot accessed {access_date}.
- School locations & enrollment — CA Dept. of Education (CDE) school directory. Accessed {access_date}.
- Licensed care facilities — CA Dept. of Social Services (CDSS) Community Care Licensing
  and CA Dept. of Public Health (CDPH). Accessed {access_date}. Redistributed only in
  de-identified/aggregate form.
- Fire perimeter — CAL FIRE. Snapshot accessed {access_date}.

## Interviews
Semi-structured interview data are NOT included. They are human-subjects data held under
restricted, IRB-controlled access; contact the author. See DATA_AVAILABILITY.md.

## Reproducing
See open/code/ (run notebooks in numeric order) and open/code/requirements.txt.
"""
    (docs_d/"README.md").write_text(readme, encoding="utf-8")

    dd = """# Data dictionary

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
"""
    (docs_d/"DATA_DICTIONARY.md").write_text(dd, encoding="utf-8")

    das = """# Data availability statement (draft for Climate Risk Management)

Aggregate data, school- and structure-level records derived from public sources
(CAL FIRE DINS, CA Dept. of Education), the fire perimeter, and all analysis code are
openly available at [REPOSITORY DOI].

De-identified, generalized facility-level data for licensed care facilities (elder-care,
adult residential, and childcare) are available from the author on reasonable request
under a data-use agreement. Facility-level microdata are not published openly because
these facilities serve vulnerable and in some cases legally protected populations and
their exact locations are potentially re-identifying.

Semi-structured interview data are not publicly available because they contain
identifiable information about participants; de-identified excerpts may be available
from the author under the terms of the study's IRB approval.

Underlying licensing data are maintained by the California Departments of Social Services
and Public Health; DINS data are published by CAL FIRE under CC-BY.
"""
    (docs_d/"DATA_AVAILABILITY.md").write_text(das, encoding="utf-8")

    (OUT/"LICENSE.txt").write_text(
        "Data (open tier): CC-BY 4.0, with attribution to original public sources.\n"
        "Code: MIT License.\n", encoding="utf-8")

if __name__ == "__main__":
    main()
