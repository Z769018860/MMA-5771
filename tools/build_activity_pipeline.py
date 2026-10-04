"""Generate the generic limited-time-activity entry used by the sync-rate loop.

    python tools/build_activity_pipeline.py [--check]

Home banner -> activity list ("活动" page: pick list item) -> gameplay entry button (left/right) ->
activity stage page (nodes with 掉落预览: pick node 1..5) -> hand over to the old CycleStart (挑战).
Nothing in it depends on the activity's name: pages are recognised by generic labels and positions are settings.
Spec: resource/navigation/activity_ui.json. Output: resource/pipeline/activity.json, resource/image/activity_*.png
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "activity.json"
AFTER = ["CycleStart", "ChooseFeather", "ChooseMadness", "OpenAssist"]   # pages the old loop already knows how to continue from


def build():
    ui = json.loads((NAV / "activity_ui.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imread(str(NAV / "samples" / sc["sample"]))
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"activity_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, roi=None, grow=16):
        return {"recognition": "TemplateMatch", "template": f"activity_{tid}.png", "roi": roi or B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def sbox(screen, box):
        return B.scale_box(box, ui["screens"][screen]["src_size"])

    def click(x, y, r=8):
        return {"action": "Click", "target": [int(x) - r, int(y) - r, 2 * r, 2 * r]}

    # ------------------------------------------------------------------ activity list page
    nodes["ActivityScreen"] = {**match("act_title"), "timeout": 120000, "rate_limit": 700, "action": "DoNothing",
                               "next": ["ActSlot", "ActEntry"],
                               "focus": {"Node.Recognition.Succeeded": "已进入【活动】页。"}}
    nodes["ActSlot"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["ActEntry"]}
    sx = ui["slots"]["x"] * 1280 / ui["screens"][ui["slots"]["screen"]]["src_size"][0]
    for i, y in enumerate(ui["slots"]["y"], 1):
        sy = y * 720 / ui["screens"][ui["slots"]["screen"]]["src_size"][1]
        nodes[f"ActSlot{i}"] = {"recognition": "DirectHit", **click(sx, sy), "post_delay": 1500, "next": ["ActEntry"],
                                "focus": {"Node.Action.Succeeded": f"已点击活动列表第 {i} 项。"}}
    # gameplay entry (right = gold, left = blue); verified by the activity title still being visible
    for side in ("right", "left"):
        x0, y0, x1, y1 = sbox(ui["entries"][side]["screen"], ui["entries"][side]["box"])
        nodes[f"ActEntry_{side}"] = {"recognition": "DirectHit", **click((x0 + x1) / 2, (y0 + y1) / 2, 18), "post_delay": 2200,
                                     "next": ["ActStagePage", *AFTER, "ActEntryRetry"],
                                     "focus": {"Node.Action.Succeeded": f"已点击{ui['entries'][side]['label']}。"}}
    nodes["ActEntry"] = {**nodes["ActEntry_right"], "recognition": "And", "all_of": [match("act_title")], "box_index": 0}
    nodes["ActEntryRetry"] = {**nodes["ActEntry"], "next": ["ActStagePage", *AFTER], "timeout": 15000,
                              "focus": {"Node.Action.Succeeded": "入口没有生效，再点一次。"}}

    # ------------------------------------------------------------------ stage page with nodes
    nodes["ActStagePage"] = {**match("act_drop", roi=[0, 440, 1280, 160], grow=0), "timeout": 120000, "rate_limit": 700,
                             "action": "DoNothing", "next": ["ActNode", "ActNode1"],
                             "focus": {"Node.Recognition.Succeeded": "已进入活动关卡页（识别到节点下的【掉落预览】）。"}}
    nodes["ActNode"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["ActNode1"]}
    sc = ui["screens"][ui["nodes"]["screen"]]["src_size"]
    ny = ui["nodes"]["y"] * 720 / sc[1]
    for i, x in enumerate(ui["nodes"]["x"], 1):
        nodes[f"ActNode{i}"] = {"recognition": "And", "all_of": [match("act_drop", roi=[0, 440, 1280, 160], grow=0)], "box_index": 0,
                                **click(x * 1280 / sc[0], ny, 22), "post_delay": 2200,
                                "next": [*AFTER, f"ActNodeRetry{i}"],
                                "focus": {"Node.Action.Succeeded": f"已点击活动关卡节点 {i}。"}}
        nodes[f"ActNodeRetry{i}"] = {**nodes[f"ActNode{i}"], "timeout": 15000, "next": AFTER,
                                     "focus": {"Node.Action.Succeeded": f"节点 {i} 没有进入下一页，再点一次。"}}
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
        print("activity pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
