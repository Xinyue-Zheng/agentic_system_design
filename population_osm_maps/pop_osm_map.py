#!/usr/bin/env python3
"""Render a population-density map around a point with OSM roads/airports overlaid.

Given a population-density GeoTIFF (e.g. usa_pd_2018_1km.tif, EPSG:4326, persons/km^2),
a center (lat, lon) and a radius in kilometers, this:

  1. Crops the raster to a square window centered on (lat, lon) with the given radius.
  2. Draws the population density as a heatmap and highlights the densest cells.
  3. Queries OpenStreetMap (Overpass API) for "places people pass through" inside the
     window -- major highways and aeroways (airports / runways) -- and overlays them.
  4. Saves the result to a PNG.

Only needs: rasterio, numpy, matplotlib, requests. No geopandas / osmnx / shapely.

Usage:
    python pop_osm_map.py --tif usa_pd_2018_1km.tif --lat 40.7128 --lon -74.0060 \
        --radius-km 25 --out nyc.png
"""

from __future__ import annotations

import argparse
import math
import sys

import matplotlib

matplotlib.use("Agg")  # headless / no display
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.collections import LineCollection
from rasterio.windows import from_bounds

# meters -> degrees helpers (spherical earth approximation, good enough for a local window)
_KM_PER_DEG_LAT = 111.32


def km_to_deg(lat_deg: float, radius_km: float) -> tuple[float, float]:
    """Return (d_lat_deg, d_lon_deg) offsets for a radius in km at the given latitude."""
    d_lat = radius_km / _KM_PER_DEG_LAT
    # longitude degrees shrink with latitude
    d_lon = radius_km / (_KM_PER_DEG_LAT * max(math.cos(math.radians(lat_deg)), 1e-6))
    return d_lat, d_lon


# ----------------------------------------------------------------------------
# OSM slippy-map tile basemap (Web Mercator). No contextily needed.
# ----------------------------------------------------------------------------
def _lonlat_to_tilexy(lon, lat, z):
    """Fractional tile x/y for a lon/lat at zoom z (Web Mercator)."""
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _tilex_to_lon(x, z):
    return x / 2 ** z * 360.0 - 180.0


def _tiley_to_lat(y, z):
    n = math.pi - 2.0 * math.pi * y / 2 ** z
    return math.degrees(math.atan(math.sinh(n)))


def fetch_basemap(west, south, east, north, max_tiles=120, timeout=20):
    """Fetch & stitch OSM tiles covering the bbox.

    Returns (mosaic_rgba, (mo_west, mo_east, mo_south, mo_north)) or (None, None)
    on failure. The mosaic extent is the union of whole tiles, so it is slightly
    larger than the requested bbox.
    """
    import io

    import matplotlib.image as mpimg
    import requests

    # pick the largest zoom whose tile count stays under max_tiles
    zoom = 3
    for z in range(19, 2, -1):
        x0, y0 = _lonlat_to_tilexy(west, north, z)  # top-left
        x1, y1 = _lonlat_to_tilexy(east, south, z)  # bottom-right
        ntiles = (int(x1) - int(x0) + 1) * (int(y1) - int(y0) + 1)
        if ntiles <= max_tiles:
            zoom = z
            break

    x0i, y0i = int(_lonlat_to_tilexy(west, north, zoom)[0]), int(_lonlat_to_tilexy(west, north, zoom)[1])
    x1i, y1i = int(_lonlat_to_tilexy(east, south, zoom)[0]), int(_lonlat_to_tilexy(east, south, zoom)[1])
    nx, ny = x1i - x0i + 1, y1i - y0i + 1

    headers = {"User-Agent": "pop_osm_map/1.0 (population-density mapping script)"}
    mosaic = np.ones((ny * 256, nx * 256, 3), dtype="float32")
    got_any = False
    for ty in range(y0i, y1i + 1):
        for tx in range(x0i, x1i + 1):
            url = f"https://tile.openstreetmap.org/{zoom}/{tx}/{ty}.png"
            try:
                r = requests.get(url, headers=headers, timeout=timeout)
                r.raise_for_status()
                tile = mpimg.imread(io.BytesIO(r.content), format="png")[:, :, :3]
                got_any = True
            except Exception as exc:  # noqa: BLE001
                print(f"tile {zoom}/{tx}/{ty} failed: {exc}", file=sys.stderr)
                continue
            ry, rx = (ty - y0i) * 256, (tx - x0i) * 256
            mosaic[ry:ry + 256, rx:rx + 256, :] = tile

    if not got_any:
        return None, None

    mo_west = _tilex_to_lon(x0i, zoom)
    mo_east = _tilex_to_lon(x1i + 1, zoom)
    mo_north = _tiley_to_lat(y0i, zoom)
    mo_south = _tiley_to_lat(y1i + 1, zoom)
    print(f"basemap: zoom {zoom}, {nx}x{ny} tiles")
    return mosaic, (mo_west, mo_east, mo_south, mo_north)


