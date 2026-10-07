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
INTERFACE = ROOT / "interface.json"
PROFILES = ROOT / "resource" / "navigation" / "activity_profiles"
MOVE_NAMES = ("ResetA", "ResetB", "MoveA", "MoveB", "MoveC", "MoveD", "MoveE", "MoveF")


def load_profiles():
    """Every activity is one profile file: stage geometry, template images and task names (see README)."""
    out = []
    for path in sorted(PROFILES.glob("*.json")):
        if path.name.startswith("_"):
            continue
        prof = json.loads(path.read_text(encoding="utf-8"))
        out.append(prof)
    prefixes = [p["prefix"] for p in out]
    assert len(set(prefixes)) == len(prefixes), "profile prefixes must be unique"
    return out


def template(name, roi, threshold=0.84):
    return {"recognition": "TemplateMatch", "template": name, "roi": roi,
            "threshold": threshold, "method": 10001}


def click(x, y, radius=12):
    return {"action": "Click", "target": [x - radius, y - radius, radius * 2, radius * 2]}


def swipe(begin, end, y=512):
    return {"recognition": "DirectHit", "action": "Swipe", "begin": [begin, y, 15, 15],
            "end": [end, y, 15, 15], "duration": 500, "post_delay": 650}


def tpl(prof, key, **override):
    t = {**prof["templates"][key], **override}
    return template(t["image"], t["roi"], t["threshold"])


def tclick(prof, key):
    return click(*prof["templates"][key]["click"])


def stage_title(prof, stage):
    """Title template of a stage detail page, or None when the profile gives none (counter fallback)."""
    t = stage.get("title")
    if not t:
        return None
    t = {**prof.get("title_default", {}), **t}
    return template(t["image"], t["roi"], t["threshold"])


