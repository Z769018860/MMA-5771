"""Generate the auto-push-main-story pipeline and wire it into interface.json.

    python tools/build_mainline_pipeline.py [--check]

Loop: stage list -> (resonance red dot? open 共鸣, activate every red node, close) -> pick the latest stage ->
story/battle/event nodes already in story_demo.json, plus map walking (click a green-outlined tile) ->
back on the stage list. Stops with a Windows message box when a battle never ends (boss that cannot be
automated), when a battle is lost (no 灵知 left / roster too weak), or when nothing on screen is recognised.

Spec: resource/navigation/mainline_ui.json. Output: resource/pipeline/mainline.json, resource/image/main_*.png and the
`自动推进主线` task + options in interface.json (task-level pipeline_override extends nodes of story_demo.json).
"""

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "mainline.json"
INTERFACE = ROOT / "interface.json"
TASK = "自动推进主线"
GREEN = {"method": 40, "lower": [40, 90, 40], "upper": [90, 255, 255]}      # HSV: candidate tile outline/fill
RED = {"method": 4, "lower": [190, 0, 0], "upper": [255, 100, 115]}         # RGB: red notification dot
MSGBOX = "Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show('{text}','忘却前夜助手','OK','Warning') | Out-Null"


def msgbox_args(text):
    script = MSGBOX.format(text=text.replace("'", "''"))
    return ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
            base64.b64encode(script.encode("utf-16-le")).decode("ascii")], script


def load_pipelines():
    nodes = {}
    for f in sorted((ROOT / "resource" / "pipeline").glob("*.json")):
        if f.name != "mainline.json":
            nodes.update(json.loads(f.read_text(encoding="utf-8-sig")))
    return nodes


