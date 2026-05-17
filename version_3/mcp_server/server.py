"""
Telecom Data MCP Server

Implements MCP protocol version 2024-11-05 over stdio transport with
Content-Length framing (identical to the official mcp Python SDK).

No external packages required beyond pandas.

Dependencies: pandas
Usage: python mcp_server/server.py
"""

# Data source note: All tools currently read from local files (synthetic data).
# In production, each tool would call the appropriate operator API:
# - get_kpi_history / get_kpi_timeseries: operator KPI/performance management API
# - get_site_attributes / get_all_site_attributes: network inventory API
# - get_coverage_pixels: RF planning tool API
# - get_geo_features: mapping service API (e.g. Google Maps Static API)
#   called with the outage lat/lon from the ticket
# - get_ticket / get_all_tickets: ticketing system API (e.g. ServiceNow)
# The tool interfaces (names, parameters, return schemas) remain unchanged
# when switching from local to API data sources.
import os
with open('/tmp/mcp_started.log', 'a') as f:
    f.write('server.py process started\n')


import base64
import json
import os
import sys
from typing import Any, Dict, List, Optional
import urllib.request
import pandas as pd
import io

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Debug: log startup environment
print(f"[debug] cwd: {os.getcwd()}", file=sys.stderr)
print(f"[debug] DATA_DIR: {os.environ.get('DATA_DIR', 'NOT SET')}", file=sys.stderr)
print(f"[debug] python: {sys.executable}", file=sys.stderr)
DATA_DIR = os.environ.get("DATA_DIR", "data")

# 改成懒加载
_kpi_df = None
_attr_df = None
_coverage = None
_tickets_data = None

def _ensure_loaded():
    global _kpi_df, _attr_df, _coverage, _tickets_data
    if _kpi_df is not None:
        return
    
    kpi_path  = os.path.join(DATA_DIR, "KPI_data.csv")
    attr_path = os.path.join(DATA_DIR, "usid_attributes.csv")
    cov_path  = os.path.join(DATA_DIR, "usid_coverage_pixels.json")
    tkt_path  = os.path.join(DATA_DIR, "outage_tickets.json")

    _kpi_df = pd.read_csv(kpi_path)
    _kpi_df["timestamp_utc"] = pd.to_datetime(_kpi_df["timestamp_utc"], utc=True)
    print(f"[load] KPI_data.csv loaded — {len(_kpi_df):,} rows", file=sys.stderr)

    _attr_df = pd.read_csv(attr_path)
    print(f"[load] usid_attributes.csv loaded — {len(_attr_df)} rows", file=sys.stderr)

    with open(cov_path) as f:
        _coverage = json.load(f)
    print(f"[load] usid_coverage_pixels.json loaded — {len(_coverage['pixels'])} pixels", file=sys.stderr)

    with open(tkt_path) as f:
        _tickets_data = json.load(f)
    print(f"[load] outage_tickets.json loaded — {len(_tickets_data['tickets'])} tickets", file=sys.stderr)

# ---------------------------------------------------------------------------
# Startup: load all tabular/JSON data once
# Logs go to stderr — stdout is reserved for MCP protocol messages.
# ---------------------------------------------------------------------------

def _load_data() -> tuple:
    kpi_path  = os.path.join(DATA_DIR, "KPI_data.csv")
    attr_path = os.path.join(DATA_DIR, "usid_attributes.csv")
    cov_path  = os.path.join(DATA_DIR, "usid_coverage_pixels.json")
    tkt_path  = os.path.join(DATA_DIR, "outage_tickets.json")

    kpi_df = pd.read_csv(kpi_path)
    kpi_df["timestamp_utc"] = pd.to_datetime(kpi_df["timestamp_utc"], utc=True)
    print(f"[startup] KPI_data.csv          loaded — {len(kpi_df):,} rows", file=sys.stderr)

    attr_df = pd.read_csv(attr_path)
    print(f"[startup] usid_attributes.csv   loaded — {len(attr_df)} rows", file=sys.stderr)

    with open(cov_path) as f:
        coverage = json.load(f)
    print(f"[startup] usid_coverage_pixels.json loaded — {len(coverage['pixels'])} pixels",
          file=sys.stderr)

    with open(tkt_path) as f:
        tickets = json.load(f)
    print(f"[startup] outage_tickets.json   loaded — {len(tickets['tickets'])} tickets",
          file=sys.stderr)

    return kpi_df, attr_df, coverage, tickets


