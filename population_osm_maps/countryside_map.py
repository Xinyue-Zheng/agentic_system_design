#!/usr/bin/env python3
"""Two countryside maps over a real OpenStreetMap tile background.

Runs directly with NO command-line arguments -- everything is hardcoded below.
Renders a 30 km x 30 km window centered on a rural spot in California's Salinas
Valley (Monterey County) and writes TWO figures:

  1. pop_density_map.png   -- population-density heatmap (usa_pd_2018_1km.tif) on
     the OSM basemap, with the dense pockets circled; their lat-lon ranges are
     printed to the console.
  2. osm_features_map.png  -- OSM interest features on the OSM basemap:
       highway / railway (lines), landuse / leisure / building (polygons),
       amenity (points). Amenity POIs and residential landuse parcels are
       clustered together into "settlement" boxes wherever they sit close to
       each other, and each box's lat-lon range is annotated *on the map*.

Everything is drawn in Web Mercator (EPSG:3857) so the overlays line up exactly
with the OSM tiles (which are natively Mercator).

Needs only: rasterio, numpy, matplotlib, Pillow (URLs fetched via stdlib urllib).
"""

from __future__ import annotations

import io
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import deque

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.patches import Circle, Patch, Rectangle
from matplotlib.patches import Polygon as MplPolygon
from PIL import Image
from rasterio.windows import from_bounds

# ----------------------------------------------------------------------------
# Hardcoded configuration (edit here, not via the command line)
# ----------------------------------------------------------------------------
TIF_PATH = "usa_pd_2018_1km.tif"
CENTER_LAT = 36.31769
CENTER_LON = -121.24962
BOX_KM = 30.0            # full width/height of the (square) window in km
ZOOM = 12               # OSM tile zoom level
DENSE_FLOOR = 50.0      # a cell counts as "populated" at >= this many persons/km^2
MIN_CLUSTER_CELLS = 2   # ignore population blobs smaller than this many cells

POI_CELL_KM = 1.5       # grid size for clustering OSM amenity POIs into "towns"
POI_MIN_POINTS = 10     # ignore amenity clusters with fewer POIs than this

RESIDENTIAL_CELL_KM = 0.6    # grid size for clustering *residential* parcels alone.
                             # kept smaller than POI_CELL_KM so isolated farmhouses
                             # strung out along a road (common in farmland) don't
                             # chain distant towns together into one giant cluster.
RESIDENTIAL_MIN_PARCELS = 10  # ignore residential blobs with fewer parcels than this
                              # (a handful of neighboring farmhouses isn't a "settlement")
MERGE_BUFFER_DEG = 0.005     # after clustering amenity POIs and residential parcels
                             # separately, merge boxes that end up within this many
                             # degrees (~500 m) of each other into one settlement box

OUT_POP = "pop_density_map.png"
OUT_OSM = "osm_features_map.png"

# which OSM feature layers to draw on figure 2
OSM_LAYERS = {
    "landuse": True,
    "leisure": True,
    "building": True,
    "amenity": True,
    "railway": True,
    "highway": True,
}

_KM_PER_DEG_LAT = 111.32
_R = 6378137.0          # Web Mercator sphere radius (m)
USER_AGENT = "countryside_map/1.0 (population + OSM feature mapping demo)"
_HEADERS = {"User-Agent": USER_AGENT}  # OSM tile server / Overpass reject requests without one


