"""Build resource/explore/event_rules.json: one rule per known event (resource/map_data/events.json).

    python tools/build_event_rules.py [--check] [--list]

For every distinct event name the options seen in the wiki transcripts / live runs are merged and scored with the
default weights of resource/explore/policy.default.json (effects such as gain_artifact, heal, lose_health ...).
  * events with structured option effects get a `prefer` (clear best option) and `avoid` (clearly harmful options);
  * events without effect data only get `avoid` for risky labels (闯入/硬闯/伏击/缴械) - nothing is invented;
  * `basis` says which of the two applied, `evidence` per option says how sure the data is.
The agent applies them as SOFT rules (+-2 score) when policy event.use_known_rules is true; hard overrides in
policy.default.json (live verified) or the user's config/explore_policy.json event.overrides always win.
"""

import argparse
import json
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
from morimens_logic import decisions, policy as P  # noqa: E402

EVENTS = ROOT / "resource" / "map_data" / "events.json"
OUT = ROOT / "resource" / "explore" / "event_rules.json"
EVIDENCE_RANK = {"live_verified": 2, "explicit_wiki_text": 1, "unclassified": 0}


def build():
    pol = P.load_default()
    known = {k for k in pol["event"].get("overrides", {})}
    events = json.loads(EVENTS.read_text(encoding="utf-8"))["events"]
    groups = OrderedDict()
    for ev in events:
        name = ev["event"]
        if name in ("未知", "", None):
            continue
        g = groups.setdefault(name, {"seen": 0, "maps": set(), "options": OrderedDict()})
        g["seen"] += 1
        if ev.get("map_id"):
            g["maps"].add(ev["map_id"])
        for opt in ev.get("options", []):
            cur = g["options"].setdefault(opt["label"], {"effects": [], "evidence": "unclassified"})
            effects = [e for e in opt.get("effects", []) if isinstance(e, dict)]
            conf = opt.get("effect_confidence", "live_verified" if effects else "unclassified")
            if effects and EVIDENCE_RANK.get(conf, 0) >= EVIDENCE_RANK[cur["evidence"]]:
                cur["effects"], cur["evidence"] = effects, conf
    rules = OrderedDict()
    for name in sorted(groups):
        g = groups[name]
        rows = []
        for label, o in g["options"].items():
            score = decisions.score_option(pol, o["effects"], None, None)      # effects only, no label keywords
            rows.append({"label": label, "effects": sorted({e["type"] for e in o["effects"]}), "evidence": o["evidence"],
                         "score": round(score, 2)})
        structured = [r for r in rows if r["effects"]]
        prefer, avoid = [], []
        if structured:
            basis = "effects"
            top = max(r["score"] for r in rows)
            best = [r for r in rows if r["score"] == top]
            if top > 0 and len(best) == 1:
                prefer = [best[0]["label"]]
            avoid = [r["label"] for r in rows if r["score"] <= -3]
        else:
            basis = "labels"
            avoid = [r["label"] for r in rows if decisions._keyword_hit(r["label"], pol["event"]["risky_keywords"])]
        rules[name] = {"basis": basis, "prefer": prefer, "avoid": avoid, "seen": g["seen"],
                       "maps": sorted(g["maps"]), "options": rows, "hard_override_in_default_policy": name in known}
    return {"_doc": "由 tools/build_event_rules.py 从 resource/map_data/events.json 生成，请不要手改；要改某个事件的选择，"
                    "在 config/explore_policy.json 的 event.overrides 里写同名事件（硬规则，优先于这里的软规则）。"
                    "关闭这些规则：event.use_known_rules=false。",
            "weights_used": pol["event"]["weights"], "rules": rules}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true", help="print one line per known event")
    args = ap.parse_args()
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if args.list:
        for name, r in data["rules"].items():
            print(f"{name}\t{r['basis']}\t选:{'/'.join(r['prefer']) or '-'}\t避:{'/'.join(r['avoid']) or '-'}\t"
                  f"{'/'.join(o['label'] for o in r['options'])}")
        return
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != text:
            sys.exit("event_rules.json is out of date: run python tools/build_event_rules.py")
        print("event rules are up to date")
        return
    OUT.write_text(text, encoding="utf-8")
    rules = data["rules"]
    print(f"{len(rules)} events -> {OUT.relative_to(ROOT)} "
          f"({sum(r['basis'] == 'effects' for r in rules.values())} with effect data, "
          f"{sum(bool(r['prefer']) for r in rules.values())} with a preferred option, "
          f"{sum(bool(r['avoid']) for r in rules.values())} with avoided options)")


if __name__ == "__main__":
    main()
