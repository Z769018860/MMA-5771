"""Generic team switching for every task that passes a formation page.

    python tools/build_team_pipeline.py [--check]

The formation page has team tabs III–IX on the left (the lit one is the current team). Two options exist on every such
task: `默认编队` (the default team) and `本任务编队` (follow the default / keep current / a team just for this task).
If neither is set nothing changes (keep the current team).

How it plugs in without touching the existing flows: the nodes TeamA_Fix (sync-rate / assist chain flows) and TeamB_Fix
(story / map flows) sit at the head of every `next` list that can see a formation page but are `enabled: false`. A team
option enables them and points them at the tab: Fix = formation page present AND the target tab is dark (not lit) ->
click the tab -> Lit (tab lit) -> Resume, which continues with the handlers the flow had before. One retry, then a
message box (Team_Locked).

This script also (idempotently) puts the Fix nodes at the head of those lists in sync_rate.json / story_demo.json /
sweep.json and in the 同调率助战 option of interface.json.

Spec: resource/navigation/team_ui.json. Output: resource/pipeline/team.json, resource/image/team_header.png.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mainline_pipeline as M  # noqa: E402
import build_nav_pipeline as B  # noqa: E402
from team_options import TEAM_OPTIONS  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "team.json"
INTERFACE = ROOT / "interface.json"
PIPE = ROOT / "resource" / "pipeline"
DARK = {"method": 4, "lower": [0, 0, 0], "upper": [80, 80, 80]}               # unlit tab circle (RGB)
LIT = {"method": 4, "lower": [85, 110, 130], "upper": [255, 255, 255]}         # lit tab circle (RGB)
TEAMS = {3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX"}
FAMILIES = {"A": ["OpenAssistPurple", "OpenAssistRed", "OpenAssist"], "B": ["StoryFirstFormation", "StoryFormation"]}
# (generated files carry their own Fix entries: sweep.json CLEAR_ROUTER, dive.json DD_AfterTeam, train_nodes.json TR_FormationRouter)
# (file, node) -> the formation handler the Fix node is put in front of; "" = head of the list
LIST_PATCHES = {
    "A": [("sync_rate.json", "CycleStart", ""), ("sync_rate.json", "EntryRouter", "OpenAssistPurple")],
    "B": [("story_demo.json", "StoryInsideRouter", "StoryFirstFormation"), ("story_demo.json", "StoryAfterRoute", "StoryFormation"),
          ("story_demo.json", "StoryBattleStage", "StoryFormation")],
}


def build():
    ui = json.loads((NAV / "team_ui.json").read_text(encoding="utf-8"))
    sc = ui["screens"]["dd_formation"]
    t = ui["templates"][0]
    x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
    img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
    images = {"team_header.png": img[y0:y1, x0:x1]}
    header = {"recognition": "TemplateMatch", "template": "team_header.png", "roi": [250, 15, 360, 70],        # the button moves right with the length of the stage title
              "threshold": t.get("threshold", 0.8), "method": 10001}

    def region(name):
        r = ui["regions"][name]
        a, b, c, d = B.scale_box(r["box"], sc["src_size"])
        return [a, b, c - a, d - b]

    def inner(name, m=14):
        x, y, w, h = region(name)
        return [x + m, y + m, max(4, w - 2 * m), max(4, h - 2 * m)]

    def fix_all(tab):
        return [header, {"recognition": "ColorMatch", "roi": region(tab), **DARK, "count": 1200, "connected": False}]

    nodes = {}
    args, _ = M.msgbox_args("没能切换到设置里的队伍（目前只能切换左侧可见的队伍 III–IX）。请手动选好队伍后再启动任务，或把「编队」选项改成沿用当前队伍。")
    nodes["Team_Locked"] = {"recognition": "DirectHit", "action": "Command", "exec": "powershell.exe", "args": args,
                            "timeout": 30000, "next": [], "on_error": [],
                            "focus": {"Node.Action.Starting": "队伍没能切换：已弹出提示并停止。"}}
    for fam, resume in FAMILIES.items():
        p = f"Team{fam}_"
        fix = {"recognition": "And", "all_of": fix_all("tab_3"), "box_index": 0, "action": "Click", "target": inner("tab_3"),
               "post_delay": 900, "focus": {"Node.Action.Succeeded": "目标队伍标签没亮：已点击切换。"}}
        nodes[p + "Fix"] = {**fix, "enabled": False, "next": [p + "Lit", p + "Fix2"]}
        nodes[p + "Fix2"] = {**fix, "post_delay": 1200, "next": [p + "Lit", "Team_Locked"]}
        nodes[p + "Lit"] = {"recognition": "ColorMatch", "roi": region("tab_3"), **LIT, "count": 900, "connected": False,
                            "action": "DoNothing", "next": [p + "Resume"], "focus": {"Node.Recognition.Succeeded": "目标队伍标签已亮起。"}}
        nodes[p + "Resume"] = {"recognition": "DirectHit", "action": "DoNothing", "next": resume}
    return images, nodes, ui, region, inner, fix_all


def team_case_overrides(nodes, ui, region, inner, fix_all):
    out = {"keep": {f"Team{f}_Fix": {"enabled": False} for f in FAMILIES}, "follow": {}}
    for n in TEAMS:
        tab = f"tab_{n}"
        ov = {}
        for fam in FAMILIES:
            p = f"Team{fam}_"
            ov[p + "Fix"] = {"enabled": True, "all_of": fix_all(tab), "target": inner(tab)}
            ov[p + "Fix2"] = {"all_of": fix_all(tab), "target": inner(tab)}
            ov[p + "Lit"] = {"roi": region(tab)}
        out[f"t{n}"] = ov
    return out


def patch_lists():
    """Put Fix nodes in front of the formation handlers. Returns {path: new text} for files that change."""
    changes = {}
    for fam, items in LIST_PATCHES.items():
        fix = f"Team{fam}_Fix"
        for fname, node, before in items:
            path = PIPE / fname
            data = json.loads(changes.get(path, path.read_text(encoding="utf-8-sig")))
            nxt = data[node]["next"]
            if fix not in nxt:
                at = nxt.index(before) if before and before in nxt else 0
                data[node]["next"] = nxt[:at] + [fix] + nxt[at:]
            changes[path] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return {p: t for p, t in changes.items() if json.loads(p.read_text(encoding="utf-8-sig")) != json.loads(t)}


def patch_interface(d, nodes, ui, region, inner, fix_all):
    cases = team_case_overrides(nodes, ui, region, inner, fix_all)
    d["option"]["默认编队"] = {
        "type": "select", "label": "默认编队（所有任务共用的默认队伍）",
        "description": "编队页先切换到这个队伍再继续。每个任务各有一份这个选项，请在要用的任务里设置；任务里的「本任务编队」不改时就用它。"
                       "目前只能切换左侧可见的队伍 III–IX（I、II 在标签列表上方，还没有截图）。",
        "default_case": "keep", "cases": [{"name": "keep", "label": "沿用当前队伍（默认）", "pipeline_override": cases["keep"]}] + [
            {"name": f"t{n}", "label": f"队伍 {r}", "pipeline_override": cases[f"t{n}"]} for n, r in TEAMS.items()]}
    d["option"]["本任务编队"] = {
        "type": "select", "label": "本任务编队（不选就用默认编队）",
        "description": "只给这个任务指定队伍。「跟随默认编队」= 使用「默认编队」选项的设置。",
        "default_case": "follow", "cases": [{"name": "follow", "label": "跟随默认编队（默认）", "pipeline_override": {}},
                                           {"name": "keep", "label": "这个任务沿用当前队伍", "pipeline_override": cases["keep"]}] + [
            {"name": f"t{n}", "label": f"队伍 {r}", "pipeline_override": cases[f"t{n}"]} for n, r in TEAMS.items()]}
    # no-assist (同调率助战) lists: Fix in front, and the handlers Fix resumes with
    for case in d["option"]["同调率助战"]["cases"]:
        ov = case.get("pipeline_override")
        if not ov:
            continue
        for node in ("CycleStart", "EntryRouter"):
            nxt = ov[node]["next"]
            if "TeamA_Fix" not in nxt:
                at = nxt.index("OpenAssistPurple") if node == "EntryRouter" and "OpenAssistPurple" in nxt else (
                    nxt.index("StartInvestigation") if "StartInvestigation" in nxt else 0)
                ov[node]["next"] = nxt[:at] + ["TeamA_Fix"] + nxt[at:]
        ov["TeamA_Resume"] = {"next": ["StartInvestigation"]}
    sweep = next(t for t in d["task"] if t["name"] == "活动扫荡")           # plain clear without assist: Fix resumes at 调查
    sweep["pipeline_override"]["TeamA_Resume"] = {"next": ["StartInvestigation"]}
    for task in d["task"]:
        if task["name"] in TEAM_TASKS:
            task["option"] = [o for o in task["option"] if o not in TEAM_OPTIONS] + TEAM_OPTIONS
    return d


TEAM_TASKS = ("同步率循环", "自动推剧情Demo", "活动扫荡", "自动活动推进", "幻梦深潜", "记忆回廊列车", "自动推进主线")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes, ui, region, inner, fix_all = build()
    d = patch_interface(json.loads(INTERFACE.read_text(encoding="utf-8-sig")), nodes, ui, region, inner, fix_all)
    text, itext = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    changes = patch_lists()
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [] if INTERFACE.read_bytes() == itext.encode("utf-8") else [str(INTERFACE)]
        stale += [str(p) for p in changes]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("team pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    for path, t in changes.items():
        path.write_bytes(t.encode("utf-8"))
    OUT.write_bytes(text.encode("utf-8"))
    INTERFACE.write_bytes(itext.encode("utf-8"))
    print(f"{len(nodes)} nodes -> {OUT.relative_to(ROOT)}; patched {len(changes)} pipeline files; interface.json updated")


if __name__ == "__main__":
    main()