def build():
    ui = json.loads((NAV / "mainline_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"main_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, grow=16):
        return {"recognition": "TemplateMatch", "template": f"main_{tid}.png", "roi": B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def region(name):
        r = ui["regions"][name]
        x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])
        return [x0, y0, x1 - x0, y1 - y0]

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    # the bar's numbers (1/14, 3/30 ...) and red dots change, so only the static labels are used
    stage_bar = {"recognition": "And", "all_of": [match("stage_lbl_star", 20), match("stage_lbl_ach", 20)], "box_index": 0}
    # ------------------------------------------------------------------ entry
    nodes["MA_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["MA_Map", "MA_ResPage", "MA_StageList", "MA_Resume"],
                         "focus": focus("自动推进主线：从地图、共鸣页、关卡列表或其他页面开始。")}
    nodes["MA_Resume"] = {"recognition": "DirectHit", "action": "DoNothing",
                          "next": ["StoryFormation", "StoryFirstFormation", "StoryCutscene", "StoryEventPage", "StoryChoicePage",
                                   "StoryShop", "StoryArtifactSelect", "StoryFinishInvestigation", "StoryReviveDecision", "NavMainEntry"]}
    # ------------------------------------------------------------------ stage list + resonance
    nodes["MA_StageList"] = {**stage_bar, "timeout": 120000, "rate_limit": 700, "action": "DoNothing",
                             "next": ["MA_ResDot", "StorySelectLatestStage"], "on_error": ["MA_StuckNotice"],
                             "focus": focus("已在章节关卡列表：先检查左下角【共鸣】红点，再选最新关卡。")}
    x, y, w, h = region("res_dot_roi")
    ix, iy, iw, ih = region("res_icon")
    nodes["MA_ResDot"] = {"recognition": "ColorMatch", "roi": [x, y, w, h], **RED, "count": 60, "connected": False,
                          "max_hit": 40, "action": "Click", "target": [ix + 6, iy + 6, iw - 12, ih - 12], "post_delay": 2200,
                          "next": ["MA_ResPage"], "on_error": ["MA_StuckNotice"],
                          "focus": {"Node.Recognition.Succeeded": "【共鸣】图标有红点，进入共鸣页激活。"}}
    nodes["MA_ResPage"] = {**match("res_title"), "timeout": 20000, "rate_limit": 700, "action": "DoNothing",
                           "next": ["MA_ResActivate", "MA_ResNode", "MA_ResExit"], "on_error": ["MA_StuckNotice"],
                           "focus": focus("已进入【共鸣】页。")}
    nodes["MA_ResNode"] = {"recognition": "ColorMatch", "roi": region("res_graph"), **RED, "count": 30, "connected": True,
                           "order_by": "Vertical", "index": 0, "action": "Click", "post_delay": 1300,
                           "next": ["MA_ResActivate", "MA_ResExit"],
                           "focus": {"Node.Action.Succeeded": "已点击有红点的共鸣节点。"}}
    nodes["MA_ResActivate"] = {"recognition": "And", "all_of": [match("res_title"), match("res_activate", 30)], "box_index": 1,
                               "action": "Click", "target_offset": [20, 10, -40, -20], "post_delay": 2000,
                               "next": ["MA_ResPage"],
                               "focus": {"Node.Action.Succeeded": "已点击【激活】。"}}
    ex, ey, ew, eh = region("exit_x")
    exit_node = {"recognition": "DirectHit", "action": "Click", "target": [ex + 12, ey + 12, ew - 24, eh - 24], "post_delay": 2000}
    nodes["MA_ResExit"] = {**exit_node, "next": ["MA_StageList", "MA_ResExitRetry"],
                           "focus": {"Node.Action.Succeeded": "没有可激活的红点：点击右上角退出共鸣页。"}}
    nodes["MA_ResExitRetry"] = {**exit_node, "timeout": 15000, "next": ["MA_StageList"], "on_error": ["MA_StuckNotice"]}
    # ------------------------------------------------------------------ map walking
    mx, my, mw, mh = region("map_area")
    nodes["MA_Map"] = {**match("map_marker"), "timeout": 120000, "rate_limit": 700, "action": "DoNothing",
                       "next": ["MA_Pick"], "on_error": ["MA_StuckNotice"],
                       "focus": focus("已在探索地图页。")}
    nodes["MA_Pick"] = {"recognition": "And",
                        "all_of": [match("map_marker"),
                                   {"recognition": "ColorMatch", "roi": [mx, my, mw, mh], **GREEN, "count": 250, "connected": True,
                                    "order_by": "Random", "index": 0}],
                        "box_index": 1, "action": "Click", "post_delay": 2200, "next": ["StoryAfterRoute"],
                        "focus": {"Node.Action.Succeeded": "已点击一个绿色描边的可达格子（随机选择；走过的格子变为青色不再选）。"}}
    # ------------------------------------------------------------------ stop notices (Windows message box)
    for name, text, note in (
            ("MA_ManualNotice", "战斗长时间没有结束：这很可能是无法自动战斗的 Boss 关，请手动操作后再启动任务。", "战斗超时：可能是需要手动操作的 Boss 关，已弹出提示。"),
            ("MA_DefeatNotice", "战斗失败且没有可用的应急灵知体：练度与关卡差距太大，请重新规划配队或先沉淀练度。", "战斗失败（灵知用完或未启用）：已弹出练度警告。"),
            ("MA_StuckNotice", "自动推进主线停住了：画面上没有识别到任何已知页面，请手动处理后重新启动，并保留诊断报告。", "没有识别到已知页面：已弹出提示。")):
        args, script = msgbox_args(text)
        nodes[name] = {"recognition": "DirectHit", "action": "Command", "exec": "powershell.exe", "args": args,
                       "timeout": 30000, "next": [], "on_error": [],
                       "focus": {"Node.Action.Starting": note, "Node.Action.Failed": note + "（消息框弹出失败，请看本日志）"}}
    return images, nodes


def task_definition(orig):
    """Task-level overrides: extend the story_demo nodes so they cooperate with map walking and the stop conditions."""
    after = [x for x in orig["StoryAfterRoute"]["next"]] + [n for n in ("MA_Map", "MA_StageList") if n not in orig["StoryAfterRoute"]["next"]]
    inside = [x for x in orig["StoryInsideRouter"]["next"]] + ["MA_Map", "MA_StageList"]
    monitor = [x for x in orig["StoryBattleMonitor"]["next"]] + ["MA_Map", "MA_StageList"]
    out = {
        "StoryAfterRoute": {"next": after, "on_error": ["MA_StuckNotice"]},
        "StoryInsideRouter": {"next": inside, "on_error": ["MA_StuckNotice"]},
        "StoryBattleMonitor": {"next": monitor, "timeout": 240000, "on_error": ["MA_ManualNotice"]},
        "StoryStopHere": {"next": ["MA_DefeatNotice"]},
        "NavStageDone": {"next": ["MA_StageList"]},
    }
    # Live finding (activity advance): once emergency 灵知 runs out the revive dialog offers a material exchange.
    # AA_PaidRevive (activity_advance.json) warns and stops without clicking; try it before StoryReviveDecision everywhere.
    for name, node in orig.items():
        nxt = out.get(name, {}).get("next", node.get("next", []))
        if "StoryReviveDecision" in nxt:
            out.setdefault(name, {})["next"] = [x for y in nxt for x in (["AA_PaidRevive", y] if y == "StoryReviveDecision" else [y])]
    return out