def http_get(url, timeout=30):
    """GET a URL with urllib and return the raw response bytes."""
    req = urllib.request.Request(url, headers=_HEADERS, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_post_form(url, form, timeout=60):
    """POST a form-encoded body with urllib and return the raw response bytes."""
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=_HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

LANDUSE_COLORS = {
    "farmland": "#f3e4b0", "farmyard": "#e8d5a0", "vineyard": "#d7a8d7",
    "orchard": "#c6df9a", "residential": "#dcd2c6", "commercial": "#e6c6c6",
    "retail": "#e6afaf", "industrial": "#cdbdd6", "forest": "#a6cf96",
    "meadow": "#cbe69f", "grass": "#cbe69f", "cemetery": "#b3c49f",
    "recreation_ground": "#c2df9f", "quarry": "#c6bfb0",
}
LANDUSE_DEFAULT = "#d9d9d9"
LEISURE_COLORS = {
    "park": "#b3e096", "garden": "#b3e096", "nature_reserve": "#a0d488",
    "pitch": "#9bd6ab", "playground": "#e0d3ad", "golf_course": "#aede96",
}
LEISURE_DEFAULT = "#b9dea6"
BUILDING_COLOR = "#b98f86"
AMENITY_COLOR = "#8800cc"


# ----------------------------------------------------------------------------
# Web Mercator helpers
# ----------------------------------------------------------------------------
def merc(lon, lat):
    x = _R * math.radians(lon)
    y = _R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def merc_arr(lons, lats):
    lons = np.asarray(lons, dtype="float64")
    lats = np.asarray(lats, dtype="float64")
    x = _R * np.radians(lons)
    y = _R * np.log(np.tan(np.pi / 4 + np.radians(lats) / 2))
    return x, y


def ring_to_merc(geometry):
    lons = [p["lon"] for p in geometry]
    lats = [p["lat"] for p in geometry]
    x, y = merc_arr(lons, lats)
    return np.column_stack([x, y])


def bbox_from_center(lat, lon, box_km):
    half = box_km / 2.0
    d_lat = half / _KM_PER_DEG_LAT
    d_lon = half / (_KM_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return lon - d_lon, lat - d_lat, lon + d_lon, lat + d_lat  # west, south, east, north


# ----------------------------------------------------------------------------
# OSM tile basemap
# ----------------------------------------------------------------------------
def _deg2num(lat, lon, n):
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _num2lat(y, n):
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))


def fetch_osm_basemap(west, south, east, north, zoom):
    """Download & stitch OSM tiles. Returns (image_array, mercator_extent)."""
    n = 2 ** zoom
    x_tl, y_tl = _deg2num(north, west, n)
    x_br, y_br = _deg2num(south, east, n)
    tx0, tx1 = int(math.floor(x_tl)), int(math.floor(x_br))
    ty0, ty1 = int(math.floor(y_tl)), int(math.floor(y_br))

    n_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    print(f"fetching {n_tiles} OSM tiles at zoom {zoom} ...")

    canvas = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256), (221, 221, 221))
    subdomains = ["a", "b", "c"]
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            sub = subdomains[(tx + ty) % 3]
            url = f"https://{sub}.tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
            try:
                content = http_get(url, timeout=30)
                tile = Image.open(io.BytesIO(content)).convert("RGB")
                canvas.paste(tile, ((tx - tx0) * 256, (ty - ty0) * 256))
            except Exception as exc:  # noqa: BLE001 - leave gray tile on failure
                print(f"  tile {zoom}/{tx}/{ty} failed: {exc}", file=sys.stderr)

    lon_left = tx0 / n * 360.0 - 180.0
    lon_right = (tx1 + 1) / n * 360.0 - 180.0
    lat_top = _num2lat(ty0, n)
    lat_bot = _num2lat(ty1 + 1, n)
    x_left, y_top = merc(lon_left, lat_top)
    x_right, y_bot = merc(lon_right, lat_bot)
    return np.asarray(canvas), (x_left, x_right, y_bot, y_top)


# ----------------------------------------------------------------------------
# Population density
# ----------------------------------------------------------------------------
def read_pop_window(tif_path, west, south, east, north):
    with rasterio.open(tif_path) as ds:
        b = ds.bounds
        window = from_bounds(max(west, b.left), max(south, b.bottom),
                             min(east, b.right), min(north, b.top),
                             transform=ds.transform)
        data = ds.read(1, window=window).astype("float32")
        tr = ds.window_transform(window)
        nodata = ds.nodata
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    data = np.where(data < 0, np.nan, data)
    return data, tr


def cell_centers(data, transform):
    ny, nx = data.shape
    cols, rows = np.meshgrid(np.arange(nx), np.arange(ny))
    lon = transform.c + transform.a * (cols + 0.5) + transform.b * (rows + 0.5)
    lat = transform.f + transform.d * (cols + 0.5) + transform.e * (rows + 0.5)
    return lon, lat


