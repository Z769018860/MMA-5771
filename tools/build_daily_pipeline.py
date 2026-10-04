"""Generate the 密境课室 (daily/weekly) and 幕间演习 one-click dispatch pipeline.

    python tools/build_daily_pipeline.py [--check]

Spec: resource/navigation/daily_ui.json; samples: resource/navigation/samples/*.png (1280x720 real screenshots).
Output: resource/pipeline/daily.json and resource/image/daily_*.png
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT = B.ROOT
NAV, IMAGE = B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "daily.json"


def build():
    ui = json.loads((NAV / "daily_ui.json").read_text(encoding="utf-8"))
    nav = json.loads((NAV / "nav_ui.json").read_text(encoding="utf-8"))
    thr, margin = 0.8, 14
    images, nodes, rects = {}, {}, {}

    def region(name):
        r = ui["regions"][name]
        return B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])

    def click_region(name, shrink=6):
        x0, y0, x1, y1 = region(name)
        return [x0 + shrink, y0 + shrink, max(4, x1 - x0 - 2 * shrink), max(4, y1 - y0 - 2 * shrink)]

    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imread(str(NAV / "samples" / sc["sample"]))
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"daily_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]

    def match(tid, threshold=None, roi=None):
        t = next(t for t in ui["templates"] if t["id"] == tid)
        return {"recognition": "TemplateMatch", "template": f"daily_{tid}.png",
                "roi": roi or B.grow(rects[tid], margin), "threshold": threshold or t.get("threshold", thr), "method": 10001}

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    def action(name, rec, act, nxt, delay=900, note=None, **extra):
        node = {**rec, **act, "post_delay": delay, "next": nxt}
        node.update(extra)
        if note:
            node["focus"] = {"Node.Action.Succeeded": note}
        nodes[name] = node

    direct = {"recognition": "DirectHit"}
    tap = lambda region_name: {"action": "Click", "target": click_region(region_name)}
    tabs = {"daily": "cr_daily", "weekly": "cr_weekly"}

    # ------------------------------------------------------------------ 密境课室
    nodes["CR_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["CR_PageDaily", "CR_PageWeekly", "CR_FromHome"],
                         "focus": focus("密境课室：从日常/周常页或主界面开始。")}
    home = json.loads((ROOT / "resource" / "pipeline" / "navigation.json").read_text(encoding="utf-8"))
    nodes["CR_FromHome"] = {**home["NavHome_secret_classroom"], "next": ["CR_PageDaily"], "timeout": 20000}
    nodes["CR_FromHomeInterlude"] = {**home["NavHome_interlude"], "next": ["IL_Page"], "timeout": 20000}
    for kind, tid in tabs.items():
        K = kind[0].upper()
        nodes[f"CR_Page{kind.capitalize()}"] = {
            "recognition": "And", "all_of": [match("cr_title"), match(tid)], "box_index": 0,
            "action": "DoNothing", "timeout": 15000, "next": [f"CR_{K}_Claim", f"CR_{K}_Nodes"],
            "focus": focus(f"已进入密境课室【{'日常' if kind == 'daily' else '周常'}试训】页。")}
        # claim every visible 领取 button (top to bottom), closing the reward popup after each
        nodes[f"CR_{K}_Claim"] = {
            "recognition": "And",
            "all_of": [match("cr_title"), {**match("cr_claim", roi=region("claim_column")), "order_by": "Vertical", "index": 0}],
            "box_index": 1,
            "action": "Click", "target_offset": [8, 6, -16, -12], "post_delay": 1500,
            "next": [f"CR_{K}_Popup", f"CR_{K}_Claim", f"CR_{K}_Nodes"],
            "focus": {"Node.Action.Succeeded": "已点击一个任务的【领取】。"}}
        nodes[f"CR_{K}_Popup"] = {
            **match("reward_title", roi=B.grow([480, 150, 320, 90], 0)), "action": "Click",
            "target": click_region("reward_blank"), "post_delay": 1200,
            "next": [f"CR_{K}_Claim", f"CR_{K}_Nodes"],
            "focus": {"Node.Action.Succeeded": "已关闭【获得物资】弹窗。"}}
        # milestone gift boxes along the bottom progress bar
        nodes[f"CR_{K}_Nodes"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [f"CR_{K}_Node1"],
                                  "focus": focus("开始点击底部进度节点领取奖励。")}
        for i in range(1, 5):
            last = i == 4
            nodes[f"CR_{K}_Node{i}"] = {
                "recognition": "DirectHit", **tap(f"gift_{i}"), "post_delay": 1200,
                "next": [f"CR_{K}_NodePopup{i}", f"CR_{K}_NodeBlank{i}"]}
            nodes[f"CR_{K}_NodePopup{i}"] = {
                **match("reward_title", roi=B.grow([480, 150, 320, 90], 0)), "action": "Click",
                "target": click_region("reward_blank"), "post_delay": 1000,
                "next": [f"CR_{K}_End" if last else f"CR_{K}_Node{i + 1}"]}
            nodes[f"CR_{K}_NodeBlank{i}"] = {
                "recognition": "DirectHit", **tap("safe_blank"), "post_delay": 600,
                "next": [f"CR_{K}_End" if last else f"CR_{K}_Node{i + 1}"],
                "focus": {"Node.Action.Succeeded": f"节点 {i} 点击后没有出现【获得物资】（可能未达成或已领取）；点击空白处关闭提示。"}}
        nodes[f"CR_{K}_End"] = {"recognition": "DirectHit", "action": "DoNothing",
                                "next": ["CR_ToWeekly"] if kind == "daily" else ["CR_Done"]}
    nodes["CR_ToWeekly"] = {"recognition": "And", "all_of": [match("cr_title")], "box_index": 0, **tap("tab_weekly"), "post_delay": 1500, "next": ["CR_PageWeekly"],
                            "focus": {"Node.Action.Succeeded": "已点击左侧【周常】页签。"}}
    nodes["CR_ToDaily"] = {"recognition": "And", "all_of": [match("cr_title")], "box_index": 0, **tap("tab_daily"), "post_delay": 1500, "next": ["CR_PageDaily"]}
    nodes["CR_Done"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                        "focus": focus("密境课室领取完成。")}

    # ------------------------------------------------------------------ 幕间演习
    nodes["IL_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["IL_Page", "CR_FromHomeInterlude"],
                         "focus": focus("幕间演习：从派遣页或主界面开始。")}
    nodes["IL_Page"] = {"recognition": "And", "all_of": [match("il_title"), match("il_limit")], "box_index": 0,
                        "action": "DoNothing", "timeout": 15000, "next": ["IL_OneClick"],
                        "focus": focus("已进入幕间演习【派遣】页。")}
    nodes["IL_OneClick"] = {"recognition": "And", "all_of": [match("il_title"), match("il_limit")], "box_index": 0,
                            **tap("il_oneclick"), "post_delay": 2000,
                            "next": ["IL_Popup", "IL_Report", "IL_Done"],
                            "focus": {"Node.Action.Succeeded": "已点击左下角一键按钮（有可领取任务时是【一键领取】，没有时是一键派遣）。"}}
    nodes["IL_Popup"] = {**match("reward_title", roi=B.grow([480, 150, 320, 90], 0)), "action": "Click",
                         "target": click_region("reward_blank"), "post_delay": 1500,
                         "next": ["IL_Report", "IL_Done"],
                         "focus": {"Node.Action.Succeeded": "已关闭【获得物资】弹窗。"}}
    nodes["IL_Report"] = {**match("report_title", roi=B.grow([480, 80, 320, 90], 0)), "action": "DoNothing",
                          "next": ["IL_ReportAgain"], "timeout": 10000,
                          "focus": focus("出现【调查报告】；按设置点击【再次派遣】或【关闭】。")}
    nodes["IL_ReportAgain"] = {"recognition": "And", "all_of": [match("report_title", roi=B.grow([480, 80, 320, 90], 0)),
                                                              match("report_again", roi=B.grow(rects["report_again"], 30))],
                               "box_index": 1, "action": "Click",
                               "target_offset": [10, 8, -20, -16], "post_delay": 2500, "next": ["IL_Popup2", "IL_Done"],
                               "focus": {"Node.Action.Succeeded": "已点击【再次派遣】。"}}
    nodes["IL_Popup2"] = {**nodes["IL_Popup"], "next": ["IL_Done"]}
    nodes["IL_ReportClose"] = {"recognition": "And", "all_of": [match("report_title", roi=B.grow([480, 80, 320, 90], 0)),
                                                              match("report_close", roi=B.grow(rects["report_close"], 30))],
                               "box_index": 1, "action": "Click",
                               "target_offset": [10, 8, -20, -16], "post_delay": 1500, "next": ["IL_Done"],
                               "focus": {"Node.Action.Succeeded": "已点击【关闭】。"}}
    nodes["IL_Done"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                        "focus": focus("幕间演习一键流程完成。")}
    return images, nodes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes = build()
    text = json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_text(encoding="utf-8") == text else [str(OUT)]
        stale += [str(IMAGE / n) for n in images if not (IMAGE / n).is_file()]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("daily pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