def update_interface(orig):
    d = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    revive = next(c for c in d["option"]["剧情灵知"]["cases"] if c["name"] == "剧情使用灵知")["pipeline_override"]
    d["option"]["主线灵知"] = {"type": "select", "label": "主线：战斗失败时使用应急灵知体",
                             "description": "使用：失败时确认复活继续；灵知用完或不使用时，失败后弹出练度差距警告并停止。",
                             "default_case": "use", "cases": [
                                 {"name": "use", "label": "使用灵知（默认）", "pipeline_override": revive},
                                 {"name": "skip", "label": "不使用灵知，失败即警告停止"}]}
    d["option"]["主线战斗超时"] = {"type": "select", "label": "主线：战斗超过多久判定为需要手动",
                               "description": "战斗一直不结束（例如无法自动的 Boss 关）时弹出提示并停止。普通战斗很慢时请调大。",
                               "default_case": "4min", "cases": [
                                   {"name": "2min", "label": "2 分钟", "pipeline_override": {"StoryBattleMonitor": {"timeout": 120000}}},
                                   {"name": "4min", "label": "4 分钟（默认）"},
                                   {"name": "8min", "label": "8 分钟", "pipeline_override": {"StoryBattleMonitor": {"timeout": 480000}}}]}
    d["option"]["探索选格方式"] = {"type": "select", "label": "主线：地图上选哪个绿色格子",
                               "description": "所有绿色描边（可达且没走过）的格子里按此选一个点击。随机最稳妥：走过的格子会变青色，不会重复。",
                               "default_case": "random", "cases": [
                                   {"name": "random", "label": "随机（默认）"},
                                   {"name": "top", "label": "最靠上", "pipeline_override": {"MA_Pick": {"all_of": None}}},
                                   {"name": "bottom", "label": "最靠下"},
                                   {"name": "left", "label": "最靠左"},
                                   {"name": "right", "label": "最靠右"}]}
    return d


def pick_overrides(nodes):
    base = nodes["MA_Pick"]["all_of"]

    def make(order, index):
        return {"MA_Pick": {"all_of": [base[0], {**base[1], "order_by": order, "index": index}]}}
    return {"top": make("Vertical", 0), "bottom": make("Vertical", -1), "left": make("Horizontal", 0), "right": make("Horizontal", -1)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes = build()
    orig = load_pipelines()
    d = update_interface(orig)
    picks = pick_overrides(nodes)
    for c in d["option"]["探索选格方式"]["cases"]:
        if c["name"] in picks:
            c["pipeline_override"] = picks[c["name"]]
    entry = {"name": TASK, "label": "自动推进主线（实验）", "entry": "MA_Start",
             "option": ["主线灵知", "主线战斗超时", "探索选格方式", "目标章节", "剧情购买策略", "剧情造物位置"],
             "default_check": False, "repeatable": False, "pipeline_override": task_definition(orig),
             "description": "反复：选最新关卡 → 走格子/事件/商店/战斗/跳过剧情 → 回到关卡列表时检查左下角共鸣红点并全部激活 → 继续下一关。遇到无法自动的 Boss 关（战斗超时）、战斗失败且灵知用完、或画面无法识别时弹出提示并停止。"}
    d["task"] = [t for t in d["task"] if t["name"] != TASK] + [entry]
    text = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
    itext = json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [] if INTERFACE.read_bytes() == itext.encode("utf-8") else [str(INTERFACE)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("mainline pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_bytes(text.encode("utf-8"))
    INTERFACE.write_bytes(itext.encode("utf-8"))
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}; interface.json updated")


if __name__ == "__main__":
    main()