def read_window(tif_path: str, lat: float, lon: float, radius_km: float):
    """Read the raster cropped to a bbox centered on (lat, lon).

    Returns (data, extent, nodata) where extent = (west, east, south, north) for imshow.
    """
    d_lat, d_lon = km_to_deg(lat, radius_km)
    west, east = lon - d_lon, lon + d_lon
    south, north = lat - d_lat, lat + d_lat

    with rasterio.open(tif_path) as ds:
        if ds.crs is None or ds.crs.to_epsg() != 4326:
            print(
                f"warning: expected EPSG:4326 raster, got {ds.crs}. "
                "The lat/lon bbox math assumes a geographic CRS.",
                file=sys.stderr,
            )
        # clamp bbox to the raster footprint so from_bounds doesn't go out of range
        b = ds.bounds
        west, east = max(west, b.left), min(east, b.right)
        south, north = max(south, b.bottom), min(north, b.top)
        if west >= east or south >= north:
            raise SystemExit(
                "The requested window does not overlap the raster footprint. "
                f"Raster bounds: {b}"
            )

        window = from_bounds(west, south, east, north, transform=ds.transform)
        data = ds.read(1, window=window).astype("float32")
        nodata = ds.nodata

    # mask nodata + negatives (population density can't be negative)
    if nodata is not None:
        data = np.where(data == nodata, np.nan, data)
    data = np.where(data < 0, np.nan, data)

    extent = (west, east, south, north)
    return data, extent, nodata


