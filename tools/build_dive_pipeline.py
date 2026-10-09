"""Generate the 幻梦深潜 (dream dive) pipeline and its task in interface.json.

    python tools/build_dive_pipeline.py [--check]

Entry page (挑战) -> difficulty list (option 幻梦深潜难度: I–VII / 癫狂; the list is scrolled to its top or bottom first so
card positions are fixed, then the card is clicked and the gold glow verified) -> 挑战 -> formation page (通用队伍选项 picks the team (build_team_pipeline.py), option 幻梦深潜助战 uses the assist chain of the sync-rate loop or goes straight to 调查) ->
map / events / shops / battles with the main-story nodes (MA_Map picks green tiles, Story* handle everything else) ->
result -> back on the list/entry page = finished. Stop notices are the mainline's MA_*Notice nodes.

Spec: resource/navigation/dive_ui.json. Output: resource/pipeline/dive.json, resource/image/dive_*.png.
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
OUT = ROOT / "resource" / "pipeline" / "dive.json"
INTERFACE = ROOT / "interface.json"
TASK = "幻梦深潜"
GOLD = {"method": 4, "lower": [225, 215, 100], "upper": [255, 255, 255]}      # selected-card glow (RGB)
CYAN = {"method": 40, "lower": [75, 80, 120], "upper": [105, 255, 255]}  # reachable hex outline (HSV)
# difficulty key -> (list state, position in that state, label)
DIFFS = {"d1": ("top", 1, "幻梦深潜 I"), "d2": ("top", 2, "II"), "d3": ("top", 3, "III"), "d4": ("top", 4, "IV"),
         "d5": ("top", 5, "V"), "d6": ("bot", 6, "VI"), "d7": ("bot", 7, "VII"), "d8": ("bot", 8, "癫狂")}


def build():
    ui = json.loads((NAV / "dive_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        img = cv2.imdecode(np.fromfile(NAV / "samples" / sc["sample"], dtype=np.uint8), cv2.IMREAD_COLOR)
        if t["id"] in ("item_title", "ability_title", "locked_door_title", "illusion_title", "artifact_title", "secret_title"):
            # The live ADB screenshot is 1600x900; recognition uses 1280x720.
            img = cv2.resize(img, (1280, 720))
        images[f"dive_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, grow=16):
        return {"recognition": "TemplateMatch", "template": f"dive_{tid}.png", "roi": B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def region(name):
        return region_of(ui, name)

    def inner(name, m=10):
        x, y, w, h = region(name)
        return [x + m, y + m // 2, max(4, w - 2 * m), max(4, h - m)]

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    nodes["DD_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["DD_Entry", "DD_List", "DD_FormationReady", "DD_Map", "DD_FromHome"], "on_error": ["MA_StuckNotice"],
                         "focus": focus("幻梦深潜：从入口页、难度列表或编队页开始。调查中续跑请指定 DD_Resume。")}
    home = json.loads((ROOT / "resource" / "pipeline" / "navigation.json").read_text(encoding="utf-8"))
    nodes["DD_FromHome"] = {**home["NavHome_dream_dive"], "next": ["DD_Entry"], "timeout": 20000}
    nodes["DD_Resume"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["DD_EnterSecret", "DD_ArtifactPick", "DD_UseRustKey", "DD_DispelIllusion", "DD_AbilityPick", "DD_ItemDismiss", "DD_RewardDismiss", "DD_SealCardPick", "DD_ShopExit", "DD_Map", "StoryAfterRoute"]}
    nodes["DD_Entry"] = {**match("entry_title"), "timeout": 20000, "rate_limit": 700, "action": "Click",
                         "target": inner("entry_challenge"), "post_delay": 2000, "next": ["DD_List", "DD_EntryRetry"],
                         "focus": {"Node.Action.Succeeded": "已点击入口页的【挑战】。"}}
    nodes["DD_EntryRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("entry_challenge"),
                              "post_delay": 2000, "timeout": 15000, "next": ["DD_List"], "on_error": ["MA_StuckNotice"]}
    # ---- difficulty list: scroll to a fixed state, click the card, verify the glow, 挑战
    nodes["DD_List"] = {**match("list_marker"), "timeout": 30000, "rate_limit": 700, "action": "DoNothing",
                        "next": ["DD_Scroll"], "on_error": ["MA_StuckNotice"], "focus": focus("已进入幻梦深潜难度列表。")}
    x, y, w, h = region("list_area")
    cx, top, bot = x + w // 2, y + int(h * 0.12), y + int(h * 0.88)
    swipe = {"recognition": "DirectHit", "action": "Swipe", "duration": 500, "post_delay": 700}
    nodes["DD_Scroll"] = {**swipe, "begin": [cx, top, 10, 10], "end": [cx, bot, 10, 10], "next": ["DD_Scroll2"],
                          "focus": {"Node.Action.Succeeded": "把难度列表滚到固定位置（第一次）。"}}
    nodes["DD_Scroll2"] = {**swipe, "begin": [cx, top, 10, 10], "end": [cx, bot, 10, 10], "next": ["DD_Select"]}
    nodes["DD_Select"] = {"recognition": "DirectHit", "action": "Click", "target": inner("card_top_1"), "post_delay": 700,
                          "next": ["DD_Selected", "DD_SelectRetry"], "focus": {"Node.Action.Succeeded": "已点击目标难度卡片。"}}
    nodes["DD_SelectRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("card_top_1"), "post_delay": 900,
                               "next": ["DD_Selected", "DD_Locked"]}
    nodes["DD_Selected"] = {"recognition": "ColorMatch", "roi": region("edge_top_1"), **GOLD, "count": 300, "connected": False,
                            "action": "Click", "target": inner("list_challenge"), "post_delay": 2500,
                            "next": ["DD_FormationReady", "DD_ChallengeRetry"],
                            "focus": {"Node.Action.Succeeded": "目标难度已选中（金边），点击【挑战】。"}}
    nodes["DD_ChallengeRetry"] = {"recognition": "DirectHit", "action": "Click", "target": inner("list_challenge"),
                                  "post_delay": 2500, "timeout": 20000, "next": ["DD_FormationReady"], "on_error": ["MA_StuckNotice"]}
    args, _ = M.msgbox_args("幻梦深潜：选择的难度没有选中（可能尚未解锁）。请手动选一个可用难度，或在任务选项里改成较低难度。")
    nodes["DD_Locked"] = {"recognition": "DirectHit", "action": "Command", "exec": "powershell.exe", "args": args,
                          "timeout": 30000, "next": [], "on_error": [],
                          "focus": {"Node.Action.Starting": "难度未能选中：已弹出提示并停止。"}}
    # ---- formation page: team tab, then assist chain (sync-rate nodes) or straight to 调查
    nodes["DD_FormationReady"] = {**match("team_header"), "timeout": 30000, "rate_limit": 700, "action": "DoNothing",
                                  "next": ["DD_AfterTeam"], "on_error": ["MA_StuckNotice"], "focus": focus("已进入编队页。")}
    # TeamA_Fix (tools/build_team_pipeline.py) switches the team first when an option asks for it, then the assist chain
    nodes["DD_AfterTeam"] = {"recognition": "DirectHit", "action": "DoNothing",
                             "next": ["TeamA_Fix", "OpenAssistPurple", "OpenAssistRed", "OpenAssist"]}
    nodes["DD_RewardDismiss"] = {**match("reward_title"), "action": "Click", "target": [310, 280, 80, 60],
                                  "post_delay": 900, "next": ["StoryAfterRoute"],
                                  "focus": {"Node.Action.Succeeded": "已关闭开场获得造物弹窗。"}}
    nodes["DD_ItemDismiss"] = {**match("item_title"), "action": "Click", "target": [610, 580, 60, 43],
                                "post_delay": 900, "next": ["StoryAfterRoute"],
                                "focus": {"Node.Action.Succeeded": "已确认地图获得物品弹窗。"}}
    nodes["DD_AbilityPick"] = {**match("ability_title"), "action": "Click", "target": [160, 255, 90, 105],
                                "post_delay": 500, "next": ["DD_AbilityTooltipDismiss"],
                                "focus": {"Node.Action.Succeeded": "已选择能力卡牌。"}}
    nodes["DD_AbilityTooltipDismiss"] = {"recognition": "DirectHit", "action": "Click", "target": [810, 570, 40, 35],
                                          "post_delay": 300, "next": ["DD_AbilityConfirm"]}
    nodes["DD_AbilityConfirm"] = {"recognition": "DirectHit", "action": "Click", "target": [605, 577, 70, 44],
                                   "post_delay": 1000, "next": ["StoryAfterRoute"]}
    nodes["DD_UseRustKey"] = {**match("locked_door_title"), "action": "Click", "target": [760, 490, 80, 45],
                               "post_delay": 1100, "next": ["DD_DoorStillClosed", "StoryAfterRoute"],
                               "focus": {"Node.Action.Succeeded": "锈蚀门扉：已选择使用钥匙。"}}
    nodes["DD_DoorStillClosed"] = {**match("locked_door_title"), "action": "Click", "target": [760, 555, 80, 45],
                                    "post_delay": 1100, "next": ["DD_MapAvoidDoor"],
                                    "focus": {"Node.Action.Succeeded": "钥匙不足，离开门扉并改走另一格。"}}
    nodes["DD_DispelIllusion"] = {**match("illusion_title"), "action": "Click", "target": [760, 490, 80, 45],
                                   "post_delay": 1100, "next": ["DD_IllusionConfirm"],
                                   "focus": {"Node.Action.Succeeded": "幻象：选择驱散，避免离开后重进同一格。"}}
    nodes["DD_IllusionConfirm"] = {"recognition": "DirectHit", "action": "Click", "target": [760, 555, 80, 45],
                                    "post_delay": 1100, "next": ["StoryAfterRoute"]}
    nodes["DD_ArtifactPick"] = {**match("artifact_title"), "action": "Click", "target": [880, 245, 90, 95],
                                 "post_delay": 1400, "next": ["DD_ArtifactConfirm"],
                                 "focus": {"Node.Action.Succeeded": "已选择右侧造物。"}}
    nodes["DD_ArtifactConfirm"] = {"recognition": "DirectHit", "action": "Click", "target": [635, 610, 10, 14],
                                    "post_delay": 1500, "next": ["DD_ArtifactRetry", "StoryAfterRoute"]}
    nodes["DD_ArtifactRetry"] = {**match("artifact_title"), "action": "Click", "target": [635, 610, 10, 14],
                                  "post_delay": 1500, "next": ["StoryAfterRoute"]}
    nodes["DD_EnterSecret"] = {**match("secret_title"), "action": "Click", "target": [760, 490, 80, 45],
                               "post_delay": 1400, "next": ["StoryAfterRoute"],
                               "focus": {"Node.Action.Succeeded": "单行密道：已选择进入。"}}
    nodes["DD_ShopExit"] = {**match("shop_title"), "action": "Click", "target": [1100, 105, 48, 42],
                            "post_delay": 1200, "next": ["StoryAfterRoute"],
                            "focus": {"Node.Action.Succeeded": "已离开幻梦深潜融痕商店。"}}
    nodes["DD_SealCardPick"] = {**match("seal_card_title"), "action": "Click", "target": [625, 295, 30, 95],
                                 "post_delay": 700, "next": ["DD_SealCardConfirm"],
                                 "focus": {"Node.Action.Succeeded": "战后选择中间的刻印卡牌。"}}
    nodes["DD_SealCardConfirm"] = {"recognition": "DirectHit", "action": "Click", "target": [612, 592, 58, 43],
                                    "post_delay": 1400, "next": ["StoryAfterRoute"]}
    nodes["DD_Map"] = {**match("map_title"), "action": "DoNothing", "next": ["DD_Pick"],
                       "focus": focus("已进入幻梦深潜地图。")}
    nodes["DD_Pick"] = {"recognition": "And", "all_of": [match("map_title"),
                         {"recognition": "ColorMatch", "roi": region("map_area"), **CYAN, "count": 250,
                          "connected": True, "order_by": "Horizontal", "index": -1}],
                        "box_index": 1, "action": "Click", "post_delay": 2200, "max_hit": 80, "next": ["StoryAfterRoute"],
                        "on_error": ["MA_StuckNotice"],
                        "focus": {"Node.Action.Succeeded": "已点击青色描边的可走六角格。"}}
    nodes["DD_MapAvoidDoor"] = {**match("map_title"), "action": "DoNothing", "next": ["DD_PickAvoidDoor"]}
    avoid = json.loads(json.dumps(nodes["DD_Pick"], ensure_ascii=False))
    avoid["all_of"][1]["order_by"] = "Vertical"
    avoid["all_of"][1]["index"] = -1
    nodes["DD_PickAvoidDoor"] = avoid
    nodes["DD_FinishedList"] = {**match("list_marker"), "action": "DoNothing", "next": [],
                                "focus": focus("回到难度列表：幻梦深潜任务完成。")}
    nodes["DD_FinishedEntry"] = {**match("entry_title"), "action": "DoNothing", "next": [],
                                 "focus": focus("回到入口页：幻梦深潜任务完成。")}
    return images, nodes, ui


def region_of(ui, name):
    r = ui["regions"][name]
    x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def inner(ui, name, m=10):
    x, y, w, h = region_of(ui, name)
    return [x + m, y + m // 2, max(4, w - 2 * m), max(4, h - m)]


def difficulty_overrides(ui, nodes):
    out = {}
    for key, (state, pos, _) in DIFFS.items():
        card, edge = f"card_{state}_{pos}", f"edge_{state}_{pos}"
        ov = {"DD_Select": {"target": inner(ui, card)}, "DD_SelectRetry": {"target": inner(ui, card)},
              "DD_Selected": {"roi": region_of(ui, edge)}}
        if state == "bot":                    # scroll the other way: down to the bottom of the list
            for name in ("DD_Scroll", "DD_Scroll2"):
                ov[name] = {"begin": nodes[name]["end"], "end": nodes[name]["begin"]}
        out[key] = ov
    return out


def update_interface(orig, ui, nodes):
    d = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    d["option"].pop("幻梦深潜编队", None)                      # replaced by the generic 默认编队 / 本任务编队 options
    ov = difficulty_overrides(ui, nodes)
    d["option"]["幻梦深潜难度"] = {
        "type": "select", "label": "幻梦深潜：挑战难度",
        "description": "进入难度列表后先把列表滚到顶部/底部（位置固定），再点选难度并确认金边。未解锁的难度选不中时弹窗提示并停止。",
        "default_case": "d1", "cases": [{"name": k, "label": lab + ("（默认）" if k == "d1" else ""), "pipeline_override": ov[k]}
                                       for k, (_, _, lab) in DIFFS.items()]}
    d["option"]["幻梦深潜助战"] = {
        "type": "select", "label": "幻梦深潜：是否使用助战",
        "description": "使用助战沿用同调率循环的助战流程（助战→选择角色→上场→调查）；不使用则直接点击调查。",
        "default_case": "use", "cases": [{"name": "use", "label": "使用助战（默认）"},
                                         {"name": "skip", "label": "不使用助战，直接调查",
                                          "pipeline_override": {"DD_AfterTeam": {"next": ["TeamA_Fix", "StartInvestigation"]},
                                                                   "TeamA_Resume": {"next": ["StartInvestigation"]}}}]}
    override = M.task_definition(orig, extra=("DD_FinishedList", "DD_FinishedEntry", "DD_EnterSecret", "DD_ArtifactPick", "DD_UseRustKey", "DD_DispelIllusion", "DD_AbilityPick", "DD_ItemDismiss", "DD_SealCardPick", "DD_ShopExit", "DD_Map", "MA_Map"), done_next=())
    for name in ("StoryAfterRoute", "StoryInsideRouter", "StoryBattleMonitor"):
        front = ("DD_EnterSecret", "DD_ArtifactPick", "DD_UseRustKey", "DD_DispelIllusion", "DD_AbilityPick", "DD_ItemDismiss", "DD_RewardDismiss", "StoryChoiceSealPopup", "DD_SealCardPick", "DD_ShopExit", "DD_Map")
        override[name]["next"] = [*front, *[n for n in override[name]["next"] if n not in front]]
    override["StoryAfterRoute"]["next"] = ["StoryAutoAlreadyOn", "StoryAutoControlReady", *override["StoryAfterRoute"]["next"]]
    for name in ("StoryChoicePostSelectWait", "StoryChoiceArtifactPopup", "StoryChoiceSealPopup"):
        override[name] = {"next": ["DD_Map", *[n for n in orig[name]["next"] if n != "DD_Map"]]}
    # the sync-rate 调查 button leads on into the map / story nodes instead of the sync-rate battle chain
    override["StartInvestigation"] = {"next": ["InvestigationWarningUnchecked", "InvestigationWarningChecked", "DD_ItemDismiss", "DD_RewardDismiss", "DD_Map", "StoryAfterRoute"]}
    override["InvestigationWarningChecked"] = {"next": ["DD_ItemDismiss", "DD_RewardDismiss", "DD_Map", "StoryAfterRoute"]}
    entry = {"name": TASK, "label": "幻梦深潜（走格子打首领）", "entry": "DD_Start",
             "option": ["幻梦深潜难度", "幻梦深潜助战", "主线灵知", "主线战斗超时", "探索选格方式", "剧情购买策略", "剧情造物位置", *TEAM_OPTIONS],
             "default_check": False, "repeatable": False, "pipeline_override": override,
             "description": "入口页挑战 → 选难度 → 挑战 → 编队页（切队伍、助战或直接调查）→ 走格子、事件、商店、战斗直到首领通关，回到列表/入口页即完成。首领战斗超时、战败且灵知用完、画面无法识别时弹窗提示并停止。"}
    tasks = [t for t in d["task"] if t["name"] != TASK]
    at = next((i for i, t in enumerate(tasks) if t["name"] == "记忆回廊列车"), len(tasks))
    tasks.insert(at, entry)
    d["task"] = tasks
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes, ui = build()
    orig = {k: v for k, v in M.load_pipelines().items() if not k.startswith(("DD_", "TR_"))}
    d = update_interface(orig, ui, nodes)
    text, itext = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n", json.dumps(d, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_bytes() == text.encode("utf-8") else [str(OUT)]
        stale += [] if INTERFACE.read_bytes() == itext.encode("utf-8") else [str(INTERFACE)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("dive pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imencode(".png", img)[1].tofile(str(IMAGE / name))
    OUT.write_bytes(text.encode("utf-8"))
    INTERFACE.write_bytes(itext.encode("utf-8"))
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}; interface.json updated")


if __name__ == "__main__":
    main()