def cell_edges_merc(data, transform):
    ny, nx = data.shape
    cols, rows = np.meshgrid(np.arange(nx + 1), np.arange(ny + 1))
    lon = transform.c + transform.a * cols + transform.b * rows
    lat = transform.f + transform.d * cols + transform.e * rows
    return merc_arr(lon, lat)


def connected_components(mask):
    """4-connected labeling of a boolean mask. Returns list of [(r,c), ...] blobs."""
    ny, nx = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    blobs = []
    for r in range(ny):
        for c in range(nx):
            if mask[r, c] and not seen[r, c]:
                q = deque([(r, c)])
                seen[r, c] = True
                cells = []
                while q:
                    cr, cc = q.popleft()
                    cells.append((cr, cc))
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < ny and 0 <= nc < nx and mask[nr, nc] and not seen[nr, nc]:
                            seen[nr, nc] = True
                            q.append((nr, nc))
                blobs.append(cells)
    return blobs


def grid_clusters(lons, lats, west, south, lat0, cell_km, min_points):
    """Cluster scattered points by snapping to a grid and merging adjacent cells.

    Returns a list of index arrays (one per kept cluster).
    """
    lons = np.asarray(lons)
    lats = np.asarray(lats)
    d_lat = cell_km / _KM_PER_DEG_LAT
    d_lon = cell_km / (_KM_PER_DEG_LAT * max(math.cos(math.radians(lat0)), 1e-6))
    ix = np.floor((lons - west) / d_lon).astype(int)
    iy = np.floor((lats - south) / d_lat).astype(int)
    cells = {}
    for k in range(len(lons)):
        cells.setdefault((int(ix[k]), int(iy[k])), []).append(k)

    seen, clusters = set(), []
    for cell in cells:
        if cell in seen:
            continue
        stack, comp = [cell], []
        seen.add(cell)
        while stack:
            c = stack.pop()
            comp.append(c)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nb = (c[0] + dx, c[1] + dy)
                    if nb in cells and nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
        idxs = [k for cc in comp for k in cells[cc]]
        if len(idxs) >= min_points:
            clusters.append(np.array(idxs))
    return clusters


def merge_close_boxes(boxes, buf):
    """Merge lon/lat bounding boxes that overlap or sit within `buf` degrees.

    Each box is a dict with lo_lon/hi_lon/lo_lat/hi_lat plus arbitrary extra
    keys (e.g. counts) that are summed on merge. Runs until no more merges apply.
    """
    boxes = list(boxes)
    changed = True
    while changed:
        changed = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                close = not (a["hi_lon"] + buf < b["lo_lon"] or b["hi_lon"] + buf < a["lo_lon"] or
                            a["hi_lat"] + buf < b["lo_lat"] or b["hi_lat"] + buf < a["lo_lat"])
                if close:
                    boxes[i] = {
                        "lo_lon": min(a["lo_lon"], b["lo_lon"]), "hi_lon": max(a["hi_lon"], b["hi_lon"]),
                        "lo_lat": min(a["lo_lat"], b["lo_lat"]), "hi_lat": max(a["hi_lat"], b["hi_lat"]),
                        "amen": a["amen"] + b["amen"], "res": a["res"] + b["res"],
                    }
                    del boxes[j]
                    changed = True
                    break
            if changed:
                break
    return boxes


