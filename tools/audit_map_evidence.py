"""Check the source image of every structured map and link stage event evidence.

Usage: python tools/audit_map_evidence.py
"""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "resource/map_data"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    maps = read(DATA / "maps.json")["maps"]
    events = read(DATA / "events.json")["events"]
    routes = read(DATA / "route_check.json")
    main_manifest = read(ROOT / "tools/resource/reference_maps/huiji_maps_1-9.json")
    special_manifest = read(ROOT / "resource/reference_maps_special/manifest.json")
    main_sources = {f"{r['chapter']}-{r['stage']}": r for r in main_manifest["maps"]}
    special_sources = {r["name"].removesuffix("_map.jpg"): r for r in special_manifest["files"]
                       if r["name"].endswith("_map.jpg") and r.get("sha1")}
    by_map = defaultdict(list)
    for event in events:
        if event["map_id"]:
            by_map[event["map_id"]].append(event)
    result = {}
    for mid, entry in maps.items():
        if mid in main_sources:
            source = main_sources[mid]
            image = ROOT / "tools/resource/reference_maps/images" / f"{mid}.jpg"
        else:
            source = special_sources.get(mid, {})
            image = ROOT / "resource/reference_maps_special/images" / f"{mid}_map.jpg"
        expected = source.get("sha1")
        verified = bool(expected and image.is_file() and hashlib.sha1(image.read_bytes()).hexdigest() == expected)
        stage_events = by_map[mid]
        result[mid] = {
            "source_image": source.get("image_url"),
            "source_image_sha1_verified": verified,
            "source_image_dimensions": [source.get("width"), source.get("height")],
            "recognized_tiles": entry["tile_count"],
            "generic_event_tiles": entry["counts"].get("event", 0),
            "stage_event_entries": len(stage_events),
            "stage_event_link": dict(Counter(e["map_link_confidence"] for e in stage_events)),
            "route_status": routes.get(mid, {}).get("status", "missing"),
            "tile_to_specific_event_known": False,
        }
    out = {
        "schema": 1,
        "note": "SHA-1 verifies source bytes, not tile recognition accuracy. Stage event entries are possible events in a stage, not assigned to individual hexes. Route status depends on the current inferred movement rules.",
        "summary": {
            "maps": len(result),
            "images_verified": sum(x["source_image_sha1_verified"] for x in result.values()),
            "maps_with_stage_events": sum(x["stage_event_entries"] > 0 for x in result.values()),
            "routes_found": sum(x["route_status"] == "ok" for x in result.values()),
        },
        "maps": result,
    }
    (DATA / "map_evidence.json").write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    print(out["summary"])


if __name__ == "__main__":
    main()
