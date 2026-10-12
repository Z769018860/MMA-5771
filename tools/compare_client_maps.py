"""Match our screenshot-recognised maps (resource/map_data/maps.json) with the client maps and report differences.

    python tools/compare_client_maps.py [--write]      # --write stores client/aliases.json (our key -> client map id)

Both sides use the same lattice (row/col, neighbours (0,±2)/(±1,±1), normalised by the minimum), so a map is matched by
the shift (dr, dc) that makes most typed tiles agree. Our recognised tiles `cracked_rock` are client walls.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "resource" / "map_data"
SAME = {"cracked_rock": "wall", "purple_rift": "swamp", "red_flesh": "swamp", "unknown_icon": "event", "plain_weak": "plain"}
IGNORE = {"plain", "wall"}


def norm(ty):
    return SAME.get(ty, ty)


def best_alignment(ours, client):
    """ours/client: {(row, col): type}. Returns (matches, mismatches, shift) maximising typed-tile agreement."""
    o = {k: norm(v) for k, v in ours.items() if norm(v) not in IGNORE}
    c = {k: v for k, v in client.items() if v not in IGNORE}
    if not o or not c:
        return 0, 0, (0, 0)
    best = None
    a0 = next(iter(o))
    for k, v in c.items():
        if v != o[a0]:
            continue
        dr, dc = k[0] - a0[0], k[1] - a0[1]
        hit = sum(1 for p, t in o.items() if c.get((p[0] + dr, p[1] + dc)) == t)
        if best is None or hit > best[0]:
            best = (hit, len(o) - hit, (dr, dc))
    return best or (0, len(o), (0, 0))


def compare():
    ours = json.loads((DATA / "maps.json").read_text(encoding="utf-8"))["maps"]
    client = json.loads((DATA / "maps_client.json").read_text(encoding="utf-8"))["maps"]
    cgrid = {mid: {(t["row"], t["col"]): t["type"] for t in m["tiles"]} for mid, m in client.items()}
    ccount = {mid: Counter(t for t in g.values() if t not in IGNORE) for mid, g in cgrid.items()}
    stages = json.loads((DATA / "client" / "stages.json").read_text(encoding="utf-8"))
    by_cn = defaultdict(set)
    for s in stages.values():
        for mid in s.get("m", []):
            by_cn[s.get("cn", "")].add(str(mid))
    signature = {mid: tuple(sorted((t["row"], t["col"], t["type"]) for t in m["tiles"])) for mid, m in client.items()}
    twins = defaultdict(list)                     # identical layouts: normal / 困难 / 癫狂 versions of one stage
    for mid, sig in signature.items():
        twins[sig].append(mid)
    result = {}
    for key, m in ours.items():
        og = {(t["row"], t["col"]): t["type"] for t in m["tiles"]}
        ocount = Counter(norm(t) for t in og.values() if norm(t) not in IGNORE)
        cands = sorted(ccount, key=lambda mid: -sum((ocount & ccount[mid]).values()) / max(1, sum((ocount | ccount[mid]).values())))[:12]
        best = None
        for mid in cands:
            hit, miss, shift = best_alignment(og, cgrid[mid])
            score = hit / max(1, hit + miss + sum(1 for k, v in cgrid[mid].items() if v not in IGNORE) - hit)
            if best is None or score > best[0]:
                best = (score, mid, shift, hit, miss)
        mm = re.fullmatch(r"(\d+)-(\d+)", key)
        wrong = best[0] < 0.6
        if mm:                                    # main story: the stage's own map (cn 关卡@主线_X_Y) when it fits at least as well
            for cmid in sorted(by_cn.get(f"关卡@主线_{mm.group(1)}_{mm.group(2)}", ())):
                if cmid not in cgrid:
                    continue
                hit, miss, shift = best_alignment(og, cgrid[cmid])
                cscore = hit / max(1, hit + miss + sum(1 for v in cgrid[cmid].values() if v not in IGNORE) - hit)
                if cscore >= best[0] - 1e-9 or best[0] < 0.6:      # our recognition of this stage is wrong: trust the client
                    best = (cscore, cmid, shift, hit, miss)
        score, mid, (dr, dc), hit, miss = best
        cg = cgrid[mid]
        shifted = {(r + dr, c + dc): norm(t) for (r, c), t in og.items()}
        diffs = []
        for p in sorted(set(shifted) | set(cg)):
            a, b = shifted.get(p), cg.get(p)
            if a == b or (a in IGNORE and b in IGNORE and (a == "wall") == (b == "wall")):
                continue
            diffs.append({"at": [p[0] - dr, p[1] - dc], "ours": a, "client": b})
        result[key] = {"client_map": mid, "score": round(score, 3), "shift": [dr, dc], "stages": client[mid]["stage_names"],
                      "same_layout_maps": sorted(m2 for m2 in twins[signature[mid]] if m2 != mid), "diffs": diffs}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    res = compare()
    good = {k: v for k, v in res.items() if v["score"] >= 0.6}
    print(f"{len(res)} of our maps; matched (score>=0.6): {len(good)}")
    typed = Counter()
    for k, v in sorted(res.items()):
        d = [x for x in v["diffs"] if not (x["ours"] in IGNORE and x["client"] in IGNORE)]
        typed.update((x["ours"], x["client"]) for x in d)
        flag = "" if v["score"] >= 0.6 else "  <-- weak match"
        print(f"{k:12s} -> {v['client_map']:>6} score {v['score']:.2f} diffs {len(d):2d} {v['stages'][:1]}{flag}")
    print("most common (ours -> client) differences:", typed.most_common(14))
    if args.write:
        out = DATA / "client" / "aliases.json"
        out.write_bytes((json.dumps({"_doc": "我们识别出来的地图（maps.json 的 key）→ 客户端地图 id；score 是格子类型吻合度，shift 是两套格点的偏移。由 tools/compare_client_maps.py 生成。",
                                     "aliases": res}, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8"))
        print("wrote", out.relative_to(ROOT))


if __name__ == "__main__":
    main()