# ----------------------------------------------------------------------------
# OSM vector features (Overpass)
# ----------------------------------------------------------------------------
def fetch_osm_features(west, south, east, north, want, timeout=120):
    feats = {k: [] for k in ("highway", "railway", "landuse", "leisure",
                             "building", "amenity")}
    bbox = f"{south},{west},{north},{east}"
    parts = []
    if want.get("highway"):
        parts.append(f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary)$"]({bbox});')
    if want.get("railway"):
        parts.append(f'way["railway"~"^(rail|light_rail|tram|subway|narrow_gauge)$"]({bbox});')
    if want.get("landuse"):
        parts.append(f'way["landuse"]({bbox});')
    if want.get("leisure"):
        parts.append(f'way["leisure"]({bbox});')
    if want.get("building"):
        parts.append(f'way["building"]({bbox});')
    if want.get("amenity"):
        parts.append(f'node["amenity"]({bbox});')
        parts.append(f'way["amenity"]({bbox});')
    if not parts:
        return feats

    query = f"[out:json][timeout:{timeout}];\n(\n  " + "\n  ".join(parts) + "\n);\nout geom;"
    endpoints = [
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]
    data = None
    for url in endpoints:
        try:
            print(f"querying Overpass ({url}) ...")
            payload = http_post_form(url, {"data": query}, timeout=timeout + 30)
            data = json.loads(payload)
            break
        except Exception as exc:  # noqa: BLE001
            print(f"overpass {url} failed: {exc}", file=sys.stderr)
    if data is None:
        print("no OSM feature data retrieved", file=sys.stderr)
        return feats

    for el in data.get("elements", []):
        tags = el.get("tags", {})
        etype = el.get("type")
        if etype == "node" and "amenity" in tags:
            feats["amenity"].append((el["lon"], el["lat"], tags["amenity"]))
            continue
        if etype != "way" or "geometry" not in el:
            continue
        geom = el["geometry"]
        if "highway" in tags:
            feats["highway"].append((geom, tags.get("ref") or tags.get("name", "")))
        elif "railway" in tags:
            feats["railway"].append(geom)
        elif "building" in tags:
            feats["building"].append(geom)
        elif "landuse" in tags:
            feats["landuse"].append((geom, tags["landuse"]))
        elif "leisure" in tags:
            feats["leisure"].append((geom, tags["leisure"]))
        elif "amenity" in tags:
            lons = [p["lon"] for p in geom]
            lats = [p["lat"] for p in geom]
            feats["amenity"].append((sum(lons) / len(lons), sum(lats) / len(lats),
                                     tags["amenity"]))
    return feats


# ----------------------------------------------------------------------------
# Rendering helpers
# ----------------------------------------------------------------------------
def add_polygons(ax, items, color_of, zorder, alpha, edgecolor="none", lw=0.0):
    patches, facecolors = [], []
    for it in items:
        geom, value = it if isinstance(it, tuple) else (it, None)
        if len(geom) < 3:
            continue
        patches.append(MplPolygon(ring_to_merc(geom), closed=True))
        facecolors.append(color_of(value))
    if not patches:
        return
    ax.add_collection(PatchCollection(patches, facecolors=facecolors,
                                      edgecolors=edgecolor, linewidths=lw,
                                      alpha=alpha, zorder=zorder))


def setup_axes(ax, base_img, base_extent, west, south, east, north, title):
    ax.imshow(base_img, extent=base_extent, origin="upper", interpolation="bilinear",
              zorder=0)
    xw, yb = merc(west, south)
    xe, yt = merc(east, north)
    ax.set_xlim(xw, xe)
    ax.set_ylim(yb, yt)
    lon_ticks = np.linspace(west, east, 6)
    lat_ticks = np.linspace(south, north, 6)
    ax.set_xticks([merc(v, CENTER_LAT)[0] for v in lon_ticks])
    ax.set_xticklabels([f"{v:.3f}" for v in lon_ticks])
    ax.set_yticks([merc(CENTER_LON, v)[1] for v in lat_ticks])
    ax.set_yticklabels([f"{v:.3f}" for v in lat_ticks])
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(title)
    return (xw, yb, xe, yt)


def add_attribution(ax):
    ax.text(0.005, 0.005, "(c) OpenStreetMap contributors", transform=ax.transAxes,
            fontsize=7, color="black", alpha=0.7, ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.6))


