#!/usr/bin/env python3
"""
09_figure2_verified.py — regenerate the Figure 2 mapping layers from the
VERIFIED facility damage classifications (aggregates/verified/), replacing
the layers previously built by 08_mapping_outputs.ipynb from the old
geocode/proximity pipeline.

Outputs
-------
restricted/eaton_social_infra_verified.gpkg
    Single point layer, same schema the ArcGIS project consumes:
    institution_name, category, damage_class, capacity, coord_source,
    in_perimeter, latitude, longitude, geometry (EPSG:4326).
    RESTRICTED TIER (gitignored): contains facility names and exact
    coordinates. Never committed; available on request under a DUA per
    docs/DATA_AVAILABILITY.md. A generalized public-safe points file is
    built by code/make_restricted_tier.py.
restricted/figure2_verified.png
    Working two-panel render (A: all social infrastructure, B: destroyed
    only) for checking symbology; final cartography remains in ArcGIS.

Coordinates
-----------
Damage attribution is parcel-address based (verified_matching.py). For
MAPPING ONLY, each matched facility is placed at the mean coordinates of
the DINS structures on its matched parcel (coord_source="dins_parcel").
Facilities with no DINS parcel (unmatched, or adjudicated on block-level
evidence) fall back to the Census-geocoded point (coord_source="geocode"),
which is retained for display only and plays no role in damage attribution
— consistent with the manuscript's Methods.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import verified_matching as vm  # noqa: E402

REPO = HERE.parent
RESTRICTED = REPO / "restricted"  # gitignored: identified facility data
# Extra input directory for files excluded from the repository (churches CSV,
# Census geocoder outputs). Set with --data-dir; everything else resolves
# from the repository itself (dins/, schools/, spatial/).
DATA_DIR = REPO / "data_local"
SEARCH_DIRS = [REPO / "dins", REPO / "schools", REPO / "spatial"]


def find_input(*names: str, required: bool = True) -> Path | None:
    """Resolve an input by filename across the repo dirs and DATA_DIR."""
    for name in names:
        for d in [*SEARCH_DIRS, DATA_DIR]:
            p = d / name
            if p.exists():
                return p
    if required:
        raise FileNotFoundError(
            f"{'/'.join(names)} not found in "
            f"{[str(d) for d in [*SEARCH_DIRS, DATA_DIR]]}; "
            "pass --data-dir pointing at a folder that contains it")
    print(f"note: optional input {'/'.join(names)} not found — skipping")
    return None

SEVERITY = ["Destroyed (>50%)", "Major (25-50%)", "Minor (10-25%)",
            "Affected (>0-10%)", "No Damage", "Inaccessible"]

CATEGORY_LABEL = {
    "Eldercare": "Elder care",
    "Adult Residential": "Adult residential/group home",
    "Childcare": "Childcare",
    "Healthcare": "Healthcare",
}

GEOCODE_FILES = {
    "Eldercare": "eldercare_eaton_geocoded.csv",
    "Adult Residential": "adult_res_eaton_geocoded.csv",
    "Childcare": "childcare_eaton_geocoded.csv",
}


def worst(damages: pd.Series) -> str:
    for s in SEVERITY:
        if (damages == s).any():
            return s
    return damages.dropna().iloc[0] if damages.notna().any() else None


def load_dins_coords(dins_path: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Mean structure coordinates per parcel-address key (both key passes)."""
    dins = vm.load_dins(dins_path)
    coords = (dins.groupby("addr_key")[["Latitude", "Longitude"]]
              .mean().reset_index())
    coords_nd = (dins.groupby(["addr_key_nodir", "parcel_city"])
                 [["Latitude", "Longitude"]].mean().reset_index())
    return coords, coords_nd


