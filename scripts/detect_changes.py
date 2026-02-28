#!/usr/bin/env python3
"""Detect parcel dataset changes and optionally send Telegram summary.

Compares current GeoJSON with the last snapshot using PARCEL_ID as key.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

DEFAULT_CURRENT = Path("data/plain_city_parcels.geojson")
DEFAULT_BASELINE = Path("data/plain_city_parcels_last.geojson")
DEFAULT_SUMMARY = Path("data/plain_city_changes_summary.json")

COMPARE_FIELDS = [
    "STREET",
    "CITY_STATE",
    "ZIPCODE",
    "PROP_STREET",
    "PROP_CITY",
    "PROP_ZIP",
    "NAME_ONE",
]


def load_geojson(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    return json.loads(path.read_text(encoding="utf-8"))


def geometry_hash(feature: Dict[str, Any]) -> str:
    geom = feature.get("geometry")
    payload = json.dumps(geom, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def to_index(geojson: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for ft in geojson.get("features", []):
        props = ft.get("properties", {})
        parcel_id = props.get("PARCEL_ID")
        if not parcel_id:
            continue
        snapshot = {
            "parcel_id": parcel_id,
            "geometry_hash": geometry_hash(ft),
            "properties": {k: props.get(k) for k in COMPARE_FIELDS},
        }
        index[str(parcel_id)] = snapshot
    return index


def compare(
    previous: Dict[str, Dict[str, Any]], current: Dict[str, Dict[str, Any]]
) -> Tuple[list[str], list[str], list[Dict[str, Any]]]:
    prev_ids = set(previous.keys())
    curr_ids = set(current.keys())

    added = sorted(curr_ids - prev_ids)
    removed = sorted(prev_ids - curr_ids)

    changed: list[Dict[str, Any]] = []
    for pid in sorted(prev_ids & curr_ids):
        prev = previous[pid]
        curr = current[pid]
        field_changes = {}

        if prev.get("geometry_hash") != curr.get("geometry_hash"):
            field_changes["geometry"] = {
                "before": prev.get("geometry_hash"),
                "after": curr.get("geometry_hash"),
            }

        for k in COMPARE_FIELDS:
            if prev["properties"].get(k) != curr["properties"].get(k):
                field_changes[k] = {
                    "before": prev["properties"].get(k),
                    "after": curr["properties"].get(k),
                }

        if field_changes:
            changed.append({"parcel_id": pid, "changes": field_changes})

    return added, removed, changed


def send_telegram_message(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram not configured; skipping alert send")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API returned error: {data}")


def build_message(summary: Dict[str, Any]) -> str:
    stats = summary["stats"]
    lines = [
        "Plain City parcel change summary",
        f"Current parcels: {stats['current_total']}",
        f"Added: {stats['added_count']}",
        f"Removed: {stats['removed_count']}",
        f"Changed: {stats['changed_count']}",
    ]

    sample = summary.get("samples", {})
    if sample.get("added"):
        lines.append(f"Sample added: {', '.join(sample['added'])}")
    if sample.get("removed"):
        lines.append(f"Sample removed: {', '.join(sample['removed'])}")
    if sample.get("changed"):
        lines.append(f"Sample changed: {', '.join(sample['changed'])}")

    lines.append("(Changes reflect dataset updates, not verified residency changes.)")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect parcel changes and optionally send Telegram alert")
    p.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    p.add_argument("--sample-size", type=int, default=10)
    p.add_argument("--send-telegram", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if not args.current.exists():
        raise FileNotFoundError(f"Current parcel file not found: {args.current}")

    current_geojson = load_geojson(args.current)
    current_idx = to_index(current_geojson)

    if not args.baseline.exists():
        shutil.copyfile(args.current, args.baseline)
        summary = {
            "status": "initialized",
            "message": "Baseline created from current parcel dataset; no diff available yet.",
            "stats": {
                "current_total": len(current_idx),
                "added_count": 0,
                "removed_count": 0,
                "changed_count": 0,
            },
        }
        args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(summary["message"])
        return 0

    previous_geojson = load_geojson(args.baseline)
    previous_idx = to_index(previous_geojson)

    added, removed, changed = compare(previous_idx, current_idx)

    summary = {
        "status": "ok",
        "stats": {
            "current_total": len(current_idx),
            "previous_total": len(previous_idx),
            "added_count": len(added),
            "removed_count": len(removed),
            "changed_count": len(changed),
        },
        "samples": {
            "added": added[: args.sample_size],
            "removed": removed[: args.sample_size],
            "changed": [x["parcel_id"] for x in changed[: args.sample_size]],
        },
        "details": {
            "added": added,
            "removed": removed,
            "changed": changed,
        },
    }

    args.summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    shutil.copyfile(args.current, args.baseline)

    msg = build_message(summary)
    print(msg)

    if args.send_telegram:
        send_telegram_message(msg)
        print("Telegram alert sent")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