# ----------------------------------------------------------------------------
# Figure 1: population density
# ----------------------------------------------------------------------------
def figure_population(base_img, base_extent, west, south, east, north,
                      data, transform):
    lon2d, lat2d = cell_centers(data, transform)
    valid = data[np.isfinite(data)]
    thresh = max(np.nanpercentile(valid, 90), DENSE_FLOOR)
    dense_mask = np.isfinite(data) & (data >= thresh)
    blobs = [b for b in connected_components(dense_mask) if len(b) >= MIN_CLUSTER_CELLS]
    print(f"\n[figure 1] dense threshold = {thresh:.1f} persons/km^2, "
          f"{len(blobs)} cluster(s):")

    fig, ax = plt.subplots(figsize=(12, 12))
    _, yb, _, yt = setup_axes(ax, base_img, base_extent, west, south, east, north,
                              f"Population density on OSM basemap\n"
                              f"center ({CENTER_LAT}, {CENTER_LON}), "
                              f"{BOX_KM:.0f} km x {BOX_KM:.0f} km  (Salinas Valley, CA)")

    Xe, Ye = cell_edges_merc(data, transform)
    masked = np.ma.masked_invalid(data)
    vmax = max(float(np.nanpercentile(valid, 99)), 1.0)
    norm = matplotlib.colors.SymLogNorm(linthresh=1.0, vmin=0.0, vmax=vmax)
    cmap = plt.get_cmap("turbo").copy()
    cmap.set_bad(alpha=0.0)
    mesh = ax.pcolormesh(Xe, Ye, masked, cmap=cmap, norm=norm, alpha=0.6,
                         shading="flat", zorder=2)
    cbar = fig.colorbar(mesh, ax=ax, shrink=0.72, pad=0.02)
    cbar.set_label("population density (persons / km$^2$, log scale)")

    for i, cells in enumerate(sorted(blobs, key=len, reverse=True), 1):
        rows = [c[0] for c in cells]
        cols = [c[1] for c in cells]
        clons = lon2d[rows, cols]
        clats = lat2d[rows, cols]
        vals = data[rows, cols]
        cx, cy = merc(clons.mean(), clats.mean())
        mx, my = merc_arr(clons, clats)
        radius = max(np.hypot(mx - cx, my - cy).max(), 400.0) + 500.0
        ax.add_patch(Circle((cx, cy), radius, fill=False, edgecolor="red",
                            linewidth=2.2, zorder=5))
        if cy + radius > yt - (yt - yb) * 0.06:
            ly, va = cy - radius, "top"
        else:
            ly, va = cy + radius, "bottom"
        ax.text(cx, ly, f"#{i}", color="red", fontsize=11, fontweight="bold",
                ha="center", va=va, zorder=6,
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="red", alpha=0.85))
        print(f"  cluster #{i}: {len(cells)} cells, peak {vals.max():.0f} persons/km^2, "
              f"lat [{clats.min():.5f}, {clats.max():.5f}]  "
              f"lon [{clons.min():.5f}, {clons.max():.5f}]")

    ccx, ccy = merc(CENTER_LON, CENTER_LAT)
    ax.plot([ccx], [ccy], marker="+", ms=16, mew=2.5, color="black", zorder=6)
    handles = [
        plt.Line2D([], [], marker="o", mfc="none", mec="red", mew=2, ls="none",
                   ms=12, label="population-dense (town)"),
        plt.Line2D([], [], marker="+", color="black", ls="none", ms=12, mew=2.5,
                   label="center"),
    ]
    ax.legend(handles=handles, loc="upper right", fontsize=9, framealpha=0.9)
    add_attribution(ax)
    fig.tight_layout()
    fig.savefig(OUT_POP, dpi=150)
    plt.close(fig)
    print(f"wrote {OUT_POP}")