_kpi_df, _attr_df, _coverage, _tickets_data = _load_data()

_KPI_COLS = [
    "sector_id", "azimuth_deg", "timestamp_utc",
    "throughput_dl_mbps", "throughput_ul_mbps",
    "volume_dl_gb", "volume_ul_gb",
]


def _kpi_to_records(df: pd.DataFrame) -> List[Dict[str, Any]]:
    return json.loads(df[_KPI_COLS].to_json(orient="records", date_format="iso"))


def _cell_id(cell) -> Optional[str]:
    return cell["ID"] if cell else None

def _matches(pixel_id: Optional[str], query: str) -> bool:
    """True if pixel_id equals query (sector-level) or starts with query + '_S' (parent-level)."""
    if pixel_id is None:
        return False
    return pixel_id == query or pixel_id.startswith(query + "_S")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def get_kpi_history(usid: str) -> List[Dict[str, Any]]:
    _ensure_loaded()
    """Return all 60-day KPI history for every sector of a given USID."""
    df = _kpi_df[_kpi_df["usid"] == usid]
    return [] if df.empty else _kpi_to_records(df)


def get_kpi_timeseries(usid: str, start_utc: str, end_utc: str) -> List[Dict[str, Any]]:
    _ensure_loaded()
    """Return 15-min KPI records for a USID within a UTC time window (inclusive)."""
    start = pd.to_datetime(start_utc, utc=True)
    end   = pd.to_datetime(end_utc,   utc=True)
    mask  = (
        (_kpi_df["usid"] == usid)
        & (_kpi_df["timestamp_utc"] >= start)
        & (_kpi_df["timestamp_utc"] <= end)
    )
    df = _kpi_df[mask]
    return [] if df.empty else _kpi_to_records(df)


def get_site_attributes(usid: str) -> Optional[Dict[str, Any]]:
    _ensure_loaded()
    """Return static hardware config for one site, or null if not found."""
    row = _attr_df[_attr_df["USID"] == usid]
    return None if row.empty else json.loads(row.iloc[0].to_json())


def get_all_site_attributes() -> List[Dict[str, Any]]:
    """Return static hardware config for all 50 sites."""
    _ensure_loaded()
    return json.loads(_attr_df.to_json(orient="records"))


def get_coverage_pixels(usid: str) -> List[Dict[str, Any]]:
    """Return pixels where usid (parent or sector ID) is dominant, backup1, or backup2 cell."""
    _ensure_loaded()
    result = []
    for pixel in _coverage["pixels"]:
        info = pixel["info"]
        if (
            _matches(_cell_id(info.get("dominant")), usid)
            or _matches(_cell_id(info.get("backup1")), usid)
            or _matches(_cell_id(info.get("backup2")), usid)
        ):
            result.append(pixel)
    return result


def get_coverage_pixels_by_sector(sector_id: str) -> List[Dict[str, Any]]:
    """Return pixels where sector_id (e.g. 'USID_09_S2') is dominant, backup1, or backup2."""
    _ensure_loaded()
    result = []
    for pixel in _coverage["pixels"]:
        info = pixel["info"]
        if (
            _cell_id(info.get("dominant")) == sector_id
            or _cell_id(info.get("backup1")) == sector_id
            or _cell_id(info.get("backup2")) == sector_id
        ):
            result.append(pixel)
    return result


