"""Catalogues of the activity stages and the 记忆回廊 route -> resource/map_data/{activity_stages,train_corridor}.json

    python tools/build_stage_catalog.py [--check]

activity_stages.json: every 活动 / 支线 stage of the client grouped by activity (client `s`), with level range, stage
count, whether a map exists (stage -> maps_client) and which of our activity profiles / gallery covers it.
train_corridor.json: the 记忆回廊 (疾驰的欢愉专列) route of the client: per difficulty (普通 / 困难 / 癫狂) the phases
(初始化, 三次共鸣阶段) with the chapter pool of each phase, and per chapter the node sequence (fixed event, 褪色遗骨,
灰烬遗迹, random nodes with their number of variants). The fixed event of each chapter is the one the agent has to decide.
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "resource" / "map_data"
NAV = ROOT / "resource" / "navigation"


def build_activities():
    stages = json.loads((DATA / "client/stages.json").read_text(encoding="utf-8"))
    maps = json.loads((DATA / "maps_client.json").read_text(encoding="utf-8"))["maps"]
    stage_map = defaultdict(list)
    for mid, m in maps.items():
        for sid in m.get("stage_ids", []):
            stage_map[str(sid)].append(mid)
    covered = {}
    for p in sorted((NAV / "activity_profiles").glob("*.json")):
        if p.name.startswith("_"):
            continue
        prof = json.loads(p.read_text(encoding="utf-8"))
        covered[prof.get("label") or p.stem] = f"activity_profiles/{p.name}"
    gal = json.loads((NAV / "activity_gallery.json").read_text(encoding="utf-8"))
    covered[gal["activity"]] = "activity_gallery.json"
    acts = defaultdict(list)
    for sid, st in stages.items():
        if st["c"] == "活动 / 支线":
            acts[st["s"]].append((int(sid), st))
    out = []
    for name, items in sorted(acts.items()):
        items.sort()
        lv = [st["lv"] for _, st in items]
        with_map = sum(1 for sid, _ in items if str(sid) in stage_map)
        out.append(OrderedDict([
            ("activity", name), ("stages", len(items)), ("lv", [min(lv), max(lv)]), ("with_map", with_map),
            ("names", sorted({st["n"] for _, st in items})[:12]),
            ("stage_ids", [sid for sid, _ in items])]))
    return {"schema": 1, "count": len(out),
            "note": "client activity names are keyed by character / event id; our profiles are keyed by the in-game "
                    "title, so the link is not automatic (see our_profiles).",
            "our_profiles": covered, "activities": out}


def build_train():
    t = json.loads((DATA / "client/train.json").read_text(encoding="utf-8"))
    groups = t["groups"]
    chapters = OrderedDict()
    for gid, g in groups.items():
        nodes = g["nodes"]
        fixed = [n for n in nodes if n[1] not in ("随机节点", "褪色遗骨", "灰烬遗迹")]
        chapters[gid] = OrderedDict([
            ("name", g["cn"]), ("length", len(nodes)),
            ("sequence", [n[1] for n in nodes]),
            ("event", fixed[0][3] if fixed and len(fixed[0]) > 3 else (fixed[0][1] if fixed else "")),
            ("random_variants", [len(n[2]) for n in nodes if n[1] == "随机节点"])])
    routes = OrderedDict()
    for rid, phases in t["stages"].items():
        route = []
        for ph in phases:
            route.append(OrderedDict([("phase", ph["cn"]), ("kind", "resonance" if ph["t"] == "D" else "chapters"),
                                      ("groups", ph["g"]),
                                      ("events", [chapters[str(g)]["event"] or chapters[str(g)]["name"] for g in ph["g"]
                                                  if str(g) in chapters])]))
        diff = next((p["phase"] for p in route if p["kind"] == "chapters"), "")
        routes[rid] = OrderedDict([("difficulty", diff), ("phases", route)])
    return {"schema": 1, "note": "route of the client's 记忆回廊; each chapter pool has four chapters, one is drawn per phase",
            "chapters": chapters, "routes": routes,
            "difficulties": dict(Counter(r["difficulty"] for r in routes.values()))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    files = {"activity_stages.json": build_activities(), "train_corridor.json": build_train()}
    bad = 0
    for name, data in files.items():
        text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
        path = DATA / name
        if a.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                print(name, "out of date")
                bad = 1
        else:
            path.write_text(text, encoding="utf-8")
    if a.check:
        print("stage catalogues " + ("out of date" if bad else "up to date"))
    else:
        print("activities", files["activity_stages.json"]["count"], "train routes", len(files["train_corridor.json"]["routes"]),
              files["train_corridor.json"]["difficulties"])
    return bad


if __name__ == "__main__":
    sys.exit(main())
