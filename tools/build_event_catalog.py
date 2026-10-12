"""Aggregate every known event into resource/map_data/events_all.json.

    python tools/build_event_catalog.py [--check]

Sources: events.json (wiki transcripts + live runs), live_facts.json (what the live runs showed), and the client map
data (client/node_types.json + maps_client.json), which tells which node kinds exist and on which maps they sit.
One entry per event name: merged options with evidence, the client node kind of the same name (named events such as
血污之池 / 监察点 / 古怪脓疱 are node types of their own), the client maps and stages where that node appears, and
whether a live run saw it. `tile_kinds` lists every node kind of the client with its tile counts, so the whole
vocabulary of the map is in one place. Run tools/build_event_rules.py afterwards (the rules read events.json).
"""

import argparse
import json
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "resource" / "map_data"
OUT = DATA / "events_all.json"
RANK = {"live_verified": 2, "explicit_wiki_text": 1, "unclassified": 0}


def build():
    events = json.loads((DATA / "events.json").read_text(encoding="utf-8"))["events"]
    facts = json.loads((DATA / "live_facts.json").read_text(encoding="utf-8"))["facts"]
    types = json.loads((DATA / "client" / "node_types.json").read_text(encoding="utf-8"))
    client = json.loads((DATA / "maps_client.json").read_text(encoding="utf-8"))["maps"]
    by_name = defaultdict(list)
    for t in types:
        by_name[t["name"]].append(t)
    # tile kinds: node type name -> tiles and maps (client data)
    kinds = OrderedDict()
    node_name = {t["id"]: t["name"] for t in types}
    node_table = json.loads((DATA / "client" / "nodes.json").read_text(encoding="utf-8"))
    occ = defaultdict(lambda: {"tiles": 0, "maps": set()})
    for mid, m in client.items():
        for t in m["tiles"]:
            if t.get("node"):
                name = t["node_type"]
                occ[name]["tiles"] += 1
                occ[name]["maps"].add(mid)
    for name in sorted(occ, key=lambda n: -occ[n]["tiles"]):
        ts = by_name.get(name, [])
        kinds[name] = {"ours": sorted({t["ours"] for t in ts}), "node_type_ids": sorted(t["id"] for t in ts),
                       "desc": ts[0]["desc"] if ts else "", "tiles": occ[name]["tiles"], "maps": len(occ[name]["maps"])}
    # events by name
    groups = OrderedDict()
    for ev in events:
        name = ev["event"]
        if name in ("未知", ""):
            continue
        g = groups.setdefault(name, {"wiki_pages": set(), "wiki_maps": set(), "options": OrderedDict(), "sources": Counter(), "live": False})
        g["wiki_pages"].add(ev.get("stage_page") or "")
        if ev.get("map_id"):
            g["wiki_maps"].add(ev["map_id"])
        g["sources"][ev.get("source_kind", "?")] += 1
        for opt in ev.get("options", []):
            cur = g["options"].setdefault(opt["label"], {"effects": [], "evidence": "unclassified"})
            effects = [e for e in opt.get("effects", []) if isinstance(e, dict)]
            conf = opt.get("effect_confidence", "live_verified" if effects else "unclassified")
            if opt.get("live_verified"):
                conf = "live_verified"
                g["live"] = True
            if effects and RANK.get(conf, 0) >= RANK[cur["evidence"]]:
                cur["effects"], cur["evidence"] = effects, conf
        if ev.get("source_kind") == "live_client":
            g["live"] = True
    out = OrderedDict()
    for name in sorted(groups):
        g = groups[name]
        ts = by_name.get(name, [])
        entry = {"options": [{"label": l, "effects": sorted({e["type"] for e in o["effects"]}), "evidence": o["evidence"]}
                             for l, o in g["options"].items()],
                 "wiki_pages": len(g["wiki_pages"]), "wiki_maps": sorted(g["wiki_maps"]), "live_verified": g["live"]}
        if ts:
            entry["client_node"] = {"type_ids": sorted(t["id"] for t in ts), "desc": ts[0]["desc"],
                                    "tiles": kinds[name]["tiles"] if name in kinds else 0, "maps": kinds[name]["maps"] if name in kinds else 0}
        out[name] = entry
    # client node kinds that look like events but have no wiki entry (so we know what is still undocumented)
    undocumented = sorted(n for n, k in kinds.items() if n not in out and set(k["ours"]) & {"event", "strange_cyst", "honey_wine", "unfinished_statue", "kind_gift",
                                                                                          "mother_of_brood", "proxy_rite", "white_sail", "checkpoint", "detention",
                                                                                          "inquisitor", "enrollment", "shadow_pool"})
    # 记忆回廊: the fixed event of every chapter (from the client route); options are not documented yet
    train = json.loads((DATA / "client" / "train.json").read_text(encoding="utf-8"))["groups"]
    train_events = OrderedDict()
    for gid, g in train.items():
        fixed = [n for n in g["nodes"] if n[1] not in ("随机节点", "褪色遗骨", "灰烬遗迹")]
        if not fixed or fixed[0][1] == "指令节点":
            continue
        name = fixed[0][3] if len(fixed[0]) > 3 else fixed[0][1]
        e = train_events.setdefault(name, {"chapters": [], "text": fixed[0][4] if len(fixed[0]) > 4 else "", "in_event_library": name in out})
        if g["cn"] not in e["chapters"]:
            e["chapters"].append(g["cn"])
    return {"_doc": "由 tools/build_event_catalog.py 生成，请不要手改。events：每个事件名一条（选项+证据+客户端节点+实机是否见过）；"
                    "tile_kinds：客户端全部节点种类及数量；undocumented_event_kinds：客户端有、wiki/实机事件库还没有的事件类节点；live_facts：实机事实。",
            "counts": {"events": len(out), "with_client_node": sum(1 for e in out.values() if "client_node" in e),
                       "live_verified": sum(1 for e in out.values() if e["live_verified"]), "tile_kinds": len(kinds),
                       "undocumented_event_kinds": len(undocumented), "train_events": len(train_events),
                       "train_events_without_options": sum(1 for e in train_events.values() if not e["in_event_library"])},
            "events": out, "tile_kinds": kinds, "undocumented_event_kinds": undocumented, "train_events": train_events, "live_facts": facts}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            sys.exit("events_all.json is out of date: run python tools/build_event_catalog.py")
        print("event catalog is up to date")
        return
    OUT.write_bytes(text.encode("utf-8"))
    c = json.loads(text)["counts"]
    print(f"{c['events']} events ({c['with_client_node']} with a client node, {c['live_verified']} live verified), "
          f"{c['tile_kinds']} tile kinds, {c['undocumented_event_kinds']} undocumented event kinds -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