def get_preprocessing_stats(usid: str) -> Optional[Dict[str, Any]]:
    """Return local preprocessing stats for a USID, or null if not computed yet."""
    _ensure_loaded()
    stats_path = os.path.join(DATA_DIR, "preprocessing_stats.json")
    if not os.path.exists(stats_path):
        return None
    with open(stats_path) as f:
        stats = json.load(f)
    return stats if stats.get("target_usid") == usid else None


# In production, this tool would call an external mapping API
# (e.g. Google Maps Static API, OpenStreetMap) using the provided
# lat/lon to fetch a real map tile centered on the outage location
# with the given radius. The synthetic implementation returns a
# pre-generated local map that covers the test area.
# def get_geo_features(lat: float, lon: float, radius_km: float = 10.0) -> Dict[str, Any]:
#     """Return geo features map as base64 PNG centered on the given coordinates."""
#     path = os.path.join(DATA_DIR, "geo_features_map.png")
#     with open(path, "rb") as f:
#         image_b64 = base64.b64encode(f.read()).decode("utf-8")
#     return {
#         "image_base64": image_b64,
#         "format": "png",
#         "center": {"lat": lat, "lon": lon},
#         "radius_km": radius_km,
#     }

def get_geo_features(lat: float, lon: float, radius_km: float = 10.0) -> Dict[str, Any]:
    """Return geo features map as base64 PNG centered on the given coordinates.

    Uses OpenStreetMap via staticmap library — no API key required.
    Falls back to local synthetic map if staticmap is not installed.
    """
    _ensure_loaded()
    try:
        from staticmap import StaticMap

        # 800x800 pixels, zoom 13 ≈ 10km radius
        zoom = max(10, min(15, round(14 - (radius_km / 5))))

        m = StaticMap(800, 800)
        img = m.render(zoom=zoom, center=[lon, lat])

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        image_bytes = buffer.getvalue()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        source = "openstreetmap"

    except ImportError:
        print("[get_geo_features] staticmap not installed, using local synthetic map",
              file=sys.stderr)
        path = os.path.join(DATA_DIR, "geo_features_map.png")
        with open(path, "rb") as f:
            image_bytes = f.read()
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        source = "local_synthetic"

    map_output_dir = os.environ.get("MAP_OUTPUT_DIR")
    if map_output_dir:
        fname = f"geo_map_{lat:.4f}_{lon:.4f}_{radius_km}km.png"
        out_path = os.path.join(map_output_dir, fname)
        with open(out_path, "wb") as f:
            f.write(image_bytes)
        print(f"[get_geo_features] saved map → {out_path}", file=sys.stderr)

    return {
        "image_base64": image_b64,
        "format": "png",
        "center": {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "source": source,
    }


def get_area_profile(lat: float, lon: float, radius_m: int = 1000) -> Dict[str, Any]:
    """Query OpenStreetMap via osmnx for land use profile around a given coordinate."""
    try:
        import osmnx as ox
        from collections import Counter

        tags = {
            "landuse": True,
            "amenity": ["hospital", "school", "university", "college"],
            "railway": ["station", "rail"],
            "building": ["hospital", "school", "university"],
        }
        gdf = ox.features_from_point((lat, lon), tags=tags, dist=radius_m)

        profile = {
            "has_hospital": False,
            "has_school": False,
            "has_railway": False,
            "dominant_landuse": "unknown",
            "landuse_summary": {},
            "source": "openstreetmap",
        }

        landuse_types = []
        for _, row in gdf.iterrows():
            landuse = row.get("landuse")
            if landuse and isinstance(landuse, str):
                landuse_types.append(landuse)

            amenity = row.get("amenity")
            if amenity == "hospital":
                profile["has_hospital"] = True
            if amenity in ("school", "university", "college"):
                profile["has_school"] = True

            building = row.get("building")
            if building == "hospital":
                profile["has_hospital"] = True
            if building in ("school", "university"):
                profile["has_school"] = True

            railway = row.get("railway")
            if railway in ("station", "rail"):
                profile["has_railway"] = True

        landuse_counts = Counter(landuse_types)
        profile["dominant_landuse"] = (
            landuse_counts.most_common(1)[0][0] if landuse_counts else "unknown"
        )
        profile["landuse_summary"] = dict(landuse_counts)

        return profile

    except Exception as exc:
        return {
            "error": str(exc),
            "dominant_landuse": "unknown",
            "landuse_summary": {},
            "has_hospital": None,
            "has_school": None,
            "has_railway": None,
            "source": "openstreetmap",
        }


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    """Return a single outage ticket by ID, or null if not found."""
    _ensure_loaded()
    for ticket in _tickets_data["tickets"]:
        if ticket["ticket_id"] == ticket_id:
            return ticket
    return None


def get_all_tickets() -> List[Dict[str, Any]]:
    _ensure_loaded()
    """Return all outage tickets."""
    return _tickets_data["tickets"]


# ---------------------------------------------------------------------------
# Tool registry — maps tool name → (callable, input JSON schema)
# ---------------------------------------------------------------------------

_TOOLS = {
    "get_kpi_history": (
        get_kpi_history,
        {
            "type": "object",
            "properties": {
                "usid": {"type": "string", "description": "Site identifier, e.g. 'USID_19'"},
            },
            "required": ["usid"],
        },
    ),
    "get_kpi_timeseries": (
        get_kpi_timeseries,
        {
            "type": "object",
            "properties": {
                "usid":      {"type": "string", "description": "Site identifier"},
                "start_utc": {"type": "string", "description": "Window start in ISO 8601 UTC"},
                "end_utc":   {"type": "string", "description": "Window end in ISO 8601 UTC"},
            },
            "required": ["usid", "start_utc", "end_utc"],
        },
    ),
    "get_site_attributes": (
        get_site_attributes,
        {
            "type": "object",
            "properties": {
                "usid": {"type": "string", "description": "Site identifier"},
            },
            "required": ["usid"],
        },
    ),
    "get_all_site_attributes": (
        get_all_site_attributes,
        {"type": "object", "properties": {}},
    ),
    "get_coverage_pixels": (
        get_coverage_pixels,
        {
            "type": "object",
            "properties": {
                "usid": {"type": "string", "description": "Parent USID (e.g. 'USID_09') or sector ID (e.g. 'USID_09_S2')"},
            },
            "required": ["usid"],
        },
    ),
    "get_coverage_pixels_by_sector": (
        get_coverage_pixels_by_sector,
        {
            "type": "object",
            "properties": {
                "sector_id": {"type": "string", "description": "Sector-level ID, e.g. 'USID_09_S2'"},
            },
            "required": ["sector_id"],
        },
    ),
    "get_preprocessing_stats": (
        get_preprocessing_stats,
        {
            "type": "object",
            "properties": {
                "usid": {"type": "string", "description": "Parent USID to retrieve preprocessing stats for"},
            },
            "required": ["usid"],
        },
    ),
    "get_geo_features": (
        get_geo_features,
        {
            "type": "object",
            "properties": {
                "lat":       {"type": "number", "description": "Latitude of the center point (from ticket)"},
                "lon":       {"type": "number", "description": "Longitude of the center point (from ticket)"},
                "radius_km": {"type": "number", "description": "Radius of the area to fetch in km (default 10.0)"},
            },
            "required": ["lat", "lon"],
        },
    ),
    "get_area_profile": (
        get_area_profile,
        {
            "type": "object",
            "properties": {
                "lat":      {"type": "number",  "description": "Latitude of the center point (from ticket)"},
                "lon":      {"type": "number",  "description": "Longitude of the center point (from ticket)"},
                "radius_m": {"type": "integer", "description": "Search radius in meters (default 1000)"},
            },
            "required": ["lat", "lon"],
        },
    ),
    "get_ticket": (
        get_ticket,
        {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket ID, e.g. 'TKT-2026-04-19-0000'"},
            },
            "required": ["ticket_id"],
        },
    ),
    "get_all_tickets": (
        get_all_tickets,
        {"type": "object", "properties": {}},
    ),
}

