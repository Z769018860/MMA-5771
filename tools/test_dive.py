"""Test the 幻梦深潜 pipeline on the real screenshots (MaaFramework, no game needed).

    python tools/test_dive.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_dive_pipeline as D  # noqa: E402
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "dive_ui.json").read_text(encoding="utf-8"))
TEAM_UI = json.loads((B.NAV / "team_ui.json").read_text(encoding="utf-8"))
IFACE = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))


def region(name):
    return D.region_of(TEAM_UI if name.startswith("tab_") else UI, name)


def option(name, case):
    return next(c for c in IFACE["option"][name]["cases"] if c["name"] == case).get("pipeline_override", {})


def move_patch(img, src_region, dst_region, fill_region):
    """Copy the lit strip/ring from src to dst and fill the old place with an unlit look-alike strip."""
    out = img.copy()
    (sx, sy, sw, sh), (dx, dy, dw, dh), (fx, fy, fw, fh) = region(src_region), region(dst_region), region(fill_region)
    w, h = min(sw, dw, fw), min(sh, dh, fh)
    lit = img[sy:sy + h, sx:sx + w].copy()
    out[sy:sy + h, sx:sx + w] = img[fy:fy + h, fx:fx + w]
    out[dy:dy + h, dx:dx + w] = lit
    return out


def main():
    resource = Resource()
    resource.post_bundle(str(B.ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    S = B.NAV / "samples"
    names = ("dd_entry", "dd_list_top", "dd_list_bottom", "dd_formation", "star_entry", "star_difficulty", "home", "chapters",
             "main_stages", "activity_stage")
    images = {n: cv2.imdecode(np.fromfile(S / f"{n}.png", dtype=np.uint8), cv2.IMREAD_COLOR) for n in names}
    matrix = {"DD_Entry": {"dd_entry"}, "DD_FinishedEntry": {"dd_entry"},
              "DD_List": {"dd_list_top", "dd_list_bottom"}, "DD_FinishedList": {"dd_list_top", "dd_list_bottom"},
              "DD_FormationReady": {"dd_formation"}}
    for node, hits in matrix.items():
        for n in images:
            fired, _ = T.run_node(resource, images[n], node, timeout=300)
            expect(fired == (n in hits), f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    # the sync-rate 调查 button template also matches other blue bottom-right buttons (挑战); it only has to hit here
    fired, ev = T.run_node(resource, images["dd_formation"], "StartInvestigation", timeout=300)
    expect(fired and T.inside(ev, [830, 625, 360, 60], 2), f"StartInvestigation on the dive formation page: {ev[:1]}")
    # real glow positions: list top state card I, list bottom state card IV
    for img_name, strip, want in (("dd_list_top", "edge_top_1", True), ("dd_list_bottom", "edge_bot_4", True),
                                  ("dd_list_top", "edge_top_2", False), ("dd_list_bottom", "edge_bot_5", False)):
        fired, _ = T.run_node(resource, images[img_name], "DD_Selected", {"DD_Selected": {"roi": region(strip)}}, timeout=300)
        expect(fired == want, f"real glow: {strip} on {img_name} expected {want}, got {fired}")
    # every difficulty option verifies the glow on its own card only (glow moved from the real selected card)
    synthetic = {}
    for pos in range(1, 6):
        synthetic[f"top_{pos}"] = move_patch(images["dd_list_top"], "edge_top_1", f"edge_top_{pos}", "edge_top_2") if pos > 1 else images["dd_list_top"]
    for pos in range(4, 9):
        synthetic[f"bot_{pos}"] = move_patch(images["dd_list_bottom"], "edge_bot_4", f"edge_bot_{pos}", "edge_bot_5") if pos > 4 else images["dd_list_bottom"]
    for key, (state, pos, label) in D.DIFFS.items():
        ov = option("幻梦深潜难度", key)
        for sname, img in synthetic.items():
            if sname.split("_")[0] != ("top" if state == "top" else "bot"):
                continue
            fired, ev = T.run_node(resource, img, "DD_Selected", ov, timeout=300)
            want = sname == f"{state}_{pos}"
            expect(fired == want, f"DD_Selected[{key}] on {sname}: expected {want}, got {fired}")
            if fired:
                expect(T.inside(ev, region("list_challenge"), 2), f"DD_Selected[{key}] must click 挑战: {ev[:1]}")
        fired, ev = T.run_node(resource, images["dd_list_top"], "DD_Select", ov, timeout=300)
        expect(fired and T.inside(ev, region(f"card_{state}_{pos}"), 2), f"DD_Select[{key}] click {ev[:1]}")
        # scroll direction: top state drags the list down, bottom state drags it up
        fired, ev = T.run_node(resource, images["dd_list_top"], "DD_Scroll", ov, timeout=300)
        moves = [e for e in ev if e[0] in ("down", "move")]
        expect(fired and moves and ((moves[-1][2] > moves[0][2]) == (state == "top")), f"DD_Scroll[{key}] direction {moves[:1]}..{moves[-1:]}")
    # whole flow: entry -> list (scroll) -> card II -> 挑战 -> formation -> switch to team IV -> (no assist) 调查
    images["list_ii"] = synthetic["top_2"]
    images["formation_iv"] = move_patch(images["dd_formation"], "tab_6", "tab_4", "tab_5")
    images["started"] = images["star_start"] = cv2.imdecode(np.fromfile(S / "star_start.png", dtype=np.uint8), cv2.IMREAD_COLOR)
    tasks = next(t for t in IFACE["task"] if t["name"] == D.TASK)
    assert tasks["entry"] == "DD_Start"
    tr = {"dd_entry": [(region("entry_challenge"), "dd_list_top")],
          "dd_list_top": [(region("card_top_2"), "list_ii")],
          "list_ii": [(region("list_challenge"), "dd_formation")],
          "dd_formation": [(region("tab_4"), "formation_iv")],
          "formation_iv": [([830, 625, 360, 60], "started")]}
    scr = Script(images, tr, "dd_entry")
    quick = {k: {"timeout": 1500, "on_error": []} for k in list(tasks["pipeline_override"]) + [
        "DD_Start", "DD_Entry", "DD_List", "DD_Select", "DD_Selected", "DD_FormationReady", "DD_AfterTeam", "TeamA_Fix", "TeamA_Fix2", "TeamA_Lit", "TeamA_Resume", "StartInvestigation", "StoryAfterRoute"]}
    for k in ("MA_ManualNotice", "MA_DefeatNotice", "MA_StuckNotice", "DD_Locked", "Team_Locked"):
        quick[k] = {"action": "DoNothing"}
    for k in ("DD_Scroll", "DD_Scroll2"):
        quick[k] = {"post_delay": 50}
    merged = {}
    for src in (tasks["pipeline_override"], option("幻梦深潜难度", "d2"), option("默认编队", "t4"), option("幻梦深潜助战", "skip"), quick):
        for k, v in src.items():
            merged.setdefault(k, {}).update(v)
    got = run(resource, scr, "DD_Start", merged)
    taps = [t[0] for t in scr.taps]
    expect(taps[:5] == ["dd_entry", "dd_list_top", "list_ii", "dd_formation", "formation_iv"] and scr.state == "started",
           f"flow: taps {scr.taps}, state {scr.state}, nodes {got}")
    expect("DD_Locked" not in got and "Team_Locked" not in got, f"flow reported a lock: {got}")
    ov = tasks["pipeline_override"]
    expect(ov["StartInvestigation"]["next"][-1] == "StoryAfterRoute" and "DD_FinishedList" in ov["StoryAfterRoute"]["next"]
           and "MA_Map" in ov["StoryAfterRoute"]["next"] and ov["StoryStopHere"]["next"] == ["MA_DefeatNotice"], "task override incomplete")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
