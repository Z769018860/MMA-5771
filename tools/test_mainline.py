"""Test the auto-push-main-story pipeline on real screenshots (MaaFramework, no game needed).

    python tools/test_mainline.py
"""

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_mainline_pipeline as M  # noqa: E402
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "mainline_ui.json").read_text(encoding="utf-8"))
IFACE = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))


def region(name):
    r = UI["regions"][name]
    x0, y0, x1, y1 = B.scale_box(r["box"], UI["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def option(name, case):
    return next(c for c in IFACE["option"][name]["cases"] if c["name"] == case).get("pipeline_override", {})


def task_override():
    return next(t for t in IFACE["task"] if t["name"] == M.TASK)["pipeline_override"]


def green_fraction(img, x, y, r=40):
    hsv = cv2.cvtColor(img[max(0, y - r):y + r, max(0, x - r):x + r], cv2.COLOR_BGR2HSV)
    return float((cv2.inRange(hsv, (40, 90, 40), (90, 255, 255)) > 0).mean())


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
    names = ["main_stages", "main_res_a", "main_res_b", "main_res_c", "main_map_a", "main_map_b", "main_map_c", "main_map_d",
             "main_map_e", "main_event", "main_lantern", "stages", "chapters", "home", "daily", "oath_list", "activity_stage"]
    images = {n: cv2.imread(str(S / f"{n}.png")) for n in names}
    # same stage list with the resonance red dot painted out
    dot = region("res_dot_roi")
    mask = np.zeros(images["main_stages"].shape[:2], np.uint8)
    mask[dot[1]:dot[1] + dot[3], dot[0]:dot[0] + dot[2]] = 255
    images["main_stages_clean"] = cv2.inpaint(images["main_stages"], mask, 7, cv2.INPAINT_TELEA)

    maps = {"main_map_a", "main_map_b", "main_map_c", "main_map_d", "main_map_e"}
    matrix = {
        "MA_StageList": {"main_stages", "main_stages_clean", "stages"},
        "MA_ResDot": {"main_stages"},
        "MA_ResPage": {"main_res_a", "main_res_b", "main_res_c"},
        "MA_ResNode": {"main_res_a", "main_res_b"},
        "MA_ResActivate": {"main_res_b"},
        "MA_Map": maps,
        "MA_Pick": maps,
    }
    for node, hits in ({} if os.environ.get('ONLY_FLOWS') else matrix).items():
        for n in list(images):
            fired, _ = T.run_node(resource, images[n], node, timeout=300)
            expect(fired == (n in hits) or (node == 'MA_ResNode' and fired and n not in hits),  # ResNode is only reachable from the resonance page
                    f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    # click positions
    fired, ev = T.run_node(resource, images["main_stages"], "MA_ResDot")
    expect(fired and T.inside(ev, region("res_icon"), 4), f"MA_ResDot click {ev[:2]}")
    for n in ("main_res_a", "main_res_b"):
        fired, ev = T.run_node(resource, images[n], "MA_ResNode")
        click = next((e for e in ev if e[0] in ("click", "tap", "down")), None)
        # the only red dot in the graph is on the 守密人通识 node, near (445, 273)
        expect(fired and click and abs(click[1] - 445) < 25 and abs(click[2] - 273) < 25, f"MA_ResNode click on {n}: {ev[:1]}")
    fired, ev = T.run_node(resource, images["main_res_b"], "MA_ResActivate")
    expect(fired and T.inside(ev, [894, 620, 316, 60], 10), f"MA_ResActivate click {ev[:1]}")
    fired, ev = T.run_node(resource, images["main_res_c"], "MA_ResExit")
    expect(fired and T.inside(ev, region("exit_x"), 2), f"MA_ResExit click {ev[:1]}")
    # map picking: every click must land on a green outlined tile; ordering options change the choice
    for n in sorted(maps) if not os.environ.get('ONLY_FLOWS') else []:
        for case in ("random", "top", "bottom", "left", "right"):
            fired, ev = T.run_node(resource, images[n], "MA_Pick", option("探索选格方式", case))
            click = next((e for e in ev if e[0] in ("click", "down")), None)
            ok = fired and click and green_fraction(images[n], click[1], click[2], 90) * 180 * 180 >= 250
            expect(ok, f"MA_Pick {case} on {n}: click {click} green={green_fraction(images[n], click[1], click[2], 90) if click else None}")
    ys = {}
    for case in ("top", "bottom"):
        _, ev = T.run_node(resource, images["main_map_a"], "MA_Pick", option("探索选格方式", case))
        ys[case] = next(e for e in ev if e[0] in ("click", "down"))[2]
    expect(ys["top"] < ys["bottom"], f"MA_Pick top/bottom ordering on main_map_a: {ys}")
    # message boxes: encoded command decodes to a MessageBox call with the intended text
    import base64
    for node in ("MA_ManualNotice", "MA_DefeatNotice", "MA_StuckNotice"):
        n = M.build()[1][node]
        script = base64.b64decode(n["args"][-1]).decode("utf-16-le")
        expect("MessageBox" in script and n["exec"] == "powershell.exe", f"{node}: bad command")
    # task-level overrides refer to real nodes and keep the story router intact
    ov = task_override()
    expect(ov["StoryStopHere"]["next"] == ["MA_DefeatNotice"] and "MA_Map" in ov["StoryAfterRoute"]["next"]
           and ov["StoryBattleMonitor"]["on_error"] == ["MA_ManualNotice"], "task override incomplete")
    # whole loop on the stage list: red dot -> resonance -> activate -> exit -> stage list (clean) -> latest stage
    star = [0, 0, 0, 0]
    tr = {"main_stages": [(region("res_icon"), "main_res_a")],
          "main_res_a": [([430, 262, 28, 28], "main_res_b")],
          "main_res_b": [([894, 620, 316, 60], "main_res_c")],
          "main_res_c": [(region("exit_x"), "main_stages_clean")],
          "main_stages_clean": [([760, 370, 120, 100], "entered")]}
    images["entered"] = images["daily"]
    scr = Script(images, tr, "main_stages")
    stop = {k: {"timeout": 1500} for k in ("StoryInsideRouter", "StoryCutscene", "StoryEventPage", "StoryFirstFormation", "StoryChoicePage",
                                          "StoryShop", "StoryArtifactSelect", "StoryFinishInvestigation", "StoryReviveDecision", "MA_Map")}
    stop["StoryInsideRouter"]["next"] = []
    for k in ("MA_ManualNotice", "MA_DefeatNotice", "MA_StuckNotice"):
        stop[k] = {"action": "DoNothing"}      # no powershell on the test host
    for k in ("StoryAfterRoute", "StoryBattleMonitor", "StoryStopHere", "MA_Start", "MA_StageList", "MA_ResPage", "MA_ResNode",
              "MA_ResActivate", "MA_ResExit", "MA_ResDot", "StorySelectLatestStage"):
        stop[k] = {"timeout": 1500, "on_error": []}
    got = run(resource, scr, "MA_Start", {**task_override(), **stop, "StoryInsideRouter": {"next": [], "timeout": 1500}})
    order = [t[0] for t in scr.taps]
    expect(order[:5] == ["main_stages", "main_res_a", "main_res_b", "main_res_c", "main_stages_clean"] and scr.state == "entered",
           f"flow resonance loop: taps {scr.taps}, state {scr.state}, nodes {got[-6:]}")
    expect("MA_ResActivate" in got and got.count("MA_ResDot") == 1, f"flow resonance nodes {got}")
    # no red dot: straight to the stage
    scr = Script(images, {"main_stages_clean": [([760, 370, 120, 100], "entered")]}, "main_stages_clean")
    got = run(resource, scr, "MA_Start", {**task_override(), **stop})
    expect("MA_ResDot" not in got and scr.state == "entered", f"flow without red dot: {got[-4:]} {scr.state}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
