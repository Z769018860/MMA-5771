"""Build the nine selectable stages of the current battle activity.

Run ``python tools/build_activity_advance.py`` after editing stage positions or
templates. The generated tasks can be checked independently, or run in order
with the all-stage task.
"""

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "resource/pipeline/activity_advance.json"
INTERFACE = ROOT / "interface.json"
STAGES = (
    "危险席位", "向怨朝圣", "战余的枯骨", "妖影的诱惑", "荒原尽头",
    "未赴之约", "暗塔", "归于光中", "无形的骑士",
)
STAGE_X = (168, 438, 708, 978, 456, 230, 500, 770, 1040)


def template(name, roi, threshold=0.84):
    return {"recognition": "TemplateMatch", "template": name, "roi": roi,
            "threshold": threshold, "method": 10001}


def click(x, y, radius=12):
    return {"action": "Click", "target": [x - radius, y - radius, radius * 2, radius * 2]}


def swipe(begin, end):
    return {"recognition": "DirectHit", "action": "Swipe", "begin": [begin, 512, 15, 15],
            "end": [end, 512, 15, 15], "duration": 500, "post_delay": 650}


def build_nodes():
    n = {}
    n["AA_Start"] = {"recognition": "DirectHit", "action": "DoNothing",
                     "next": ["AA_PaidRevive", "AA_DetailBack", "AA_StagePage", "AA_ActivityPage", "AA_Home"]}
    n["AA_DetailBack"] = {**template("challenge.png", [930, 550, 340, 160], 0.53),
                          **click(1238, 38, 10), "post_delay": 800, "next": ["AA_StagePage"]}
    n["AA_Home"] = {**template("home_marker.png", [1040, 70, 235, 210], 0.48),
                    **click(160, 477, 12), "post_delay": 1400, "next": ["AA_ActivityPage"]}
    n["AA_ActivityPage"] = {**template("activity_act_title.png", [65, 0, 210, 80], 0.79),
                            "action": "DoNothing", "next": ["AA_CurrentEvent"]}
    n["AA_CurrentEvent"] = {**template("activity_advance_current_item.png", [0, 340, 250, 320], 0.80),
                            **click(90, 450, 15), "post_delay": 900, "next": ["AA_GoldEntry"]}
    n["AA_GoldEntry"] = {**template("activity_advance_gold_entry.png", [930, 610, 320, 80], 0.78),
                         **click(1095, 647, 22), "post_delay": 1400, "next": ["AA_StagePage"]}
    n["AA_StagePage"] = {**template("activity_advance_stage_page.png", [0, 15, 310, 85], 0.86),
                         "action": "DoNothing", "next": ["AA_Stage1_ResetA"]}

    n["AA_MadnessSelected"] = {"recognition": "ColorMatch", "roi": [49, 575, 5, 70],
                               "method": 4, "lower": [150, 170, 180], "upper": [255, 255, 255],
                               "count": 200, "connected": False, "action": "DoNothing",
                               "next": ["CycleStart"]}
    n["AA_MadnessLocked"] = {**template("activity_advance_locked.png", [40, 560, 390, 105], 0.88),
                             "action": "DoNothing", "next": ["AA_SelectSix"]}
    n["AA_SelectSix"] = {"recognition": "DirectHit", **click(200, 520, 13),
                         "post_delay": 450, "next": ["CycleStart"],
                         "focus": {"Node.Action.Succeeded": "癫狂尚未解锁，先挑战当前关的之六。"}}
    n["AA_SelectMadness"] = {"recognition": "DirectHit", **click(200, 615, 13),
                             "post_delay": 650, "next": ["AA_MadnessSelected", "AA_SelectMadnessRetry"],
                             "focus": {"Node.Action.Succeeded": "已选择当前关癫狂难度。"}}
    n["AA_SelectMadnessRetry"] = {"recognition": "DirectHit", **click(200, 615, 10),
                                  "post_delay": 750,
                                  "next": ["AA_MadnessSelected", "AA_SelectMadnessLast"]}
    n["AA_SelectMadnessLast"] = {"recognition": "DirectHit", **click(200, 615, 8),
                                 "post_delay": 850, "next": ["AA_MadnessSelected"]}
    n["AA_ScrollDifficulty"] = {"recognition": "DirectHit", "action": "Swipe",
                                "begin": [185, 585, 20, 20], "end": [185, 165, 20, 20],
                                "duration": 450, "post_delay": 650,
                                "next": ["AA_MadnessSelected", "AA_MadnessLocked", "AA_SelectMadness"]}
    n["AA_AfterResult"] = {"recognition": "DirectHit", "action": "DoNothing",
                           "post_delay": 1500,
                           "next": [*[f"AA_Completed{i}" for i in range(1, 10)], "AA_AfterSix"]}
    n["AA_AfterSix"] = {**template("challenge.png", [930, 550, 340, 160], 0.53),
                        "action": "DoNothing", "next": ["AA_SelectMadness"],
                        "focus": {"Node.Recognition.Succeeded": "之六已结算，改选癫狂。"}}
    n["AA_BattleFailed"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                            "focus": {"Node.Recognition.Succeeded": "本关战斗失败，停止推进，避免跳过未通关关卡。"}}
    warning = ("应急灵知体已耗尽，游戏正在询问是否消耗材料兑换复活。"
               "活动自动推进已停止，未点击游戏中的确认或取消。请手动处理复活弹窗。")
    script = ("Add-Type -AssemblyName PresentationFramework; "
              "[System.Windows.MessageBox]::Show('" + warning.replace("'", "''") +
              "','忘却前夜活动预警','OK','Warning') | Out-Null")
    n["AA_PaidRevive"] = {
        **template("activity_advance_paid_revival.png", [350, 245, 600, 120], 0.85),
        "action": "Command", "exec": "powershell.exe",
        "args": ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand",
                 base64.b64encode(script.encode("utf-16-le")).decode("ascii")],
        "timeout": 30000, "next": [], "on_error": [],
        "focus": {"Node.Action.Starting": "付费复活弹窗已出现：停止推进并弹出预警；不会消耗材料。",
                  "Node.Action.Failed": "付费复活弹窗已出现，预警框弹出失败；自动推进仍已停止。"}}
    n["AA_PostReviveWait"] = {"recognition": "DirectHit", "action": "DoNothing",
                              "post_delay": 4500,
                              "next": ["AA_PaidRevive", "AA_ReviveAuto"],
                              "focus": {"Node.Action.Succeeded": "复活后等待画面稳定，重新确认 AUTO。"}}
    n["AA_ReviveAuto"] = {"recognition": "DirectHit", **click(65, 495, 8),
                          "post_delay": 700, "next": ["AutoVerifyWait"],
                          "focus": {"Node.Action.Succeeded": "复活会关闭 AUTO，已重新点击开启。"}}

    for i, name in enumerate(STAGES, 1):
        reset_a = f"AA_Stage{i}_ResetA"
        reset_b = f"AA_Stage{i}_ResetB"
        n[reset_a] = {**swipe(240, 1040), "next": [reset_b]}
        after_reset = f"AA_Stage{i}_Click" if i < 5 else f"AA_Stage{i}_MoveA"
        n[reset_b] = {**swipe(240, 1040), "next": [after_reset]}
        if i == 5:
            n[f"AA_Stage{i}_MoveA"] = {**swipe(1080, 560), "next": [f"AA_Stage{i}_Click"]}
        elif i > 5:
            n[f"AA_Stage{i}_MoveA"] = {**swipe(1080, 280), "next": [f"AA_Stage{i}_MoveB"]}
            n[f"AA_Stage{i}_MoveB"] = {**swipe(1080, 280), "next": [f"AA_Stage{i}_Click"]}
        n[f"AA_Stage{i}_Click"] = {**template("activity_advance_stage_page.png", [0, 15, 310, 85], 0.86),
                                    **click(STAGE_X[i - 1], 512, 18), "post_delay": 950,
                                    "next": [f"AA_Stage{i}_Detail"],
                                    "focus": {"Node.Action.Succeeded": f"进入活动第 {i} 关：{name}。"}}
        title = template(f"activity_advance_title_{i}.png", [0, 20, 310, 80], 0.87)
        n[f"AA_Stage{i}_Detail"] = {**title, "action": "DoNothing",
                                     "next": ["AA_ScrollDifficulty"]}
        n[f"AA_Completed{i}"] = {"recognition": "And", "all_of": [
            title, {k: v for k, v in n["AA_MadnessSelected"].items()
                    if k not in ("action", "next")}], "box_index": 0,
            "action": "DoNothing", "next": [f"AA_BackToStage{i + 1}"] if i < 9 else [],
            "focus": {"Node.Recognition.Succeeded": f"第 {i} 关癫狂已结算。"}}
        if i < 9:
            n[f"AA_BackToStage{i + 1}"] = {"recognition": "DirectHit", **click(1238, 38, 10),
                                              "post_delay": 750,
                                              "next": [f"AA_Stage{i + 1}_Page"]}
            n[f"AA_Stage{i + 1}_Page"] = {"recognition": "DirectHit", "action": "DoNothing",
                                           "next": [f"AA_Stage{i + 1}_Ready", f"AA_Stage{i + 1}_Reenter"]}
            n[f"AA_Stage{i + 1}_Ready"] = {
                **template("activity_advance_stage_page.png", [0, 15, 310, 85], 0.86),
                "action": "DoNothing", "next": [f"AA_Stage{i + 1}_ResetA"]}
            n[f"AA_Stage{i + 1}_Reenter"] = {
                **template("activity_advance_gold_entry.png", [930, 610, 320, 80], 0.78),
                **click(1095, 647, 22), "post_delay": 1400,
                "next": [f"AA_Stage{i + 1}_Page"]}
    return n


