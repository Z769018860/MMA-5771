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
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "sweep.json"
INTERFACE = ROOT / "interface.json"
STAGES = ("破开囚笼", "昨日之梦", "传烛者", "愚者", "孤独之旅", "无尽沙", "自由与死亡")
# battle pages the sync-rate loop already handles (no assist selection: one plain clear)
CLEAR_ROUTER = ["TeamA_Fix", "TeamA_FixLo", "TeamA_FixHi", "StartInvestigation", "InvestigationWarningUnchecked", "InvestigationWarningChecked", "BattleWarning",
                "ReviveDecision", "FailureChoice", "FinishInvestigation", "HideCards", "AutoControlReady", "BattleMonitor", "StopHere"]
# task-level override (interface.json): after the one-off clear the sync-rate nodes must come back here, not start farming
TASK_OVERRIDE = {
    "FinishCurrentButton": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FinishAltButton": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FinishButtonClickRetry": {"next": ["Sweep_Page2", "FinishCurrentButton", "FinishAltButton"]},
    "FailureChoice": {"next": ["StopHere"]},
    "StopHere": {"next": ["Sweep_GiveUp"]},
}
LIST_TITLE = {"recognition": "TemplateMatch", "template": "sweep_list_marker.png", "roi": [990, 85, 165, 70],
              "threshold": 0.78, "method": 10001}


def build():
    ui = json.loads((NAV / "sweep_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"sweep_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)
    left_view = cv2.imdecode(np.fromfile(NAV / "samples" / "mirror_prisoner_stage_left.png", dtype=np.uint8), cv2.IMREAD_COLOR)
    left_view = cv2.resize(left_view, (1280, 720))
    right_view = cv2.imdecode(np.fromfile(NAV / "samples" / "mirror_prisoner_stage_right.png", dtype=np.uint8), cv2.IMREAD_COLOR)
    right_view = cv2.resize(right_view, (1280, 720))
    for i, (x0, x1) in enumerate(((95, 245), (350, 525), (635, 770), (905, 1055)), 1):
        images[f"sweep_stage{i}_title.png"] = left_view[495:535, x0:x1]
    images["sweep_stage5_title.png"] = right_view[495:535, 430:590]
    images["sweep_stage6_title.png"] = right_view[495:535, 720:835]
    images["sweep_stage7_title.png"] = right_view[495:535, 960:1140]

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
                            "next": ["Sweep_Reward", "Sweep_Dialog", "Sweep_Page", "Sweep_StagePage", "Sweep_FromActivity", "Sweep_FromHome"],
                            "focus": focus("镜像囚徒·复刻扫荡：从主界面、活动页、横排关卡页或难度列表开始。")}
    # from the activity stage page: open node N (default 1), arriving at the level list
    act = json.loads((NAV / "activity_ui.json").read_text(encoding="utf-8"))
    asc = act["screens"][act["nodes"]["screen"]]["src_size"]
    drop = {"recognition": "TemplateMatch", "template": "activity_act_drop.png", "roi": [0, 440, 1280, 160],
            "threshold": 0.8, "method": 10001}
    nodes["Sweep_StagePage"] = {**drop, "action": "DoNothing", "next": ["Sweep_FromStage"]}
    nodes["Sweep_FromStage"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["SweepNode1"]}
    nodes["Sweep_FromActivity"] = {
        "recognition": "TemplateMatch", "template": "sweep_mirror_prisoner_banner.png",
        "roi": [0, 65, 270, 110], "threshold": 0.78, "method": 10001,
        "action": "Click", "target_offset": [20, 12, -40, -24], "post_delay": 800,
        "next": ["Sweep_ActivityEntry"],
        "focus": {"Node.Action.Succeeded": "已识别并选择【镜像囚徒·复刻】活动。"},
    }
    nodes["Sweep_ActivityEntry"] = {
        "recognition": "DirectHit", "action": "Click", "target": [1070, 625, 50, 48],
        "post_delay": 2200, "next": ["Sweep_StagePage"],
        "focus": {"Node.Action.Succeeded": "已点击【飞跃青空】进入该活动横排关卡页。"},
    }
    home = json.loads((ROOT / "resource" / "pipeline" / "navigation.json").read_text(encoding="utf-8"))
    nodes["Sweep_FromHome"] = {**home["NavHome_banner_event"], "next": ["Sweep_FromActivity"]}
    # First normalize the carousel to its left/right end; then verify the
    # chapter title. A failed swipe must not result in tapping another chapter.
    title_boxes = ((75, 245), (330, 525), (615, 780), (885, 1070),
                   (410, 610), (700, 855), (940, 1160))
    for i, cx in enumerate((168, 436, 704, 972, 508, 781, 1059), 1):
        right_end = i >= 5
        start_x, end_x = (1080, 280) if right_end else (280, 1080)
        nodes[f"SweepNode{i}"] = {"recognition": "DirectHit", "action": "Swipe",
                                  "begin": [start_x, 520, 20, 20], "end": [end_x, 520, 20, 20],
                                  "duration": 550, "post_delay": 850,
                                  "next": [f"SweepNode{i}Scroll2"],
                                  "focus": {"Node.Action.Succeeded": f"滑动到镜像囚徒·复刻关卡 {i} 所在一端。"}}
        nodes[f"SweepNode{i}Scroll2"] = {**nodes[f"SweepNode{i}"],
                                         "next": [f"SweepNode{i}Click"]}
        x0, x1 = title_boxes[i-1]
        title = {"recognition": "TemplateMatch", "template": f"sweep_stage{i}_title.png",
                 "roi": [x0, 475, x1-x0, 75], "threshold": 0.85, "method": 10001}
        nodes[f"SweepNode{i}Click"] = {"recognition": "And", "all_of": [drop, title],
                                      "box_index": 1, "action": "Click",
                                      "target": [cx - 25, 505, 50, 50],
                                      "post_delay": 2200, "next": ["Sweep_Page"],
                                      "focus": {"Node.Action.Succeeded": f"已点击活动关卡节点 {i}：{STAGES[i-1]}。"}}
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


