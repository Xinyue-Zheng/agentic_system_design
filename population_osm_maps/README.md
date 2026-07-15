# Population density + OSM feature maps

Two small, dependency-light scripts that render a population-density GeoTIFF around
a chosen point and overlay OpenStreetMap features. Everything is drawn in Web
Mercator (EPSG:3857) so overlays line up exactly with the OSM tiles, and OSM data
is fetched directly (tile server for the basemap, Overpass API for vector features)
— **no** `geopandas` / `osmnx` / `contextily` / `shapely` needed.

## Dependencies

```
rasterio   numpy   matplotlib   Pillow      # both scripts
requests                                    # only pop_osm_map.py
```

`countryside_map.py` fetches every URL (OSM tiles + Overpass) with the standard
library `urllib.request` — it needs no third-party HTTP client. `pop_osm_map.py`
still uses `requests`. Install everything with:

```bash
pip install -r requirements.txt
```

You also need a population-density raster in EPSG:4326 (persons/km²), e.g.
`usa_pd_2018_1km.tif`. It is **not** included here (large data file). Put it next to
the scripts or point the scripts at it (see below).

An internet connection is required at runtime for the OSM basemap tiles and the
Overpass queries.

## `countryside_map.py`

Self-contained, **no command-line arguments** — all configuration is hardcoded at
the top of the file (center lat/lon, 30 km × 30 km window, zoom, layer toggles,
input tif path, output filenames). It writes **two** figures over a real OSM
basemap:

1. `pop_density_map.png` — population-density heatmap with the dense pockets
   (towns) circled; each cluster's lat/lon range is printed to the console.
2. `osm_features_map.png` — OSM interest features: `highway` / `railway` (lines),
   `landuse` / `leisure` / `building` (polygons), `amenity` (points). Points of
   interest are clustered into towns, boxed, and their lat/lon ranges are annotated
   directly on the map.

Run:

```bash
python countryside_map.py
```

Edit the `CONFIG` block near the top to change location, window size, zoom, which
OSM layers to draw (`OSM_LAYERS`), the dense-cell threshold, or the POI-cluster
grid size.

## `pop_osm_map.py`

A more general, parameterized version (single figure). Takes the center, radius,
and tif path from the command line:

```bash
python pop_osm_map.py --tif usa_pd_2018_1km.tif --lat 40.7128 --lon -74.0060 \
    --radius-km 25 --out nyc.png
```

It draws the population-density heatmap, marks the densest cells, and overlays OSM
highways and airports (Overpass). Use `--no-osm` to skip the OSM overlay, and
`--hot-pct` to tune the "dense" percentile.

## Notes

- The OSM tile server and the public Overpass endpoints require a `User-Agent`
  header (already set) and are rate-limited; the scripts try several Overpass
  mirrors and fail gracefully (drawing the population map even if OSM is
  unavailable).
- Please respect the
  [OSM tile usage policy](https://operations.osmfoundation.org/policies/tiles/)
  — these scripts are for light, one-off use.