def update_interface():
    data = json.loads(INTERFACE.read_text(encoding="utf-8"))
    data["option"]["活动应急灵知体"] = {
        "type": "select", "label": "活动：战败时使用应急灵知体",
        "description": "使用每日可获得的应急灵知体继续当前战斗；次数用完时停止。",
        "default_case": "use",
        "cases": [
            {"name": "use", "label": "使用灵知（默认）", "pipeline_override": {
                "ReviveDecision": {"target_offset": [341, 343, -292, -92],
                                   "next": ["AA_PostReviveWait"]}}},
            {"name": "skip", "label": "不使用灵知，战败停止"},
        ],
    }
    data["task"] = [t for t in data["task"] if not t["name"].startswith("自动活动推进")]
    finish = {name: {"next": ["AA_AfterResult"]} for name in
              ("FinishCurrentButton", "FinishAltButton", "FinishButtonClickRetry")}
    finish["BattleMonitor"] = {"next": ["AA_PaidRevive", "ReviveDecision", "FinishInvestigation"]}
    finish["StartInvestigation"] = {"next": ["InvestigationWarningUnchecked", "InvestigationWarningChecked",
                                             "HideCards", "BattleStartSignal", "AutoAlreadyOn", "AutoControlReady",
                                             "AA_PaidRevive", "ReviveDecision", "FinishInvestigation"]}
    finish["FailureChoice"] = {"next": ["AA_BattleFailed"]}
    finish["StopHere"] = {"next": ["AA_BattleFailed"]}
    all_task = {"name": "自动活动推进全部", "label": "活动自动推进：第 1–9 关",
                "entry": "AA_Start", "option": ["同调率助战", "活动应急灵知体"], "default_check": False,
                "repeatable": False, "pipeline_override": finish,
                "description": "倘若荣光不复：依次挑战第 1–9 关癫狂；未解锁则先打之六。战败即停止。"}
    single = []
    for i, title in enumerate(STAGES, 1):
        override = {**finish, "AA_StagePage": {"next": [f"AA_Stage{i}_ResetA"]},
                    f"AA_Completed{i}": {"next": []}}
        single.append({"name": f"自动活动推进第{i}关", "label": f"活动第 {i} 关：{title}",
                       "entry": "AA_Start", "option": ["同调率助战", "活动应急灵知体"],
                       "default_check": False, "repeatable": False,
                       "pipeline_override": override,
                       "description": "仅挑战这一关；癫狂未解锁时先打之六。"})
    mainline = next((j for j, t in enumerate(data["task"]) if t["name"] == "自动推进主线"), len(data["task"]))
    data["task"][mainline:mainline] = [all_task, *single]
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    pipeline = (json.dumps(build_nodes(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    interface = (json.dumps(update_interface(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.check:
        if not OUT.is_file() or OUT.read_bytes() != pipeline or INTERFACE.read_bytes() != interface:
            raise SystemExit("activity advance resources are out of date")
        print("activity advance resources are up to date")
        return
    OUT.write_bytes(pipeline)
    INTERFACE.write_bytes(interface)
    print(f"{len(STAGES)} stages, {len(build_nodes())} nodes")


if __name__ == "__main__":
    main()
