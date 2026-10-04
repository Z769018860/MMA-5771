"""Merge resource/map_data/live_observations.json into events.json (idempotent).

    python tools/apply_live_observations.py

Existing wiki entries get matching options marked live_verified (effects replaced by the observed ones when given);
events or options the wiki does not have are appended with source_kind live_client.
"""

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "resource" / "map_data"


def main():
    path = DATA / "events.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    live = json.loads((DATA / "live_observations.json").read_text(encoding="utf-8"))["events"]
    events = doc["events"]
    for obs in live:
        entry = next((e for e in events if e["map_id"] == obs["map_id"] and e["event"] == obs["event"]), None)
        if entry is None:
            entry = {"map_id": obs["map_id"], "map_link_confidence": "live_client", "stage_page": None, "event": obs["event"],
                     "event_image": None, "options": [], "source": "live client", "source_kind": "live_client",
                     "source_confidence": "live_verified"}
            events.append(entry)
        for key in ("trigger", "note"):
            if obs.get(key):
                entry[f"live_{key}"] = obs[key]
        entry["source_confidence"] = "live_verified" if entry["source_kind"] == "live_client" else "wiki_plus_live"
        for o in obs["options"]:
            opt = next((x for x in entry["options"] if x["label"] == o["label"]), None)
            if opt is None:
                opt = {"label": o["label"], "effects": [], "effect_confidence": "unclassified"}
                entry["options"].append(opt)
            if o.get("effects"):
                opt["effects"] = o["effects"]
                opt["effect_confidence"] = "live_verified"
            if o.get("result"):
                opt["live_result"] = o["result"]
            opt["live_verified"] = True
    doc["counts"]["events"] = len(events)
    doc["counts"]["live_verified_events"] = sum(1 for e in events if e.get("source_confidence") in ("live_verified", "wiki_plus_live"))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(doc["counts"])


if __name__ == "__main__":
    main()
