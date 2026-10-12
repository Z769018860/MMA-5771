"""Catalogue of the 幻梦深潜 map layouts -> resource/map_data/dive_layouts.json

    python tools/build_dive_layouts.py [--check]

The client has 24 layout styles per 篇 (忘却篇 / 星辰篇); every difficulty (I..VII, 癫狂 at several levels) draws one
of them at random, so the map is only known once the run is on screen (live fact `dive_random_layout`). The catalogue
lists, per 篇 and style, the client map id, tile/node counts, the stages that use it and the route-check status, so the
agent can identify the layout from the first screens (Knowledge.identify_map) and route on the exact map.
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "resource" / "map_data"
OUT = DATA / "dive_layouts.json"
ROMAN = "ⅠⅡⅢⅣⅤⅥⅦ"


def build():
    stages = json.loads((DATA / "client/stages.json").read_text(encoding="utf-8"))
    maps = json.loads((DATA / "maps_client.json").read_text(encoding="utf-8"))["maps"]
    check = json.loads((DATA / "route_check_client.json").read_text(encoding="utf-8"))
    layouts = {}
    for sid, st in stages.items():
        if not st["n"].startswith("幻梦深潜"):
            continue
        suffix = st["n"][4:].lstrip("·")
        diff = ROMAN.index(suffix) + 1 if suffix in ROMAN else suffix
        for mid in st["m"]:
            key = f'{st["s"]}:{mid}'
            e = layouts.setdefault(key, {"pian": st["s"], "map": str(mid), "difficulties": {}})
            e["difficulties"].setdefault(str(diff), []).append({"stage": int(sid), "lv": st["lv"]})
    out = []
    for key, e in sorted(layouts.items(), key=lambda kv: (kv[1]["pian"], int(kv[1]["map"]))):
        m = maps.get(e["map"], {})
        chk = check.get(m.get("cn", ""), check.get(e["map"], {}))
        e["cn"] = m.get("cn", "")
        e["tiles"] = m.get("tile_count", 0)
        e["nodes"] = dict(m.get("counts", {}))
        e["route"] = {k: chk[k] for k in ("status", "steps", "keys", "doors", "islands") if k in chk}
        e["difficulties"] = {d: sorted(v, key=lambda x: x["stage"]) for d, v in sorted(e["difficulties"].items(), key=lambda kv: str(kv[0]))}
        out.append(e)
    summary = Counter(e["pian"] for e in out)
    return {"schema": 1,
            "note": "Each run draws one layout of its 篇 at random (live-verified, live_facts.dive_random_layout); "
                    "identify it from the first screens, then route on the exact client map.",
            "count": dict(summary), "layouts": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if a.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print("dive_layouts.json out of date")
            return 1
        print("ok")
        return 0
    OUT.write_text(text, encoding="utf-8")
    d = json.loads(text)
    print("layouts", d["count"], "route status", Counter(e["route"].get("status") for e in d["layouts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
