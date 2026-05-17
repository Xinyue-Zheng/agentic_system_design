from staticmap import StaticMap, Line
# from local_preprocessing import run_local_preprocessing

# Match exactly the bounding box from your coverage JSON
LAT_MIN = 33.0100
LAT_MAX = 33.0550
LON_MIN = -96.7200
LON_MAX = -96.6650

m = StaticMap(800, 700)
img = m.render(zoom=14, center=[(LON_MIN+LON_MAX)/2, (LAT_MIN+LAT_MAX)/2])
img.save("real_map.png")