def build_nodes(prof):
    n = {}
    stages = prof["stages"]
    count, sy = len(stages), prof.get("swipe_y", 512)
    n["AA_Start"] = {"recognition": "DirectHit", "action": "DoNothing",
                     "next": ["AA_PaidRevive", "AA_DetailBack", "AA_StagePage", "AA_ActivityPage", "AA_Home"]}
    n["AA_DetailBack"] = {**tpl(prof, "detail_back"), **tclick(prof, "detail_back"),
                          "post_delay": 800, "next": ["AA_StagePage"]}
    n["AA_Home"] = {**tpl(prof, "home"), **tclick(prof, "home"), "post_delay": 1400,
                    "next": ["AA_ActivityPage"]}
    n["AA_ActivityPage"] = {**tpl(prof, "activity_page"), "action": "DoNothing", "next": ["AA_CurrentEvent", "ActSlot"]}
    # Theme-specific shortcuts first; any other activity falls through to the generic list-slot / entry-button nodes
    # of activity.json (options 活动列表项 / 活动玩法入口 choose which item and which entry).
    n["AA_CurrentEvent"] = {**tpl(prof, "current_item"), **tclick(prof, "current_item"),
                            "post_delay": 900, "next": ["AA_GoldEntry", "ActEntry"]}
    n["AA_GoldEntry"] = {**tpl(prof, "gold_entry"), **tclick(prof, "gold_entry"),
                         "post_delay": 1400, "next": ["AA_StagePage"]}
    n["AA_StagePage"] = {**tpl(prof, "stage_page"), "action": "DoNothing", "next": ["AA_Stage1_ResetA"]}

    n["AA_MadnessSelected"] = {"recognition": "ColorMatch", "roi": [49, 575, 5, 70],
                               "method": 4, "lower": [150, 170, 180], "upper": [255, 255, 255],
                               "count": 200, "connected": False, "action": "DoNothing",
                               "next": ["CycleStart"]}
    n["AA_MadnessLocked"] = {**tpl(prof, "locked"), "action": "DoNothing", "next": ["AA_SelectSix"]}
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
                           "next": [*[f"AA_Completed{i}" for i in range(1, count + 1)], "AA_AfterSix"]}
    n["AA_AfterSix"] = {**tpl(prof, "detail_back"), "action": "DoNothing", "next": ["AA_SelectMadness"],
                        "focus": {"Node.Recognition.Succeeded": "之六已结算，改选癫狂。"}}
    n["AA_BattleFailed"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                            "focus": {"Node.Recognition.Succeeded": "本关战斗失败，停止推进，避免跳过未通关关卡。"}}
    warning = ("应急灵知体已耗尽，游戏正在询问是否消耗材料兑换复活。"
               "活动自动推进已停止，未点击游戏中的确认或取消。请手动处理复活弹窗。")
    script = ("Add-Type -AssemblyName PresentationFramework; "
              "[System.Windows.MessageBox]::Show('" + warning.replace("'", "''") +
              "','忘却前夜活动预警','OK','Warning') | Out-Null")
    n["AA_PaidRevive"] = {
        **tpl(prof, "paid_revival"),
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

    madness = {k: v for k, v in n["AA_MadnessSelected"].items() if k not in ("action", "next")}
    for i, stage in enumerate(stages, 1):
        moves = [*prof.get("reset_swipes", []), *stage.get("swipes", [])]
        assert len(moves) <= len(MOVE_NAMES), f"stage {i}: too many swipes"
        names = [f"AA_Stage{i}_{MOVE_NAMES[j]}" for j in range(len(moves))]
        click_node = f"AA_Stage{i}_Click"
        for j, (name, (a, b)) in enumerate(zip(names, moves)):
            n[name] = {**swipe(a, b, sy), "next": [names[j + 1] if j + 1 < len(names) else click_node]}
        cx, cy = stage["click"]
        n[click_node] = {**tpl(prof, "stage_page"), **click(cx, cy, 18), "post_delay": 950,
                         "next": [f"AA_Stage{i}_Detail"],
                         "focus": {"Node.Action.Succeeded": f"进入活动第 {i} 关：{stage['label']}。"}}
        title = stage_title(prof, stage)
        if title:
            n[f"AA_Stage{i}_Detail"] = {**title, "action": "DoNothing", "next": ["AA_ScrollDifficulty"]}
            done = {"recognition": "And", "all_of": [title, madness], "box_index": 0}
        else:
            # No title image for this stage: the detail page is not verified, and the "done" node can fire only once
            # per run (max_hit), so AfterResult walks AA_Completed1..N in order.
            n[f"AA_Stage{i}_Detail"] = {"recognition": "DirectHit", "action": "DoNothing",
                                        "next": ["AA_ScrollDifficulty"]}
            done = {**madness, "max_hit": 1}
        n[f"AA_Completed{i}"] = {**done, "action": "DoNothing",
                                 "next": [f"AA_BackToStage{i + 1}"] if i < count else [],
                                 "focus": {"Node.Recognition.Succeeded": f"第 {i} 关癫狂已结算。"}}
        if i < count:
            n[f"AA_BackToStage{i + 1}"] = {"recognition": "DirectHit", **tclick(prof, "detail_back"),
                                           "post_delay": 750, "next": [f"AA_Stage{i + 1}_Page"]}
            n[f"AA_Stage{i + 1}_Page"] = {"recognition": "DirectHit", "action": "DoNothing",
                                          "next": [f"AA_Stage{i + 1}_Ready", f"AA_Stage{i + 1}_Reenter"]}
            n[f"AA_Stage{i + 1}_Ready"] = {**tpl(prof, "stage_page"), "action": "DoNothing",
                                           "next": [f"AA_Stage{i + 1}_ResetA"]}
            n[f"AA_Stage{i + 1}_Reenter"] = {**tpl(prof, "gold_entry"), **tclick(prof, "gold_entry"),
                                             "post_delay": 1400, "next": [f"AA_Stage{i + 1}_Page"]}
    return rename(n, prof["prefix"])


def rename(nodes, prefix):
    """Node names are written with the AA_ prefix; other activities get their own so profiles never collide."""
    if prefix == "AA":
        return nodes
    text = json.dumps(nodes, ensure_ascii=False).replace('"AA_', f'"{prefix}_')
    return json.loads(text)


def task_overrides(prof):
    P = prof["prefix"]
    finish = {name: {"next": [f"{P}_AfterResult"]} for name in
              ("FinishCurrentButton", "FinishAltButton", "FinishButtonClickRetry")}
    finish["BattleMonitor"] = {"next": [f"{P}_PaidRevive", "ReviveDecision", "FinishInvestigation"]}
    finish["StartInvestigation"] = {"next": ["InvestigationWarningUnchecked", "InvestigationWarningChecked",
                                             "HideCards", "BattleStartSignal", "AutoAlreadyOn", "AutoControlReady",
                                             f"{P}_PaidRevive", "ReviveDecision", "FinishInvestigation"]}
    finish["FailureChoice"] = {"next": [f"{P}_BattleFailed"]}
    finish["StopHere"] = {"next": [f"{P}_BattleFailed"]}
    # the generic entry buttons must also recognise this activity's stage page
    for name, orig in generic_entry_nodes().items():
        finish[name] = {"next": [f"{P}_StagePage", *[x for x in orig if x != f"{P}_StagePage"]]}
    return finish


def generic_entry_nodes():
    activity = json.loads((ROOT / "resource" / "pipeline" / "activity.json").read_text(encoding="utf-8-sig"))
    return {k: v["next"] for k, v in activity.items() if k.startswith("ActEntry") and "next" in v}


def revive_option(prefix):
    return {"ReviveDecision": {"target_offset": [341, 343, -292, -92], "next": [f"{prefix}_PostReviveWait"]}}


def scope_cases(prof):
    """Option cases of the single task: the whole run, or one stage (its page/completion nodes are redirected)."""
    P, stages = prof["prefix"], prof["stages"]
    so = prof["scope_option"]
    cases = [{"name": "all", "label": so["all_label"].format(n=len(stages))}]
    for i, stage in enumerate(stages, 1):
        cases.append({"name": f"stage{i}", "label": so["stage_label"].format(i=i, title=stage["label"]),
                      "pipeline_override": {f"{P}_StagePage": {"next": [f"{P}_Stage{i}_ResetA"]},
                                            f"{P}_Completed{i}": {"next": []}}})
    return cases


def profile_task(prof):
    P, count = prof["prefix"], len(prof["stages"])
    ta, so = prof["task_all"], prof["scope_option"]
    return {"name": ta["name"], "label": ta["label"], "entry": f"{P}_Start",
            "option": [so["name"], "同调率助战", "活动应急灵知体", "活动列表项", "活动玩法入口"], "default_check": False,
            "repeatable": False, "pipeline_override": task_overrides(prof),
            "description": ta["description"].format(n=count)}


def update_interface(profiles):
    data = json.loads(INTERFACE.read_text(encoding="utf-8"))
    first = profiles[0]
    data["option"]["活动应急灵知体"] = {
        "type": "select", "label": "活动：战败时使用应急灵知体",
        "description": "使用每日可获得的应急灵知体继续当前战斗；次数用完时停止。",
        "default_case": "use",
        "cases": [
            {"name": "use", "label": "使用灵知（默认）", "pipeline_override": revive_option(first["prefix"])},
            {"name": "skip", "label": "不使用灵知，战败停止"},
        ],
    }
    for p in profiles:
        so = p["scope_option"]
        data["option"][so["name"]] = {"type": "select", "label": so["label"],
                                      "description": so["description"].format(n=len(p["stages"])),
                                      "default_case": "all", "cases": scope_cases(p)}
    mine = {p["task_all"]["name"] for p in profiles}
    data["task"] = [t for t in data["task"] if t["name"] not in mine and not t["name"].startswith("自动活动推进")
                    and not t["name"].startswith("活动自动推进")]
    tasks = [profile_task(p) for p in profiles]
    mainline = next((j for j, t in enumerate(data["task"]) if t["name"] in ("幻梦深潜", "记忆回廊列车", "自动推进主线")), len(data["task"]))
    data["task"][mainline:mainline] = tasks
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    profiles = load_profiles()
    outputs = {ROOT / "resource" / "pipeline" / p["pipeline"]:
               (json.dumps(build_nodes(p), ensure_ascii=False, indent=2) + "\n").encode("utf-8") for p in profiles}
    interface = (json.dumps(update_interface(profiles), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if args.check:
        if any(not path.is_file() or path.read_bytes() != data for path, data in outputs.items()) \
                or INTERFACE.read_bytes() != interface:
            raise SystemExit("activity advance resources are out of date")
        print("activity advance resources are up to date")
        return
    for path, data in outputs.items():
        path.write_bytes(data)
    INTERFACE.write_bytes(interface)
    print(", ".join(f"{p['id']}: {len(p['stages'])} stages" for p in profiles))


if __name__ == "__main__":
    main()
