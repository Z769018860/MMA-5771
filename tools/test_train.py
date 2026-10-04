"""Test the 记忆回廊（列车）pipeline on the real screenshots (MaaFramework, no game needed).

    python tools/test_train.py
"""

import json
import sys
from pathlib import Path

import cv2
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402
import build_train_pipeline as TR  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "train_ui.json").read_text(encoding="utf-8"))
IFACE = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))


def region(name):
    return TR.ui_region(UI, name)


def option(case):
    return next(c for c in IFACE["option"]["记忆回廊难度"]["cases"] if c["name"] == case)["pipeline_override"]


def task_override():
    return next(t for t in IFACE["task"] if t["name"] == TR.TASK)["pipeline_override"]


def with_glow(base, which):
    """The real difficulty page has 普通 selected; return a copy whose gold glow strip sits on card `which` (or none)."""
    img = base.copy()
    strips = {k: region(f"edge_{k}") for k, _ in TR.DIFFICULTIES}
    nx, ny, nw, nh = strips["normal"]
    glow = img[ny:ny + nh, nx:nx + nw].copy()
    hx, hy, hw, hh = strips["hard"]
    img[ny:ny + nh, nx:nx + nw] = img[hy:hy + hh, hx:hx + hw][:nh, :nw]       # an unselected strip
    if which in strips:
        tx, ty, tw, th = strips[which]
        img[ty:ty + th, tx:tx + tw] = glow[:th, :tw]
    return img


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
    images = {n: cv2.imread(str(S / f"{n}.png")) for n in ("star_entry", "star_difficulty", "star_formation", "star_start",
                                                          "home", "chapters", "main_stages", "daily", "activity_stage")}
    for n in ("star_entry", "star_difficulty", "star_formation", "star_start"):
        images[n] = cv2.resize(images[n], (1280, 720), interpolation=cv2.INTER_AREA)
    for k, _ in TR.DIFFICULTIES:
        images[f"diff_{k}"] = with_glow(images["star_difficulty"], k)
    matrix = {"TR_Entry": {"star_entry"}, "TR_Diff": {"star_difficulty", "diff_normal", "diff_hard", "diff_crazy"},
              "TR_Started": {"star_start"}, "TR_Finished": {"star_entry"}, "TR_Selected": {"star_difficulty", "diff_normal"}}
    for node, hits in matrix.items():
        for n in list(images):
            fired, _ = T.run_node(resource, images[n], node, timeout=300)
            expect(fired == (n in hits), f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    # each difficulty option verifies the glow on its own card only
    for k, _ in TR.DIFFICULTIES:
        for n in ("diff_normal", "diff_hard", "diff_crazy"):
            fired, ev = T.run_node(resource, images[n], "TR_Selected", option(k), timeout=300)
            expect(fired == (n == f"diff_{k}"), f"TR_Selected[{k}] on {n}: got {fired}")
            if fired:
                expect(T.inside(ev, region("challenge_button"), 2), f"TR_Selected[{k}] must click 挑战: {ev[:1]}")
        fired, ev = T.run_node(resource, images["diff_normal"], "TR_Select", option(k), timeout=300)
        expect(fired and T.inside(ev, region(f"card_{k}"), 2), f"TR_Select[{k}] click {ev[:1]}")
    fired, ev = T.run_node(resource, images["star_entry"], "TR_Entry", timeout=300)
    expect(fired and T.inside(ev, region("go_button"), 2), f"TR_Entry click {ev[:1]}")
    # the formation page is handled by the existing 调查 button node
    fired, ev = T.run_node(resource, images["star_formation"], "StoryFormation", timeout=300)
    expect(fired, "StoryFormation must recognise the train formation page")
    ov = task_override()
    expect(ov["StoryFormation"]["next"][1] == "TR_Started" and "TR_Finished" in ov["StoryAfterRoute"]["next"]
           and "AA_PaidRevive" in ov["StoryBattleMonitor"]["next"] and ov["StoryStopHere"]["next"] == ["MA_DefeatNotice"],
           "task override incomplete")
    # whole entry flow with 困难: entry -> diff (none selected) -> click card -> glow -> 挑战 -> formation -> 调查 -> HUD
    images["diff_none"] = with_glow(images["star_difficulty"], "none")
    tr = {"star_entry": [(region("go_button"), "diff_none")],
          "diff_none": [(region("card_hard"), "diff_hard")],
          "diff_hard": [(region("challenge_button"), "star_formation")],
          "star_formation": [([830, 630, 350, 55], "star_start")]}
    scr = Script(images, tr, "star_entry")
    quick = {k: {"timeout": 1500, "on_error": []} for k in list(ov) + [n for n in
             ("TR_Start", "TR_Entry", "TR_Diff", "TR_Selected", "TR_Select", "TR_Started", "StoryAfterRoute", "StoryInsideRouter")]}
    for k in ("MA_ManualNotice", "MA_DefeatNotice", "MA_StuckNotice", "TR_Locked"):
        quick[k] = {"action": "DoNothing"}
    merged = {}
    for src in (ov, option("hard"), quick):
        for k, v in src.items():
            merged.setdefault(k, {}).update(v)
    got = run(resource, scr, "TR_Start", merged)
    order = [t[0] for t in scr.taps]
    expect(order[:4] == ["star_entry", "diff_none", "diff_hard", "star_formation"] and scr.state == "star_start",
           f"flow: taps {scr.taps}, state {scr.state}, nodes {got}")
    expect(got.count("TR_Select") == 1 and "TR_Started" in got and "TR_Locked" not in got, f"flow nodes {got}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