def overpass_features(west, south, east, north, timeout=60):
    """Query Overpass for highways and aeroways in the bbox.

    Returns (roads, airports) where:
      roads    -> list of [(lon, lat), ...] polylines
      airports -> list of (lon, lat, name) points (airport nodes / way centroids)
    Never raises on network failure -- returns whatever it got (possibly empty).
    """
    import requests

    # Overpass expects (south, west, north, east)
    bbox = f"{south},{west},{north},{east}"
    query = f"""
    [out:json][timeout:{timeout}];
    (
      way["highway"~"^(motorway|trunk|primary|secondary)$"]({bbox});
      way["aeroway"~"^(runway|taxiway)$"]({bbox});
      node["aeroway"="aerodrome"]({bbox});
      way["aeroway"="aerodrome"]({bbox});
    );
    out geom;
    """
    endpoints = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ]
    # Overpass returns 406 without an identifying User-Agent.
    headers = {"User-Agent": "pop_osm_map/1.0 (population-density mapping script)"}
    data = None
    for url in endpoints:
        try:
            resp = requests.post(
                url, data={"data": query}, headers=headers, timeout=timeout + 10
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:  # noqa: BLE001 - overlay is best-effort
            print(f"overpass query to {url} failed: {exc}", file=sys.stderr)
    if data is None:
        print("no OSM data retrieved; drawing population map only", file=sys.stderr)
        return [], []

    roads: list[list[tuple[float, float]]] = []
    airports: list[tuple[float, float, str]] = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if el.get("type") == "way" and "geometry" in el:
            line = [(pt["lon"], pt["lat"]) for pt in el["geometry"]]
            if "aeroway" in tags and tags.get("aeroway") == "aerodrome":
                # airport polygon -> use centroid as a marker
                lons = [p[0] for p in line]
                lats = [p[1] for p in line]
                airports.append(
                    (sum(lons) / len(lons), sum(lats) / len(lats), tags.get("name", "airport"))
                )
            else:
                roads.append(line)
        elif el.get("type") == "node" and tags.get("aeroway") == "aerodrome":
            airports.append((el["lon"], el["lat"], tags.get("name", "airport")))

    return roads, airports


def make_map(data, extent, roads, airports, center, radius_km, out_path, hot_pct):
    west, east, south, north = extent
    lat, lon = center

    fig, ax = plt.subplots(figsize=(11, 11))

    # --- population density heatmap ---
    # log scale so dense urban cores don't wash out everything else
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        raise SystemExit("The cropped window is entirely nodata.")
    vmax = np.nanpercentile(valid, 99)
    norm = matplotlib.colors.SymLogNorm(linthresh=1.0, vmin=0, vmax=max(vmax, 1.0))
    im = ax.imshow(
        data,
        extent=extent,
        origin="upper",
        cmap="inferno",
        norm=norm,
        interpolation="nearest",
        aspect="auto",
    )
    cbar = fig.colorbar(im, ax=ax, shrink=0.75, pad=0.02)
    cbar.set_label("population density (persons / km$^2$, log scale)")

    # --- highlight the densest cells (top `hot_pct` percentile) ---
    if valid.size > 0:
        thresh = np.nanpercentile(valid, hot_pct)
        hot = np.isfinite(data) & (data >= thresh)
        if hot.any():
            ny, nx = data.shape
            # cell-center coordinates
            xs = np.linspace(west, east, nx, endpoint=False) + (east - west) / (2 * nx)
            ys = np.linspace(north, south, ny, endpoint=False) - (north - south) / (2 * ny)
            gx, gy = np.meshgrid(xs, ys)
            ax.scatter(
                gx[hot],
                gy[hot],
                s=14,
                facecolors="none",
                edgecolors="cyan",
                linewidths=0.6,
                alpha=0.8,
                label=f"dense (top {100 - hot_pct:.0f}%, >{thresh:.0f}/km$^2$)",
            )

    # --- OSM roads ---
    if roads:
        segs = [np.array(line) for line in roads if len(line) >= 2]
        lc = LineCollection(segs, colors="deepskyblue", linewidths=1.0, alpha=0.85)
        ax.add_collection(lc)
        # proxy handle for legend
        ax.plot([], [], color="deepskyblue", lw=1.5, label="highways (OSM)")

    # --- OSM airports ---
    if airports:
        axs = [a[0] for a in airports]
        ays = [a[1] for a in airports]
        ax.scatter(axs, ays, marker="*", s=260, c="lime", edgecolors="black",
                   linewidths=0.6, zorder=5, label="airport (OSM)")
        for alon, alat, name in airports:
            if name and name != "airport":
                ax.annotate(name, (alon, alat), fontsize=7, color="white",
                            xytext=(4, 4), textcoords="offset points")

    # --- center marker ---
    ax.scatter([lon], [lat], marker="+", s=200, c="white", linewidths=2.0,
               zorder=6, label="center")

    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(
        f"Population density + OSM near ({lat:.4f}, {lon:.4f}), r={radius_km} km"
    )
    ax.legend(loc="upper right", fontsize=8, framealpha=0.85)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    print(f"wrote {out_path}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tif", default="usa_pd_2018_1km.tif", help="population-density GeoTIFF")
    p.add_argument("--lat", type=float, required=True, help="center latitude")
    p.add_argument("--lon", type=float, required=True, help="center longitude")
    p.add_argument("--radius-km", type=float, default=25.0, help="half-width of the window in km")
    p.add_argument("--out", default="pop_osm_map.png", help="output PNG path")
    p.add_argument("--hot-pct", type=float, default=90.0,
                   help="percentile threshold for 'dense' cells (default 90 = top 10%%)")
    p.add_argument("--no-osm", action="store_true", help="skip the OSM overlay")
    args = p.parse_args(argv)

    data, extent, _ = read_window(args.tif, args.lat, args.lon, args.radius_km)
    west, east, south, north = extent

    roads, airports = ([], [])
    if not args.no_osm:
        roads, airports = overpass_features(west, south, east, north)
        print(f"OSM: {len(roads)} road ways, {len(airports)} airports")

    make_map(data, extent, roads, airports, (args.lat, args.lon),
             args.radius_km, args.out, args.hot_pct)


if __name__ == "__main__":
    main()
