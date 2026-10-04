"""Structural tests for the profile-driven activity advance generator (no game, no screenshots).

    python tools/test_activity_advance.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_activity_advance as A  # noqa: E402

ROOT = A.ROOT
failures, checks = [], 0


def expect(ok, text):
    global checks
    checks += 1
    if not ok:
        failures.append(text)


def all_nodes():
    out = {}
    for f in (ROOT / "resource" / "pipeline").glob("*.json"):
        out.update(json.loads(f.read_text(encoding="utf-8-sig")))
    return out


def check_profile(prof, label):
    nodes = A.build_nodes(prof)
    pool = {**all_nodes(), **nodes}
    P, n = prof["prefix"], len(prof["stages"])
    expect(all(k.startswith(P + "_") for k in nodes), f"{label}: node without prefix {P}_")
    missing = sorted({x for v in nodes.values() for x in v.get("next", []) if x not in pool})
    expect(not missing, f"{label}: dangling next {missing}")
    for i, st in enumerate(prof["stages"], 1):
        chain, cur = [], f"{P}_Stage{i}_ResetA" if prof.get("reset_swipes") else f"{P}_Stage{i}_Click"
        while cur in nodes and cur != f"{P}_Stage{i}_Click":
            chain.append(cur)
            cur = nodes[cur]["next"][0]
        expect(cur == f"{P}_Stage{i}_Click" and len(chain) == len(prof.get("reset_swipes", [])) + len(st.get("swipes", [])),
               f"{label}: stage {i} swipe chain {chain} -> {cur}")
        expect(nodes[f"{P}_Stage{i}_Click"]["target"][0] <= st["click"][0] <= nodes[f"{P}_Stage{i}_Click"]["target"][0] + 36,
               f"{label}: stage {i} click x")
        done = nodes[f"{P}_Completed{i}"]
        expect(("all_of" in done) == bool(st.get("title")) and (bool(st.get("title")) or done.get("max_hit") == 1),
               f"{label}: stage {i} completion node should be {'titled' if st.get('title') else 'counted (max_hit 1)'}")
        expect(done["next"] == ([f"{P}_BackToStage{i + 1}"] if i < n else []), f"{label}: stage {i} completion next")
    order = nodes[f"{P}_AfterResult"]["next"]
    expect(order == [*[f"{P}_Completed{i}" for i in range(1, n + 1)], f"{P}_AfterSix"], f"{label}: AfterResult order {order}")
    tasks = A.profile_tasks(prof)
    expect(len(tasks) == n + 1 and all(t["entry"] == f"{P}_Start" for t in tasks), f"{label}: tasks")
    for t in tasks:
        refs = {x for v in t["pipeline_override"].values() for x in v.get("next", [])}
        expect(all(x in pool for x in refs), f"{label}: task {t['name']} override refers to unknown nodes {sorted(refs - set(pool))}")
        expect(f"{P}_StagePage" in t["pipeline_override"]["ActEntry"]["next"], f"{label}: generic entry must reach {P}_StagePage")
    return nodes


for prof in A.load_profiles():
    nodes = check_profile(prof, prof["id"])
    on_disk = json.loads((ROOT / "resource" / "pipeline" / prof["pipeline"]).read_text(encoding="utf-8-sig"))
    expect(on_disk == nodes, f"{prof['id']}: generated pipeline on disk is stale")
# the template profile must produce a valid, collision-free pipeline too
template = json.loads((A.PROFILES / "_template.json").read_text(encoding="utf-8"))
tnodes = check_profile(template, "template")
expect(not (set(tnodes) & set(all_nodes())), "template nodes collide with existing node names")
expect(tnodes["AB_Completed3"].get("max_hit") == 1 and "all_of" not in tnodes["AB_Completed3"], "template: untitled counter")
interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))
names = [t["name"] for t in interface["task"]]
expect(len(names) == len(set(names)), "duplicate task names")
print(f"{checks} checks, {len(failures)} failures")
for f in failures:
    print("FAIL", f)
sys.exit(1 if failures else 0)
