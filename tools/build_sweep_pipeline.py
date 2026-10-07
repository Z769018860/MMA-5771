"""Generate the activity sweep (重现) pipeline.

    python tools/build_sweep_pipeline.py [--check]

From the activity level list (the 巨古誓言-style list with a gold 重现 button): scroll to the bottom, select the level
directly above the last one (癫狂), tap 重现, tap the max-count arrow, tap 确定, close the reward popup.
Spec: resource/navigation/sweep_ui.json. Output: resource/pipeline/sweep.json, resource/image/sweep_*.png
The list page itself is recognised with the existing activity_oath_title.png (see build_activity_pipeline.py).
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "sweep.json"
# battle pages the sync-rate loop already handles (no assist selection: one plain clear)
CLEAR_ROUTER = ["TeamA_Fix", "StartInvestigation", "InvestigationWarningUnchecked", "InvestigationWarningChecked", "BattleWarning",
                "ReviveDecision", "FailureChoice", "FinishInvestigation", "HideCards", "AutoControlReady", "BattleMonitor", "StopHere"]
# task-level override (interface.json): after the one-off clear the sync-rate nodes must come back here, not start farming
TASK_OVERRIDE = {
    "FinishCurrentButton": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FinishAltButton": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FinishButtonClickRetry": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FailureChoice": {"next": ["StopHere"]},
    "StopHere": {"next": ["Sweep_GiveUp"]},
}
LIST_TITLE = {"recognition": "TemplateMatch", "template": "activity_oath_title.png", "roi": [0, 15, 230, 80],
              "threshold": 0.88, "method": 10001}


def build():
    ui = json.loads((NAV / "sweep_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imread(str(NAV / "samples" / sc["sample"]))
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"sweep_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, grow=16):
        return {"recognition": "TemplateMatch", "template": f"sweep_{tid}.png", "roi": B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def region(name):
        r = ui["regions"][name]
        x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])
        return [x0, y0, x1 - x0, y1 - y0]

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    nodes["Sweep_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                            "next": ["Sweep_Reward", "Sweep_Dialog", "Sweep_Page", "Sweep_FromStage"],
                            "focus": focus("活动扫荡：从关卡列表、重现窗口、奖励弹窗或活动关卡页开始。")}
    # from the activity stage page: open node N (default 1), arriving at the level list
    act = json.loads((NAV / "activity_ui.json").read_text(encoding="utf-8"))
    asc = act["screens"][act["nodes"]["screen"]]["src_size"]
    drop = {"recognition": "TemplateMatch", "template": "activity_act_drop.png", "roi": [0, 440, 1280, 160],
            "threshold": 0.8, "method": 10001}
    nodes["Sweep_FromStage"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["SweepNode1"]}
    for i, x in enumerate(act["nodes"]["x"], 1):
        cx, cy = x * 1280 / asc[0], act["nodes"]["y"] * 720 / asc[1]
        nodes[f"SweepNode{i}"] = {"recognition": "And", "all_of": [drop], "box_index": 0, "timeout": 15000,
                                  "action": "Click", "target": [int(cx) - 22, int(cy) - 22, 44, 44], "post_delay": 2200,
                                  "next": ["Sweep_Page"],
                                  "focus": {"Node.Action.Succeeded": f"已点击活动关卡节点 {i}。"}}
    # level list: scroll to the bottom, select the level above the last one (癫狂)
    nodes["Sweep_Page"] = {**LIST_TITLE, "action": "DoNothing", "timeout": 20000, "next": ["Sweep_Scroll"],
                           "focus": focus("已进入活动关卡列表。")}
    nodes["Sweep_Scroll"] = {"recognition": "DirectHit", "action": "Swipe", "begin": [185, 585, 20, 20], "end": [185, 165, 20, 20],
                             "duration": 450, "post_delay": 800, "next": ["Sweep_SelectPrev"]}
    nodes["Sweep_SelectPrev"] = {"recognition": "DirectHit", "action": "Click", "target": [185, 505, 30, 30], "post_delay": 900,
                                 "next": ["Sweep_Replay", "Sweep_Challenge"],
                                 "focus": {"Node.Action.Succeeded": "已选中列表最后一项上面的关卡（癫狂的上一个）。"}}
    nodes["Sweep_Replay"] = {"recognition": "And", "all_of": [LIST_TITLE, match("replay_btn")], "box_index": 1, "timeout": 15000,
                             "action": "Click", "target_offset": [20, 8, -40, -16], "post_delay": 1500,
                             "next": ["Sweep_Dialog", "Sweep_ReplayRetry"],
                             "focus": {"Node.Action.Succeeded": "已点击【重现】。"}}
    nodes["Sweep_ReplayRetry"] = {**nodes["Sweep_Replay"], "timeout": 10000, "next": ["Sweep_Dialog"],
                                  "focus": {"Node.Action.Succeeded": "【重现】没有打开窗口，再点一次。"}}
    # no 重现 button (level never cleared): clear it once with 挑战, then come back and look again (only once)
    nodes["Sweep_Challenge"] = {"recognition": "And", "all_of": [LIST_TITLE, match("challenge_btn")], "box_index": 1, "timeout": 15000,
                                "action": "Click", "target_offset": [20, 8, -40, -16], "post_delay": 2200,
                                "next": ["Sweep_ClearRouter"],
                                "focus": {"Node.Action.Succeeded": "该关卡没有【重现】：点击【挑战】先通关一次。"}}
    nodes["Sweep_ClearRouter"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 600000, "next": CLEAR_ROUTER}
    nodes["Sweep_Page2"] = {**LIST_TITLE, "action": "DoNothing", "timeout": 30000, "next": ["Sweep_Scroll2"],
                            "focus": focus("通关后回到关卡列表，再找一次【重现】。")}
    nodes["Sweep_Scroll2"] = {**nodes["Sweep_Scroll"], "next": ["Sweep_SelectPrev2"]}
    nodes["Sweep_SelectPrev2"] = {**nodes["Sweep_SelectPrev"], "next": ["Sweep_Replay", "Sweep_Fail"]}
    nodes["Sweep_Fail"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                           "focus": {"Node.Recognition.Succeeded": "通关一次后仍然没有【重现】按钮，停止（请检查选中的关卡）。"}}
    nodes["Sweep_GiveUp"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                             "focus": {"Node.Recognition.Succeeded": "先通关一次的挑战失败，停止。"}}
    # count dialog
    nodes["Sweep_Dialog"] = {**match("dlg_title"), "action": "DoNothing", "timeout": 15000, "next": ["Sweep_Max"],
                             "focus": focus("已打开【重现次数】窗口。")}
    nodes["Sweep_Max"] = {"recognition": "And", "all_of": [match("dlg_title"), match("dlg_max")], "box_index": 1,
                          "action": "Click", "target_offset": [6, 5, -12, -10], "post_delay": 900,
                          "next": ["Sweep_Confirm"],
                          "focus": {"Node.Action.Succeeded": "已点击最大次数按钮（↑）。"}}
    nodes["Sweep_Confirm"] = {"recognition": "And", "all_of": [match("dlg_title"), match("dlg_ok")], "box_index": 1,
                              "action": "Click", "target_offset": [20, 10, -40, -20], "post_delay": 2500,
                              "next": ["Sweep_Reward", "Sweep_ConfirmRetry"],
                              "focus": {"Node.Action.Succeeded": "已点击【确定】。"}}
    # one retry only: a window that stays open must not loop forever (确定 may be greyed out, e.g. not enough stamina)
    nodes["Sweep_ConfirmRetry"] = {**nodes["Sweep_Confirm"], "timeout": 10000, "next": ["Sweep_Reward"],
                                   "focus": {"Node.Action.Succeeded": "窗口还在，再点一次【确定】；之后仍无奖励弹窗则超时停止。"}}
    nodes["Sweep_Reward"] = {**match("reward_title"), "timeout": 20000, "action": "Click", "target": region("reward_blank"),
                             "post_delay": 1500, "next": ["Sweep_Reward", "Sweep_Done"],
                             "focus": {"Node.Action.Succeeded": "已点击空白处关闭【重现奖励】。"}}
    nodes["Sweep_Done"] = {**LIST_TITLE, "action": "DoNothing", "next": [], "timeout": 10000,
                           "focus": focus("扫荡完成，回到关卡列表。")}
    return images, nodes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes = build()
    text = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("sweep pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_bytes(text.encode("utf-8"))
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