# ---------------------------------------------------------------------------
# MCP stdio transport — Content-Length framed JSON-RPC 2.0
# ---------------------------------------------------------------------------

def _send(msg: dict) -> None:
    """Write one JSON-RPC message to stdout as newline-delimited JSON."""
    body = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(body + "\n")
    sys.stdout.flush()

# def _recv() -> Optional[dict]:
#     """Read one Content-Length framed JSON-RPC message from stdin. Returns None on EOF."""
#     headers: Dict[str, str] = {}
#     while True:
#         raw = sys.stdin.buffer.readline()
#         if not raw:
#             return None  # stdin closed
#         line = raw.decode("utf-8").rstrip("\r\n")
#         if line == "":
#             break  # blank line separates headers from body
#         if ":" in line:
#             k, _, v = line.partition(":")
#             headers[k.strip()] = v.strip()

#     length = int(headers.get("Content-Length", 0))
#     if length == 0:
#         return None
#     body = sys.stdin.buffer.read(length)
#     return json.loads(body)

def _recv() -> Optional[dict]:
    """Read one JSON-RPC message from stdin. Supports both
    Content-Length framed and newline-delimited formats."""
    line = sys.stdin.buffer.readline()
    if not line:
        return None
    
    line = line.strip()
    if not line:
        return None
    
    # 如果是 Content-Length header，走原来的逻辑
    if line.startswith(b"Content-Length:"):
        headers = {}
        headers["Content-Length"] = line.split(b":")[1].strip().decode()
        # 读空行
        sys.stdin.buffer.readline()
        length = int(headers["Content-Length"])
        body = sys.stdin.buffer.read(length)
        return json.loads(body)
    
    # 否则直接解析这一行为 JSON
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _handle(msg: dict) -> Optional[dict]:
    """Dispatch one JSON-RPC message. Returns a response dict or None for notifications."""
    method  = msg.get("method", "")
    msg_id  = msg.get("id")          # None for notifications
    params  = msg.get("params") or {}

    with open('/tmp/mcp_debug.log', 'a') as f:
        f.write(f"received method: {method}\n")
    # --- Notifications (no response) ---
    if method in ("initialized", "notifications/cancelled", "notifications/progress"):
        return None

    # --- initialize ---
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "telecom_data", "version": "1.0.0"},
            },
        }

    # --- ping ---
    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    # --- tools/list ---
    if method == "tools/list":
        tools = [
            {
                "name": name,
                "description": fn.__doc__.strip().splitlines()[0],
                "inputSchema": schema,
            }
            for name, (fn, schema) in _TOOLS.items()
        ]
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}}

    # --- tools/call ---
    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}

        if tool_name not in _TOOLS:
            return _error(msg_id, -32601, f"Unknown tool: {tool_name!r}")

        fn, _ = _TOOLS[tool_name]
        try:
            result = fn(**arguments)
        except Exception as exc:
            return _error(msg_id, -32603, str(exc))

        # For tools that return an image, emit a proper MCP image content block
        # so the Claude agent can render it visually, plus a text block with metadata.
        if isinstance(result, dict) and "image_base64" in result:
            meta = {k: v for k, v in result.items() if k != "image_base64"}
            content = [
                {
                    "type": "image",
                    "data": result["image_base64"],
                    "mimeType": "image/png",
                },
                {"type": "text", "text": json.dumps(meta, ensure_ascii=False)},
            ]
        else:
            content = [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"content": content},
        }

    # --- unknown method ---
    if msg_id is not None:
        return _error(msg_id, -32601, f"Method not found: {method!r}")
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("[startup] telecom_data MCP server ready (stdio transport)", file=sys.stderr)
    # with open('/tmp/mcp_stdin.log', 'ab') as f:
    #     raw = sys.stdin.buffer.read(1000)
    #     f.write(raw)
    
    while True:
        msg = _recv()
        if msg is None:
            break
        response = _handle(msg)
        if response is not None:
            _send(response)
    print("[shutdown] stdin closed, exiting.", file=sys.stderr)
