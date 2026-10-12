"""Generic team switching for every task that passes a formation page.

    python tools/build_team_pipeline.py [--check]

The formation page has a column of team tabs (roman numerals) on the left. The CURRENT team is always the tab in the
middle; the column shows three teams above and three below it (current VI: III–IX, current XI: VIII–XIV, from the
dive live run). Two options exist on every task that passes a formation page: `默认编队` (the default team) and
`本任务编队` (follow the default / keep current / a team just for this task). If neither is set nothing changes.

How it works without touching the existing flows: the nodes TeamA_Fix* (sync-rate / assist chain flows) and TeamB_Fix*
(story / map flows) sit at the head of every `next` list that can see a formation page but are `enabled: false`. A team
option enables them and points them at the target numeral: Fix = formation page present AND the numeral glyph of the
target team is visible in the column -> click it (the clicked tab becomes the current one) -> Resume, which continues
with the handlers the flow had before. FixLo / FixHi cover VI and XI, whose unselected glyph we have no sample of: they
click one slot below the visible V / above the visible VII (resp. X / XII). The selected tab is drawn differently, so
a target that is already the current team is simply not found and nothing is clicked; a target more than three teams
away is not visible either and is left alone (switch once by hand). Never clicks anything outside the tab column.

This script also (idempotently) puts the Fix nodes at the head of those lists in sync_rate.json / story_demo.json
and in the 同调率助战 option of interface.json.

Spec: resource/navigation/team_ui.json. Output: resource/pipeline/team.json, resource/image/team_*.png.
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
ROMAN = {3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII", 9: "IX", 10: "X", 11: "XI", 12: "XII", 13: "XIII", 14: "XIV"}
GLYPHS = (3, 4, 5, 7, 8, 9, 10, 12, 13, 14)          # unselected numerals we have a sample of
VIA = {6: (5, 7), 11: (10, 12)}                      # target without a glyph: its lower / higher neighbour
TEAMS = ROMAN
FIXES = ("Fix", "FixLo", "FixHi")
FAMILIES = {"A": ["OpenAssistPurple", "OpenAssistRed", "OpenAssist"], "B": ["StoryFirstFormation", "StoryFormation"]}
# the tab column in 1280x720 pixels: x range and the vertical extent of the 7 slots (80 px apart)
COLUMN = [8, 70, 80, 540]
SLOT = 80
# (generated files carry their own Fix entries: sweep.json CLEAR_ROUTER, dive.json DD_AfterTeam, train_nodes.json TR_FormationRouter)
# (file, node) -> the formation handler the Fix nodes are put in front of; "" = head of the list
LIST_PATCHES = {
    "A": [("sync_rate.json", "CycleStart", ""), ("sync_rate.json", "EntryRouter", "OpenAssistPurple")],
    "B": [("story_demo.json", "StoryInsideRouter", "StoryFirstFormation"), ("story_demo.json", "StoryAfterRoute", "StoryFormation"),
          ("story_demo.json", "StoryBattleStage", "StoryFormation")],
}


def build():
    ui = json.loads((NAV / "team_ui.json").read_text(encoding="utf-8"))
    images = {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
        images[f"team_{t['id']}.png"] = img[y0:y1, x0:x1]
    header = {"recognition": "TemplateMatch", "template": "team_header.png", "roi": [250, 15, 360, 70],        # the button moves right with the length of the stage title
              "threshold": next(t for t in ui["templates"] if t["id"] == "header").get("threshold", 0.8), "method": 10001}
    th = {t["id"]: t.get("threshold", 0.85) for t in ui["templates"]}

    def glyph(n, roi):
        return {"recognition": "TemplateMatch", "template": f"team_glyph_{n}.png", "roi": roi, "threshold": th[f"glyph_{n}"], "method": 10001}

    # roi for the slots that still have a slot below / above them inside the column
    full = COLUMN
    lo_roi = [COLUMN[0], COLUMN[1], COLUMN[2], COLUMN[3] - COLUMN[1] - SLOT]          # not the bottom slot
    hi_roi = [COLUMN[0], COLUMN[1] + SLOT, COLUMN[2], COLUMN[3] - COLUMN[1] - SLOT]    # not the top slot
    nodes = {}
    for fam, resume in FAMILIES.items():
        p = f"Team{fam}_"
        base = {"recognition": "And", "box_index": 1, "action": "Click", "post_delay": 900}
        nodes[p + "Fix"] = {**base, "all_of": [header, glyph(4, full)], "enabled": False, "next": [p + "Resume"],
                            "focus": {"Node.Action.Succeeded": "已点击目标队伍标签（它变成当前队伍，列表重新居中）。"}}
        nodes[p + "FixLo"] = {**base, "all_of": [header, glyph(5, lo_roi)], "target_offset": [0, SLOT, 0, 0], "enabled": False,
                              "next": [p + "Resume"]}
        nodes[p + "FixHi"] = {**base, "all_of": [header, glyph(7, hi_roi)], "target_offset": [0, -SLOT, 0, 0], "enabled": False,
                              "next": [p + "Resume"]}
        nodes[p + "Resume"] = {"recognition": "DirectHit", "action": "DoNothing", "next": resume}
    return images, nodes, ui, header, glyph, full, lo_roi, hi_roi


def team_case_overrides(header, glyph, full, lo_roi, hi_roi):
    off = {f"Team{f}_{x}": {"enabled": False} for f in FAMILIES for x in FIXES}
    out = {"keep": off, "follow": {}}
    for n in ROMAN:
        ov = {}
        for fam in FAMILIES:
            p = f"Team{fam}_"
            if n in GLYPHS:
                ov[p + "Fix"] = {"enabled": True, "all_of": [header, glyph(n, full)]}
                ov[p + "FixLo"] = {"enabled": False}
                ov[p + "FixHi"] = {"enabled": False}
            else:                                           # VI / XI: click next to the visible neighbour
                lower, higher = VIA[n]
                ov[p + "Fix"] = {"enabled": False}
                ov[p + "FixLo"] = {"enabled": True, "all_of": [header, glyph(lower, lo_roi)]}
                ov[p + "FixHi"] = {"enabled": True, "all_of": [header, glyph(higher, hi_roi)]}
        out[f"t{n}"] = ov
    return out


def patch_lists():
    """Put the Fix nodes in front of the formation handlers. Returns {path: new text} for files that change."""
    changes = {}
    for fam, items in LIST_PATCHES.items():
        fixes = [f"Team{fam}_{x}" for x in FIXES]
        for fname, node, before in items:
            path = PIPE / fname
            data = json.loads(changes.get(path, path.read_text(encoding="utf-8-sig")))
            nxt = [x for x in data[node]["next"] if not x.startswith(f"Team{fam}_")]
            at = nxt.index(before) if before and before in nxt else 0
            data[node]["next"] = nxt[:at] + fixes + nxt[at:]
            changes[path] = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    return {p: t for p, t in changes.items() if json.loads(p.read_text(encoding="utf-8-sig")) != json.loads(t)}


def patch_interface(d, cases):
    names = {n: f"队伍 {r}" for n, r in ROMAN.items()}
    note = ("目标队伍的标签在左侧列表里看得到时才会点（当前队伍总在正中间，上下各显示 3 个）；已经是当前队伍则不动；"
            "相差超过 3 个的看不到，请先手动切到附近一次。队伍 I、II 还没有样本。")
    d["option"]["默认编队"] = {
        "type": "select", "label": "默认编队（所有任务共用的默认队伍）",
        "description": "编队页先切换到这个队伍再继续。每个任务各有一份这个选项，请在要用的任务里设置；任务里的「本任务编队」不改时就用它。" + note,
        "default_case": "keep", "cases": [{"name": "keep", "label": "沿用当前队伍（默认）", "pipeline_override": cases["keep"]}] + [
            {"name": f"t{n}", "label": names[n], "pipeline_override": cases[f"t{n}"]} for n in ROMAN]}
    d["option"]["本任务编队"] = {
        "type": "select", "label": "本任务编队（不选就用默认编队）",
        "description": "只给这个任务指定队伍。「跟随默认编队」= 使用「默认编队」选项的设置。" + note,
        "default_case": "follow", "cases": [{"name": "follow", "label": "跟随默认编队（默认）", "pipeline_override": {}},
                                           {"name": "keep", "label": "这个任务沿用当前队伍", "pipeline_override": cases["keep"]}] + [
            {"name": f"t{n}", "label": names[n], "pipeline_override": cases[f"t{n}"]} for n in ROMAN]}
    # no-assist (同调率助战) lists: Fix in front, and the handlers Fix resumes with
    for case in d["option"]["同调率助战"]["cases"]:
        ov = case.get("pipeline_override")
        if not ov:
            continue
        for node in ("CycleStart", "EntryRouter"):
            nxt = [x for x in ov[node]["next"] if not x.startswith("TeamA_")]
            at = nxt.index("OpenAssistPurple") if node == "EntryRouter" and "OpenAssistPurple" in nxt else (
                nxt.index("StartInvestigation") if "StartInvestigation" in nxt else 0)
            ov[node]["next"] = nxt[:at] + [f"TeamA_{x}" for x in FIXES] + nxt[at:]
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
    images, nodes, ui, header, glyph, full, lo_roi, hi_roi = build()
    cases = team_case_overrides(header, glyph, full, lo_roi, hi_roi)
    d = patch_interface(json.loads(INTERFACE.read_text(encoding="utf-8-sig")), cases)
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
    print(f"{len(nodes)} nodes, {len(images)} templates -> {OUT.relative_to(ROOT)}; patched {len(changes)} pipeline files; interface.json updated")


if __name__ == "__main__":
    main()