# ----------------------------------------------------------------------------
# Figure 2: OSM interest features
# ----------------------------------------------------------------------------
def figure_osm(base_img, base_extent, west, south, east, north, feats):
    print("\n[figure 2] OSM features:  " +
          "  ".join(f"{k}={len(v)}" for k, v in feats.items()))
    fig, ax = plt.subplots(figsize=(13, 12))
    _, yb, _, yt = setup_axes(ax, base_img, base_extent, west, south, east, north,
                              f"OSM interest features on OSM basemap\n"
                              f"center ({CENTER_LAT}, {CENTER_LON}), "
                              f"{BOX_KM:.0f} km x {BOX_KM:.0f} km  (Salinas Valley, CA)")
    handles = []

    if OSM_LAYERS["landuse"] and feats["landuse"]:
        add_polygons(ax, feats["landuse"],
                     lambda v: LANDUSE_COLORS.get(v, LANDUSE_DEFAULT),
                     zorder=1, alpha=0.4)
        counts = {}
        for _, v in feats["landuse"]:
            counts[v] = counts.get(v, 0) + 1
        for v, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:6]:
            handles.append(Patch(facecolor=LANDUSE_COLORS.get(v, LANDUSE_DEFAULT),
                                 edgecolor="none", alpha=0.7, label=f"landuse: {v}"))

    if OSM_LAYERS["leisure"] and feats["leisure"]:
        add_polygons(ax, feats["leisure"],
                     lambda v: LEISURE_COLORS.get(v, LEISURE_DEFAULT),
                     zorder=1.3, alpha=0.55)
        handles.append(Patch(facecolor=LEISURE_DEFAULT, edgecolor="none",
                             alpha=0.7, label="leisure (park/pitch/...)"))

    if OSM_LAYERS["building"] and feats["building"]:
        add_polygons(ax, feats["building"], lambda v: BUILDING_COLOR,
                     zorder=2, alpha=0.8)
        handles.append(Patch(facecolor=BUILDING_COLOR, edgecolor="none",
                             alpha=0.85, label="building"))

    if OSM_LAYERS["railway"] and feats["railway"]:
        segs = [ring_to_merc(g) for g in feats["railway"] if len(g) >= 2]
        ax.add_collection(LineCollection(segs, colors="black", linewidths=1.6,
                                         linestyles="dashed", zorder=3))
        handles.append(plt.Line2D([], [], color="black", lw=1.6, ls="dashed",
                                  label="railway"))

    if OSM_LAYERS["highway"] and feats["highway"]:
        segs = [ring_to_merc(g) for g, _ in feats["highway"] if len(g) >= 2]
        ax.add_collection(LineCollection(segs, colors="#0033cc", linewidths=2.0,
                                         alpha=0.9, zorder=3.5))
        handles.append(plt.Line2D([], [], color="#0033cc", lw=2.5, label="highway"))

    # --- amenity points (scatter only) ---
    alon = np.array([a[0] for a in feats["amenity"]]) if feats["amenity"] else np.array([])
    alat = np.array([a[1] for a in feats["amenity"]]) if feats["amenity"] else np.array([])
    if OSM_LAYERS["amenity"] and feats["amenity"]:
        axm, aym = merc_arr(alon, alat)
        ax.scatter(axm, aym, s=12, c=AMENITY_COLOR, marker="o", alpha=0.85,
                   edgecolors="white", linewidths=0.3, zorder=4)
        handles.append(plt.Line2D([], [], color=AMENITY_COLOR, marker="o", ls="none",
                                  ms=7, mec="white", label="amenity (POI)"))

    # --- residential landuse parcels ---
    residential_geoms = [geom for geom, v in feats.get("landuse", []) if v == "residential"]
    res_cen_lon = np.array([np.mean([p["lon"] for p in g]) for g in residential_geoms]) \
        if residential_geoms else np.array([])
    res_cen_lat = np.array([np.mean([p["lat"] for p in g]) for g in residential_geoms]) \
        if residential_geoms else np.array([])

    # Cluster amenity POIs and residential parcels SEPARATELY first (each with its
    # own grid size / density threshold), then merge only the resulting boxes that
    # actually sit close together. Combining the raw points into one clustering
    # pass would let a string of isolated roadside farmhouses (each tagged
    # landuse=residential) bridge two unrelated towns into one giant box.
    raw_boxes = []
    if alon.size:
        for idx in grid_clusters(alon, alat, west, south, CENTER_LAT,
                                 POI_CELL_KM, POI_MIN_POINTS):
            raw_boxes.append({"lo_lon": float(alon[idx].min()), "hi_lon": float(alon[idx].max()),
                              "lo_lat": float(alat[idx].min()), "hi_lat": float(alat[idx].max()),
                              "amen": int(idx.size), "res": 0})
    if res_cen_lon.size:
        for idx in grid_clusters(res_cen_lon, res_cen_lat, west, south, CENTER_LAT,
                                 RESIDENTIAL_CELL_KM, RESIDENTIAL_MIN_PARCELS):
            lons = [pt["lon"] for k in idx for pt in residential_geoms[k]]
            lats = [pt["lat"] for k in idx for pt in residential_geoms[k]]
            raw_boxes.append({"lo_lon": min(lons), "hi_lon": max(lons),
                              "lo_lat": min(lats), "hi_lat": max(lats),
                              "amen": 0, "res": int(idx.size)})

    boxes = merge_close_boxes(raw_boxes, MERGE_BUFFER_DEG)
    boxes.sort(key=lambda b: b["amen"] + b["res"], reverse=True)
    print(f"  {len(boxes)} settlement cluster(s) (amenity + residential):")
    pad = 0.004  # deg padding around the box
    if boxes:
        handles.append(Patch(facecolor="none", edgecolor="red", linewidth=2.0,
                             label="settlement cluster (amenity + residential)"))
    for i, b in enumerate(boxes, 1):
        lo_lon, hi_lon = b["lo_lon"] - pad, b["hi_lon"] + pad
        lo_lat, hi_lat = b["lo_lat"] - pad, b["hi_lat"] + pad
        x0, y0 = merc(lo_lon, lo_lat)
        x1, y1 = merc(hi_lon, hi_lat)
        ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False,
                               edgecolor="red", linewidth=2.0, zorder=5))
        label = (f"cluster #{i}: {b['amen']} POI, {b['res']} residential parcel\n"
                 f"lat {lo_lat + pad:.4f}~{hi_lat - pad:.4f}\n"
                 f"lon {lo_lon + pad:.4f}~{hi_lon - pad:.4f}")
        # put the label below the box if its top is near the top of the frame
        if y1 > yt - (yt - yb) * 0.12:
            anchor_y, dy, va = y0, -6, "top"
        else:
            anchor_y, dy, va = y1, 6, "bottom"
        ax.annotate(label, xy=((x0 + x1) / 2, anchor_y), xytext=(0, dy),
                    textcoords="offset points", ha="center", va=va,
                    fontsize=8, color="black", zorder=6,
                    bbox=dict(boxstyle="round,pad=0.3", fc="yellow", ec="red",
                              alpha=0.85))
        print(f"    #{i}: {b['amen']} POI, {b['res']} residential parcel(s)  "
              f"lat [{lo_lat + pad:.5f}, {hi_lat - pad:.5f}]  "
              f"lon [{lo_lon + pad:.5f}, {hi_lon - pad:.5f}]")

    ccx, ccy = merc(CENTER_LON, CENTER_LAT)
    ax.plot([ccx], [ccy], marker="+", ms=16, mew=2.5, color="black", zorder=6)
    handles.append(plt.Line2D([], [], marker="+", color="black", ls="none",
                              ms=12, mew=2.5, label="center"))
    ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.9)
    add_attribution(ax)
    fig.tight_layout()
    fig.savefig(OUT_OSM, dpi=150)
    plt.close(fig)
    print(f"wrote {OUT_OSM}")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    west, south, east, north = bbox_from_center(CENTER_LAT, CENTER_LON, BOX_KM)
    print(f"window lat [{south:.5f}, {north:.5f}]  lon [{west:.5f}, {east:.5f}]  "
          f"({BOX_KM:.0f} km square)")

    base_img, base_extent = fetch_osm_basemap(west, south, east, north, ZOOM)
    data, transform = read_pop_window(TIF_PATH, west, south, east, north)
    feats = fetch_osm_features(west, south, east, north, OSM_LAYERS)

    figure_population(base_img, base_extent, west, south, east, north, data, transform)
    figure_osm(base_img, base_extent, west, south, east, north, feats)


if __name__ == "__main__":
    main()
