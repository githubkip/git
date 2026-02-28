#!/usr/bin/env python3
"""Fetch Plain City parcel polygons from Weber County ArcGIS services.

Step 2 implementation:
- Pull Plain City boundary geometry
- Spatially query parcel layer that intersects boundary
- Export a GeoJSON FeatureCollection to data/plain_city_parcels.geojson

No third-party dependencies required.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

BOUNDARY_QUERY_URL = (
    "https://maps.webercountyutah.gov/arcgis/rest/services/"
    "cities/weber_eoc_city_boundaries/MapServer/0/query"
)
PARCEL_QUERY_URL = (
    "https://maps.webercountyutah.gov/arcgis/rest/services/"
    "assessor/Assessed_Values_Map/FeatureServer/0/query"
)

DEFAULT_OUTFILE = Path("data/plain_city_parcels.geojson")
DEFAULT_FIELDS = [
    "OBJECTID",
    "PARCEL_ID",
    "STREET",
    "CITY_STATE",
    "ZIPCODE",
    "PROP_STREET",
    "PROP_CITY",
    "PROP_ZIP",
    "NAME_ONE",
]


def post_json(url: str, params: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
    payload = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_plain_city_geometry() -> Dict[str, Any]:
    result = post_json(
        BOUNDARY_QUERY_URL,
        {
            "where": "NAME='Plain City'",
            "outFields": "NAME",
            "returnGeometry": "true",
            "f": "json",
        },
    )

    features = result.get("features", [])
    if not features:
        raise RuntimeError("Plain City boundary not found in boundary dataset")
    return features[0]["geometry"]


def get_intersecting_object_ids(geometry: Dict[str, Any]) -> List[int]:
    result = post_json(
        PARCEL_QUERY_URL,
        {
            "where": "1=1",
            "returnIdsOnly": "true",
            "geometryType": "esriGeometryPolygon",
            "geometry": json.dumps(geometry),
            "spatialRel": "esriSpatialRelIntersects",
            "inSR": "3560",  # boundary layer SR (NAD83 / Utah Central ftUS)
            "f": "json",
        },
    )
    object_ids = result.get("objectIds", [])
    if not object_ids:
        return []
    return sorted(object_ids)


def fetch_features_by_ids(
    object_ids: List[int],
    out_fields: List[str],
    chunk_size: int = 400,
    pause_seconds: float = 0.0,
) -> List[Dict[str, Any]]:
    features: List[Dict[str, Any]] = []

    for i in range(0, len(object_ids), chunk_size):
        chunk = object_ids[i : i + chunk_size]
        result = post_json(
            PARCEL_QUERY_URL,
            {
                "objectIds": ",".join(str(v) for v in chunk),
                "outFields": ",".join(out_fields),
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            },
        )

        chunk_features = result.get("features", [])
        features.extend(chunk_features)

        print(
            f"Fetched chunk {i // chunk_size + 1} "
            f"({len(chunk_features)} features, total={len(features)})"
        )
        if pause_seconds > 0:
            time.sleep(pause_seconds)

    return features


def build_geojson(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "name": "plain_city_parcels",
        "features": features,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch Plain City parcels into GeoJSON")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTFILE)
    p.add_argument("--chunk-size", type=int, default=400)
    p.add_argument("--pause", type=float, default=0.0)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    print("Loading Plain City boundary geometry...")
    boundary_geometry = get_plain_city_geometry()

    print("Querying intersecting parcel ObjectIDs...")
    object_ids = get_intersecting_object_ids(boundary_geometry)
    print(f"Found {len(object_ids)} parcels intersecting Plain City boundary")

    features = fetch_features_by_ids(
        object_ids,
        out_fields=DEFAULT_FIELDS,
        chunk_size=max(1, args.chunk_size),
        pause_seconds=max(0.0, args.pause),
    )

    geojson = build_geojson(features)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(geojson), encoding="utf-8")

    print(f"Wrote {len(features)} features to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