def load_geocodes() -> dict[tuple[str, str], tuple[float, float]]:
    """facility_number -> (lat, lon) from the Census geocoder outputs."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for cat, fname in GEOCODE_FILES.items():
        path = find_input(fname, required=False)
        if path is None:
            continue
        g = pd.read_csv(path, header=None, dtype=str, engine="python",
                        on_bad_lines="skip")
        # census geocoder layout: 0=id, 5="lon,lat" (matched point)
        for _, row in g.iterrows():
            pt = row.iloc[5]
            if isinstance(pt, str) and "," in pt:
                lon, lat = pt.split(",")[:2]
                try:
                    out[(cat, str(row.iloc[0]).strip())] = (float(lat), float(lon))
                except ValueError:
                    pass
    return out


def build_care_layer(coords, coords_nd, geocodes) -> pd.DataFrame:
    fac = pd.read_csv(RESTRICTED / "facility_damage_verified.csv",
                      dtype={"facility_number": str})
    fac = fac[fac["operating_at_fire"] == True].copy()  # noqa: E712

    fac["addr_key"] = fac["address"].map(vm.norm_addr)
    fac["addr_key_nodir"] = fac["address"].map(
        lambda a: vm.norm_addr(a, strip_directionals=True))
    fac["fac_city"] = fac["city"].str.upper().str.strip()

    fac = fac.merge(coords, on="addr_key", how="left")
    m2 = fac["Latitude"].isna()
    nd = fac.loc[m2, ["addr_key_nodir", "fac_city"]].merge(
        coords_nd, left_on=["addr_key_nodir", "fac_city"],
        right_on=["addr_key_nodir", "parcel_city"], how="left")
    fac.loc[m2, "Latitude"] = nd["Latitude"].to_numpy()
    fac.loc[m2, "Longitude"] = nd["Longitude"].to_numpy()
    fac["coord_source"] = "dins_parcel"

    gc_miss = fac["Latitude"].isna()
    for idx in fac.index[gc_miss]:
        key = (fac.at[idx, "category"], fac.at[idx, "facility_number"])
        if key in geocodes:
            fac.at[idx, "Latitude"], fac.at[idx, "Longitude"] = geocodes[key]
            fac.at[idx, "coord_source"] = "geocode"

    fac["damage_class"] = fac["worst_damage"].fillna("No inspection record")
    out = pd.DataFrame({
        "institution_name": fac["facility_name"],
        "category": fac["category"].map(CATEGORY_LABEL),
        "damage_class": fac["damage_class"],
        "capacity": fac["capacity"],
        "coord_source": fac["coord_source"].where(fac["Latitude"].notna()),
        "latitude": fac["Latitude"],
        "longitude": fac["Longitude"],
    })
    return out[out["latitude"].notna()]


def build_schools_layer() -> pd.DataFrame:
    s = pd.read_csv(find_input("calfire_assessed_school_structures.csv"))
    agg = (s.groupby("APN (parcel)")
           .agg(damage_class=("* Damage", worst),
                latitude=("Latitude", "mean"),
                longitude=("Longitude", "mean"),
                site=("Site Address (parcel)", "first"))
           .reset_index())
    names = pd.read_csv(find_input("schools_inside_eaton_perimeter.csv"))
    names["addr_key"] = names["Address Line 1"].map(vm.norm_addr)
    agg["addr_key"] = agg["site"].map(vm.norm_addr)
    agg = agg.merge(names[["addr_key", "Name"]].drop_duplicates("addr_key"),
                    on="addr_key", how="left")
    return pd.DataFrame({
        "institution_name": agg["Name"].fillna(agg["site"].str.title()),
        "category": "School",
        "damage_class": agg["damage_class"],
        "capacity": None,
        "coord_source": "dins_parcel",
        "latitude": agg["latitude"],
        "longitude": agg["longitude"],
    })


def build_churches_layer() -> pd.DataFrame:
    path = find_input("eaton_fire_churches.csv", required=False)
    if path is None:
        return pd.DataFrame()
    c = pd.read_csv(path)
    return pd.DataFrame({
        "institution_name": c["Name"],
        "category": "Church",
        "damage_class": "Impacted",   # unchanged from prior analysis (USC CRCC)
        "capacity": None,
        "coord_source": "source_dataset",
        "latitude": c["latitude"],
        "longitude": c["longitude"],
    })


def main() -> None:
    import geopandas as gpd
    from shapely.geometry import Point

    coords, coords_nd = load_dins_coords(find_input("eaton_fire_only.csv"))
    frames = [build_care_layer(coords, coords_nd, load_geocodes()),
              build_schools_layer(), build_churches_layer()]
    layers = pd.concat([f for f in frames if len(f)], ignore_index=True)

    gdf = gpd.GeoDataFrame(
        layers,
        geometry=[Point(xy) for xy in zip(layers["longitude"], layers["latitude"])],
        crs="EPSG:4326")

    perim = gpd.read_file(
        find_input("eaton_perimeter.gpkg", "eaton_perimeter.geojson")
    ).to_crs("EPSG:4326")
    gdf["in_perimeter"] = gdf.within(perim.union_all())

    RESTRICTED.mkdir(parents=True, exist_ok=True)
    out_gpkg = RESTRICTED / "eaton_social_infra_verified.gpkg"
    gdf.to_file(out_gpkg, driver="GPKG")
    print(f"wrote {out_gpkg} ({len(gdf)} points, "
          f"{int(gdf['in_perimeter'].sum())} in perimeter)")

    # ---------------------------------------------------------------- render
    # Styled to match the manuscript's ArcGIS figure: gray perimeter fill,
    # left-aligned gray panel titles, category dots (A) / open destroyed
    # circles (B), two-column legend lower left, miles scale bar lower right.
    import math

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.lines as mlines
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt

    cat_colors = {
        "Adult residential/group home": "#e2231a",
        "Childcare": "#f7941d",
        "Church": "#72bf44",
        "Elder care": "#a05fb4",
        "Healthcare": "#2dbfb8",
        "School": "#5b9bd5",
    }
    GRAY_TXT, EDGE = "#8a8a8a", "#d0d0ce"
    impacted_classes = ["Destroyed (>50%)", "Major (25-50%)",
                        "Minor (10-25%)", "Affected (>0-10%)", "Impacted"]

    xmin, ymin, xmax, ymax = perim.total_bounds
    pad_x, pad_y = 0.022, 0.013
    extent = (xmin - pad_x, xmax + pad_x, ymin - pad_y, ymax + pad_y)

    impacted = gdf[gdf["damage_class"].isin(impacted_classes)]
    destroyed = gdf[gdf["damage_class"] == "Destroyed (>50%)"]

    # Background street-grid texture: census tract boundaries (urban tract
    # lines follow arterials and freeways), standing in for the basemap the
    # final ArcGIS figure carries. Optional input; skipped if absent.
    tracts = None
    tract_path = find_input("access_desert_by_tract.gpkg", required=False)
    if tract_path is not None:
        t = gpd.read_file(tract_path).to_crs("EPSG:4326")
        tracts = t.cx[extent[0]:extent[1], extent[2]:extent[3]]

    fig, axes = plt.subplots(
        1, 2, figsize=(9.6, 5.3),
        gridspec_kw=dict(left=0.02, right=0.98, top=0.91, bottom=0.27,
                         wspace=0.04))
    for ax, title in zip(axes, ["A. All Social Infrastructure Impacts",
                                "B. Destroyed Social Infrastructure"]):
        ax.set_facecolor("#f0efed")
        # street-grid lines go UNDER the perimeter; the fill is slightly
        # transparent so the grid reads through it, as in the ArcGIS figure
        if tracts is not None and len(tracts):
            tracts.boundary.plot(ax=ax, color="white", linewidth=1.2,
                                 zorder=1)
        perim.plot(ax=ax, facecolor="#d6d6d4", edgecolor="#bebebc",
                   linewidth=0.8, alpha=0.66, zorder=2)
        ax.set_title(title, loc="left", color=GRAY_TXT, fontsize=10.5, pad=6)
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
        ax.set_aspect(1.0 / math.cos(math.radians((ymin + ymax) / 2)))
        ax.set_xticks([]); ax.set_yticks([])
        ax.set_xlabel(""); ax.set_ylabel("")
        for sp in ax.spines.values():
            sp.set_color(EDGE); sp.set_linewidth(0.8)

    for cat, color in cat_colors.items():
        sub = impacted[impacted["category"] == cat]
        if len(sub):
            axes[0].scatter(sub["longitude"], sub["latitude"], s=26,
                            c=color, edgecolors="white", linewidths=0.6,
                            zorder=3)
    axes[1].scatter(destroyed["longitude"], destroyed["latitude"], s=48,
                    facecolors="none", edgecolors="#4d4d4d", linewidths=1.1,
                    zorder=3)

    # legend (lower left, two columns, column-major like the original)
    handles = [mlines.Line2D([], [], marker="o", ls="", markersize=6.5,
                             markerfacecolor=c, markeredgecolor="#999999",
                             markeredgewidth=0.5, label=l)
               for l, c in cat_colors.items()]
    handles += [
        mlines.Line2D([], [], marker="o", ls="", markersize=7.5,
                      markerfacecolor="none", markeredgecolor="#4d4d4d",
                      markeredgewidth=1.1, label="Destroyed (>50%)"),
        mpatches.Patch(facecolor="#d6d6d4", edgecolor="#c2c2c0",
                       label="Eaton Fire perimeter"),
    ]
    leg = fig.legend(handles=handles, loc="lower left",
                     bbox_to_anchor=(0.04, 0.015), ncol=2, frameon=False,
                     fontsize=8.5, title="Categories", title_fontsize=11,
                     columnspacing=1.6, handletextpad=0.5, labelspacing=0.55)
    leg.get_title().set_color("#4d4d4d")
    try:
        leg._legend_box.align = "left"
    except AttributeError:
        pass

    # miles scale bar (lower right), true to the panel scale
    mi_lon = 1.0 / (69.172 * math.cos(math.radians((ymin + ymax) / 2)))
    fig.canvas.draw()  # apply aspect so panel position is final
    pos = axes[1].get_position()
    four_mi_fig = (4 * mi_lon / (extent[1] - extent[0])) * pos.width
    sax_w = four_mi_fig * 4.8 / 4.0  # x-range -0.2..4.6 around the 0..4 bar
    sax = fig.add_axes([pos.x1 - sax_w - 0.045, 0.09, sax_w, 0.05])
    sax.set_axis_off()
    sax.set_xlim(-0.2, 4.6); sax.set_ylim(0, 1)
    for x0, x1, fc in [(0, 1, "#555555"), (1, 2, "white"), (2, 4, "#555555")]:
        sax.add_patch(mpatches.Rectangle((x0, 0.45), x1 - x0, 0.22,
                                         facecolor=fc, edgecolor="#555555",
                                         linewidth=0.7))
    for x in (0, 1, 2, 4):
        sax.text(x, 0.22, str(x), ha="center", va="top", fontsize=8,
                 color="#4d4d4d")
    sax.text(4.25, 0.56, "Miles", ha="left", va="center", fontsize=8.5,
             color="#4d4d4d")
    del mi_lon  # bar is schematic; panel extent fixed above

    # simple north indicator inside panel B (lower right)
    nx = extent[0] + 0.93 * (extent[1] - extent[0])
    ny = extent[2] + 0.12 * (extent[3] - extent[2])
    r = 0.012 * (extent[1] - extent[0])
    axes[1].add_patch(mpatches.Circle((nx, ny), r, facecolor="none",
                                      edgecolor="#8a8a8a", linewidth=0.8))
    axes[1].plot([nx, nx], [ny, ny + 1.6 * r], color="#8a8a8a",
                 linewidth=0.8)

    if tracts is not None and len(tracts):
        fig.text(0.975, 0.245, "Background lines: U.S. Census tract boundaries",
                 ha="right", va="top", fontsize=7, color="#9a9a9a")

    out_png = RESTRICTED / "figure2_verified.png"
    fig.savefig(out_png, dpi=220, facecolor="white")
    print(f"wrote {out_png}")
    print(destroyed.groupby("category").size())


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(DATA_DIR),
                    help="folder holding inputs excluded from the repository "
                         "(eaton_fire_churches.csv, *_eaton_geocoded.csv)")
    DATA_DIR = Path(ap.parse_args().data_dir)
    main()
