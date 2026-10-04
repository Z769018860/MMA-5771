"""Generate the 记忆回廊（列车，星辰篇）pipeline and its task in interface.json.

    python tools/build_train_pipeline.py [--check]

Entry page (启程) -> difficulty page (option 记忆回廊难度, then 挑战) -> formation page (调查, existing StoryFormation) ->
"调查开始" -> events / shops / battles with the story_demo nodes (same handling as the main story) -> result -> back
on the entry page = finished. Stop notices (boss timeout, defeat, unknown page) are the mainline's MA_*Notice nodes.

Spec: resource/navigation/train_ui.json. Output: resource/pipeline/train.json, resource/image/train_*.png.
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

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "train.json"
INTERFACE = ROOT / "interface.json"
TASK = "记忆回廊列车"
GOLD = {"method": 4, "lower": [225, 215, 100], "upper": [255, 255, 255]}   # RGB of the selected-difficulty glow
DIFFICULTIES = (("normal", "普通"), ("hard", "困难"), ("crazy", "癫狂"))


def build():
    ui = json.loads((NAV / "train_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"train_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, grow=16):
        return {"recognition": "TemplateMatch", "template": f"train_{tid}.png", "roi": B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def region(name):
        r = ui["regions"][name]
        x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])
        return [x0, y0, x1 - x0, y1 - y0]

    def inner(name, m=10):
        x, y, w, h = region(name)
        return [x + m, y + m // 2, max(4, w - 2 * m), max(4, h - m)]

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    nodes["TR_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["TR_Diff", "TR_Entry", "TR_Resume"], "on_error": ["MA_StuckNotice"],
                         "focus": focus("记忆回廊：从入口页、难度页或调查中的任意页面开始。")}
    nodes["TR_Resume"] = {"recognition": "DirectHit", "action": "DoNothing",
                          "next": ["StoryFormation", "StoryFirstFormation", "StoryCutscene", "StoryEventPage", "StoryChoicePage",
                                   "StoryShop", "StoryArtifactSelect", "StoryFinishInvestigation", "AA_PaidRevive", "StoryReviveDecision"]}
    # ---- entry page -> difficulty page
    nodes["TR_Entry"] = {**match("entry_title"), "timeout": 20000, "rate_limit": 700, "action": "Click",
                         "target": inner("go_button"), "post_delay": 2000, "next": ["TR_Diff", "TR_EntryRetry"],
                         "focus": {"Node.Action.Succeeded": "已点击入口页右下角的启程按钮。"}}
    nodes["TR_EntryRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("go_button"), "post_delay": 2000,
                              "timeout": 15000, "next": ["TR_Diff"], "on_error": ["MA_StuckNotice"]}
    # ---- difficulty page: select (option decides which card), verify the gold glow, then 挑战
    nodes["TR_Diff"] = {**match("diff_title"), "timeout": 30000, "rate_limit": 700, "action": "DoNothing",
                        "next": ["TR_Selected", "TR_Select"], "on_error": ["MA_StuckNotice"],
                        "focus": focus("已进入【选择难度】页。")}
    nodes["TR_Selected"] = {"recognition": "ColorMatch", "roi": region("edge_normal"), **GOLD, "count": 400, "connected": False,
                            "action": "Click", "target": inner("challenge_button"), "post_delay": 2500,
                            "next": ["StoryFormation", "TR_ChallengeRetry"],
                            "focus": {"Node.Action.Succeeded": "目标难度已选中（金边），点击【挑战】。"}}
    nodes["TR_ChallengeRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("challenge_button"),
                                  "post_delay": 2500, "timeout": 20000, "next": ["StoryFormation"],
                                  "on_error": ["MA_StuckNotice"]}
    nodes["TR_Select"] = {"recognition": "DirectHit", "action": "Click", "target": inner("card_normal"), "post_delay": 700,
                          "next": ["TR_Selected", "TR_SelectRetry"],
                          "focus": {"Node.Action.Succeeded": "已点击目标难度卡片。"}}
    nodes["TR_SelectRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("card_normal"), "post_delay": 900,
                               "next": ["TR_Selected", "TR_Locked"]}
    args, _ = M.msgbox_args("记忆回廊：选择的难度没有选中（可能尚未解锁）。请手动选择一个可用难度，或在任务选项里改成较低难度。")
    nodes["TR_Locked"] = {"recognition": "DirectHit", "action": "Command", "exec": "powershell.exe", "args": args,
                          "timeout": 30000, "next": [], "on_error": [],
                          "focus": {"Node.Action.Starting": "难度未能选中：已弹出提示并停止。"}}
    # ---- investigation running
    nodes["TR_Started"] = {**match("hud_icon", 24), "timeout": 60000, "rate_limit": 700, "action": "DoNothing",
                           "next": ["StoryAfterRoute"], "on_error": ["MA_StuckNotice"],
                           "focus": focus("已进入调查（右上角出现层数 1-1/6 这类标识）：交给事件/商店/战斗节点。")}
    nodes["TR_Finished"] = {**match("entry_title"), "action": "DoNothing", "next": [],
                            "focus": focus("调查已结束并回到入口页：记忆回廊任务完成。")}
    return images, nodes, ui


def option_overrides(nodes, ui):
    out = {}
    for key, _ in DIFFICULTIES:
        x, y, w, h = [ui_region(ui, f"card_{key}")][0]
        ex = ui_region(ui, f"edge_{key}")
        out[key] = {"TR_Select": {"target": [x + 10, y + 5, max(4, w - 20), max(4, h - 10)]},
                    "TR_SelectRetry": {"target": [x + 10, y + 5, max(4, w - 20), max(4, h - 10)]},
                    "TR_Selected": {"roi": ex}}
    return out


def ui_region(ui, name):
    r = ui["regions"][name]
    x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def update_interface(orig, ui, nodes):
    d = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    ov = option_overrides(nodes, ui)
    d["option"]["记忆回廊难度"] = {
        "type": "select", "label": "记忆回廊（列车）：挑战难度",
        "description": "进入【选择难度】页后点选的难度。未解锁的难度选不中时会弹出提示并停止。",
        "default_case": "normal",
        "cases": [{"name": k, "label": label + ("（默认）" if k == "normal" else ""), "pipeline_override": ov[k]}
                  for k, label in DIFFICULTIES]}
    override = M.task_definition(orig, extra=("TR_Finished",), done_next=())
    override["StoryFormation"] = {"next": ["StoryFormation", "TR_Started", "StoryBattleMonitor"]}
    entry = {"name": TASK, "label": "记忆回廊：疾驰的欢愉专列（星辰篇）", "entry": "TR_Start",
             "option": ["记忆回廊难度", "主线灵知", "主线战斗超时", "剧情购买策略", "剧情造物位置"],
             "default_check": False, "repeatable": False, "pipeline_override": override,
             "description": "入口页点启程 → 选难度 → 挑战 → 编队页点调查 → 事件/商店/战斗按主线逻辑自动处理，直到调查结束回到入口页。Boss 超时、战败且灵知用完、或画面无法识别时弹窗提示并停止。"}
    tasks = [t for t in d["task"] if t["name"] != TASK]
    at = next((i for i, t in enumerate(tasks) if t["name"] == M.TASK), len(tasks))
    tasks.insert(at, entry)
    d["task"] = tasks
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes, ui = build()
    orig = {k: v for k, v in M.load_pipelines().items() if not k.startswith("TR_")}
    d = update_interface(orig, ui, nodes)
    text, itext = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [] if INTERFACE.read_bytes() == itext.encode("utf-8") else [str(INTERFACE)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("train pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_bytes(text.encode("utf-8"))
    INTERFACE.write_bytes(itext.encode("utf-8"))
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}; interface.json updated")


if __name__ == "__main__":
    main()
