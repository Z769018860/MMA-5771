"""Add an optional monthly-card popup check to daily task entry points.

Run after the daily and sweep pipeline builders. The game's daily reset is at
09:00 Asia/Shanghai; detection is visual, so no local clock adjustment is needed.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "interface.json"
PIPELINES = {
    "CR_Start": ROOT / "resource/pipeline/daily.json",
    "IL_Start": ROOT / "resource/pipeline/daily.json",
    "Soc_Start": ROOT / "resource/pipeline/social.json",
    "Sweep_Start": ROOT / "resource/pipeline/sweep.json",
    "Shop_Start": ROOT / "resource/pipeline/shop.json",
}


def main():
    interface = json.loads(INTERFACE.read_text(encoding="utf-8-sig"))
    overrides = {}
    for start, path in PIPELINES.items():
        if not path.exists():
            continue
        nodes = json.loads(path.read_text(encoding="utf-8-sig"))
        original = [n for n in nodes[start]["next"]
                    if n not in (f"Monthly_{start}", f"MonthlyReward_{start}")]
        monthly = f"Monthly_{start}"
        reward = f"MonthlyReward_{start}"
        nodes[monthly] = {
            "recognition": "And",
            "all_of": [
                {"recognition": "TemplateMatch", "template": "monthly_claim_prompt.png",
                 "roi": [490, 595, 300, 85], "threshold": 0.82, "method": 10001},
                {"recognition": "TemplateMatch", "template": "monthly_remaining_label.png",
                 "roi": [565, 65, 100, 75], "threshold": 0.82, "method": 10001},
            ],
            "box_index": 0,
            "action": "Click", "target": [610, 310, 60, 70],
            "post_delay": 7000, "next": [reward, *original],
            "focus": {"Node.Action.Succeeded": "识别到月卡登录页，已点击领取月相观测奖励。"},
        }
        nodes[reward] = {
            "recognition": "TemplateMatch", "template": "daily_reward_title.png",
            "roi": [480, 150, 320, 90], "threshold": 0.8, "method": 10001,
            "action": "Click", "target": [1030, 470, 80, 70],
            "post_delay": 1200, "next": original,
            "focus": {"Node.Action.Succeeded": "已关闭月卡领取后的【获得物资】弹窗。"},
        }
        path.write_bytes((json.dumps(nodes, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        overrides[start] = {"next": [monthly, reward, *original]}

    interface["option"]["月卡弹窗识别"] = {
        "type": "select", "label": "识别月卡登录页",
        "description": "游戏日常日期在每天 09:00 切换。有月卡时，运行日常任务会先识别并领取月相观测奖励。",
        "default_case": "enabled",
        "cases": [
            {"name": "enabled", "label": "开启（默认）", "pipeline_override": overrides},
            {"name": "disabled", "label": "关闭"},
        ],
    }
    for task in interface["task"]:
        if task["entry"] in PIPELINES:
            task["option"] = ["月卡弹窗识别", *[o for o in task["option"] if o != "月卡弹窗识别"]]
    INTERFACE.write_bytes((json.dumps(interface, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