def update_interface(data):
    """Expose all seven current event chapters and their replayable difficulties."""
    options = data["option"]
    options["扫荡节点"] = {
        "type": "select", "label": "镜像囚徒·复刻：关卡",
        "description": "从飞跃青空横排关卡页进入时选择；已进入某关的难度列表时，此项不再切换关卡。",
        "default_case": "node1",
        "cases": [
            {"name": f"node{i}", "label": f"{i}. {name}" + ("（默认）" if i == 1 else ""),
             "pipeline_override": {"Sweep_FromStage": {"next": [f"SweepNode{i}"]}}}
            for i, name in enumerate(STAGES, 1)
        ],
    }
    options["扫荡难度"] = {
        "type": "select", "label": "镜像囚徒·复刻：扫荡难度",
        "description": "每关可选之一至之六；癫狂页只有挑战，无法重现。未通关的所选难度会先挑战一次。",
        "default_case": "level6", "cases": [],
    }
    labels = ("之一（20级）", "之二（30级）", "之三（40级）", "之四（50级）", "之五（60级）", "之六（65级）")
    for level, label in enumerate(labels, 1):
        # Top of the seven-row list shows levels 1–6; the bottom shows 2–6 and 癫狂.
        # Level 6 is selected from the bottom to preserve the verified default path.
        to_bottom = level == 6
        swipe = {"begin": [185, 585 if to_bottom else 165, 20, 20],
                 "end": [185, 165 if to_bottom else 585, 20, 20]}
        y = 505 if to_bottom else 145 + (level - 1) * 100
        override = {"Sweep_Scroll": swipe, "Sweep_Scroll2": swipe,
                    "Sweep_SelectPrev": {"target": [185, y, 30, 30]},
                    "Sweep_SelectPrev2": {"target": [185, y, 30, 30]}}
        options["扫荡难度"]["cases"].append({
            "name": f"level{level}", "label": label + ("（默认）" if level == 6 else ""),
            "pipeline_override": override,
        })
    task = next(task for task in data["task"] if task["name"] == "活动扫荡")
    task["option"] = ["扫荡节点", "扫荡难度", *[x for x in task["option"] if x not in ("扫荡节点", "扫荡难度")]]
    task["description"] = "镜像囚徒·复刻：可从飞跃青空选择七个关卡之一，并选择之一至之六扫荡；已有重现则直接扫荡，否则先挑战解锁。癫狂不提供重现。"
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes = build()
    text = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
    interface = update_interface(json.loads(INTERFACE.read_text(encoding="utf-8-sig")))
    itext = json.dumps(interface, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [] if INTERFACE.read_bytes() == itext.encode("utf-8") else [str(INTERFACE)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("sweep pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imencode(".png", img)[1].tofile(str(IMAGE / name))
    OUT.write_bytes(text.encode("utf-8"))
    INTERFACE.write_bytes(itext.encode("utf-8"))
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
