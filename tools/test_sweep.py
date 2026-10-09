"""Test the activity sweep (重现) pipeline on real screenshots (MaaFramework, no game needed).

    python tools/test_sweep.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "sweep_ui.json").read_text(encoding="utf-8"))
ACT = json.loads((B.NAV / "activity_ui.json").read_text(encoding="utf-8"))


def tbox(tid):
    t = next(t for t in UI["templates"] if t["id"] == tid)
    x0, y0, x1, y1 = B.scale_box(t["box"], UI["screens"][t["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def blank():
    r = UI["regions"]["reward_blank"]
    x0, y0, x1, y1 = B.scale_box(r["box"], UI["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def main():
    resource = Resource()
    resource.post_bundle(str(B.ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    names = ["oath_list", "oath_dialog", "oath_reward", "activity_stage", "activity", "home", "daily", "interlude"]
    images = {n: cv2.imdecode(np.fromfile(B.NAV / "samples" / f"{n}.png", dtype=np.uint8), cv2.IMREAD_COLOR) for n in names}
    matrix = {"Sweep_Page": {"oath_list"}, "Sweep_Replay": {"oath_list"}, "Sweep_Dialog": {"oath_dialog"},
              "Sweep_Max": {"oath_dialog"}, "Sweep_Confirm": {"oath_dialog"}, "Sweep_Reward": {"oath_reward"},
              "Sweep_Done": {"oath_list"}, "SweepNode1": {"activity_stage"}, "SweepNode4": {"activity_stage"}}
    for node, hits in matrix.items():
        for n in names:
            fired, _ = T.run_node(resource, images[n], node)
            expect(fired == (n in hits), f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    for node, screen, target in (("Sweep_Replay", "oath_list", tbox("replay_btn")), ("Sweep_Max", "oath_dialog", tbox("dlg_max")),
                                 ("Sweep_Confirm", "oath_dialog", tbox("dlg_ok")), ("Sweep_Reward", "oath_reward", blank()),
                                 ("Sweep_SelectPrev", "oath_list", [185, 505, 30, 30])):
        fired, ev = T.run_node(resource, images[screen], node)
        expect(fired and T.inside(ev, target, 3), f"{node}: click outside target {ev[:2]}")
    # the level that gets selected must be the one directly above 癫狂: in the real page it sits at y~517 (1280x720)
    expect(500 <= 517 <= 540, "selection target no longer covers the level above 癫狂")
    # flows
    in_rect = lambda t, r: r[0] - 4 <= t[1] <= r[0] + r[2] + 4 and r[1] - 4 <= t[2] <= r[1] + r[3] + 4
    tr = {"oath_list": [(tbox("replay_btn"), "oath_dialog")], "oath_dialog": [(tbox("dlg_max"), "oath_dialog_max")],
          "oath_dialog_max": [(tbox("dlg_ok"), "oath_reward")], "oath_reward": [(blank(), "oath_list_end")],
          "oath_list_end": []}
    images["oath_dialog_max"] = images["oath_dialog"]
    images["oath_list_end"] = images["oath_list"]
    scr = Script(images, tr, "oath_list")
    got = run(resource, scr, "Sweep_Start")
    order = [t[0] for t in scr.taps]
    expect(got and got[-1] == "Sweep_Done" and scr.state == "oath_list_end", f"flow from list: {got[-4:]} state {scr.state}")
    expect([s for s in order if s != "oath_list"][:1] == ["oath_dialog"] and order.count("oath_dialog") + order.count("oath_dialog_max") >= 2,
           f"flow tap order {order}")
    expect(any(s == "oath_list" and in_rect((s, x, y), [185, 505, 30, 30]) for s, x, y in scr.taps), "flow: level above 癫狂 not selected")
    # dialog opened first (e.g. resuming) and reward popup first
    scr = Script(images, tr, "oath_dialog")
    got = run(resource, scr, "Sweep_Start")
    expect(got[-1] == "Sweep_Done" and scr.state == "oath_list_end", f"flow from dialog: {got[-3:]}")
    scr = Script(images, tr, "oath_reward")
    got = run(resource, scr, "Sweep_Start")
    expect(got[-1] == "Sweep_Done", f"flow from reward popup: {got[-3:]}")
    # from the activity stage page: node 1 then the list
    asc = ACT["screens"][ACT["nodes"]["screen"]]["src_size"]
    node1 = [ACT["nodes"]["x"][0] * 1280 / asc[0] - 22, ACT["nodes"]["y"] * 720 / asc[1] - 22, 44, 44]
    tr2 = dict(tr, activity_stage=[(node1, "oath_list")])
    scr = Script(images, tr2, "activity_stage")
    got = run(resource, scr, "Sweep_Start")
    expect(got[-1] == "Sweep_Done" and "SweepNode1" in got, f"flow from stage page: {got[-5:]}")
    # --- no 重现 button (never cleared): 挑战 first, then look again once
    iface = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))
    task = next(t for t in iface["task"] if t["name"] == "活动扫荡")
    override = task.get("pipeline_override", {})
    expect(override.get("StopHere", {}).get("next") == ["Sweep_GiveUp"] and "Sweep_Page2" in override["FinishCurrentButton"]["next"],
           "task-level override missing: finish/defeat nodes would fall back into the farming loop")
    no_replay = images["oath_list"].copy()
    x, y, w, h = tbox("replay_btn")
    mask = np.zeros(no_replay.shape[:2], np.uint8)
    mask[y - 4:y + h + 4, x - 4:x + w + 4] = 255
    images["oath_list_no_replay"] = cv2.inpaint(no_replay, mask, 9, cv2.INPAINT_TELEA)
    for node, want in (("Sweep_Replay", False), ("Sweep_Challenge", True)):
        fired, ev = T.run_node(resource, images["oath_list_no_replay"], node)
        expect(fired == want, f"{node} on a list without 重现: expected {want}, got {fired}")
    fired, ev = T.run_node(resource, images["oath_list"], "Sweep_Challenge")
    expect(fired and T.inside(ev, tbox("challenge_btn"), 3), f"Sweep_Challenge click {ev[:2]}")
    stop = {k: {"timeout": 1500} for k in ("Sweep_ClearRouter", "Sweep_Challenge", "StartInvestigation", "InvestigationWarningUnchecked", "InvestigationWarningChecked", "BattleWarning",
                                           "ReviveDecision", "FailureChoice", "FinishInvestigation", "HideCards", "AutoControlReady", "BattleMonitor", "StopHere")}
    images["formation"] = images["home"]                 # a page nothing in the clear router recognises
    tr = {"oath_list_no_replay": [(tbox("challenge_btn"), "formation")], "formation": []}
    scr = Script(images, tr, "oath_list_no_replay")
    got = run(resource, scr, "Sweep_Start", stop)
    expect(scr.state == "formation" and "Sweep_Challenge" in got and "Sweep_ClearRouter" in got and "Sweep_Replay" not in got,
           f"flow without 重现 clicks 挑战: nodes {got[-6:]} state {scr.state}")
    # after the clear the list shows 重现: normal sweep continues; if it still does not, stop with Sweep_Fail
    scr = Script(images, dict(tr, **{"oath_list": [(tbox("replay_btn"), "oath_dialog")]}), "oath_list")
    got = run(resource, scr, "Sweep_Page2")
    expect("Sweep_Replay" in got and scr.state == "oath_dialog", f"after clear, 重现 present: {got[-5:]} state {scr.state}")
    scr = Script(images, tr, "oath_list_no_replay")
    got = run(resource, scr, "Sweep_Page2", {**stop, "Sweep_Replay": {"timeout": 1500}})
    expect(got[-1] == "Sweep_Fail" and "Sweep_Challenge" not in got, f"still no 重现 after clearing: {got[-4:]}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
