"""Generate the 校友会 (follow list -> first player -> like -> back home) and 信箱 (claim all) pipelines.

    python tools/build_social_pipeline.py [--check]

Spec: resource/navigation/social_ui.json; samples: resource/navigation/samples/*.png.
Output: resource/pipeline/social.json and resource/image/social_*.png
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402

ROOT, NAV, IMAGE = B.ROOT, B.NAV, B.IMAGE
OUT = ROOT / "resource" / "pipeline" / "social.json"


def build():
    ui = json.loads((NAV / "social_ui.json").read_text(encoding="utf-8"))
    home = json.loads((ROOT / "resource" / "pipeline" / "navigation.json").read_text(encoding="utf-8"))
    images, nodes, rects, thr = {}, {}, {}, {}
    for t in ui["templates"]:
        sc = ui["screens"][t["screen"]]
        img = cv2.imread(str(NAV / "samples" / sc["sample"]))
        x0, y0, x1, y1 = B.scale_box(t["box"], sc["src_size"])
        images[f"social_{t['id']}.png"] = img[y0:y1, x0:x1]
        rects[t["id"]] = [x0, y0, x1 - x0, y1 - y0]
        thr[t["id"]] = t.get("threshold", 0.8)

    def match(tid, grow=14, roi=None):
        return {"recognition": "TemplateMatch", "template": f"social_{tid}.png", "roi": roi or B.grow(rects[tid], grow),
                "threshold": thr[tid], "method": 10001}

    def region(name):
        r = ui["regions"][name]
        return B.scale_box(r["box"], ui["screens"][r["screen"]]["src_size"])

    def tap(name, shrink=6):
        x0, y0, x1, y1 = region(name)
        return {"action": "Click", "target": [x0 + shrink, y0 + shrink, max(4, x1 - x0 - 2 * shrink), max(4, y1 - y0 - 2 * shrink)]}

    def focus(text):
        return {"Node.Recognition.Succeeded": text}

    # home recognised -> stop (NavHomeRouter itself would go on to click 调查)
    nodes["Soc_HomeReached"] = {**home["NavHomeRouter"], "action": "DoNothing", "next": [],
                                "focus": focus("已回到主界面。")}
    nodes["Soc_HomeReached"].pop("timeout", None)

    cx0, cy0, cx1, cy1 = B.scale_box(ui["regions"]["fixed_compass"]["box"], ui["screens"][ui["regions"]["fixed_compass"]["screen"]]["src_size"])
    for i in range(1, 7):
        # the compass can be partly clipped by the window frame (profile page + toast), so also click its fixed spot
        nodes[f"Soc_BackFixed{i}"] = {"recognition": "DirectHit", "action": "Click", "target": [cx0 + 10, cy0 + 10, cx1 - cx0 - 20, cy1 - cy0 - 20],
                                      "post_delay": 1800, "next": ["Soc_HomeReached", f"Soc_BackFixed{i + 1}"] if i < 6 else ["Soc_HomeReached"],
                                      "focus": {"Node.Action.Succeeded": f"按固定位置点击右上角罗盘返回（第 {i} 次）。"}}

    def back(prefix, page_check):
        nodes[f"{prefix}_Back"] = {**match("compass", 20), "action": "Click", "target_offset": [8, 8, -16, -16],
                                   "post_delay": 1800, "timeout": 20000,
                                   "next": ["Soc_HomeReached", f"{prefix}_Back", "Soc_BackFixed1"],
                                   "focus": {"Node.Action.Succeeded": "已点击右上角罗盘返回；重复直到识别到主界面。"}}

    # ------------------------------------------------------------------ 校友会
    nodes["Soc_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                          "next": ["Soc_ListPage", "Soc_ProfilePage", "Soc_FromHome"],
                          "focus": focus("校友会：从关注列表、守密人档案或主界面开始。")}
    nodes["Soc_FromHome"] = {**home["NavHome_social"], "next": ["Soc_ListPage"], "timeout": 20000}
    nodes["Soc_ListPage"] = {**match("al_title"), "action": "DoNothing", "timeout": 15000, "next": ["Soc_OpenFirst"],
                             "focus": focus("已进入【校友会 关注】列表。")}
    nodes["Soc_OpenFirst"] = {**match("al_title"), "box_index": 0, **tap("al_first_avatar"), "post_delay": 2200,
                              "next": ["Soc_ProfilePage"],
                              "focus": {"Node.Action.Succeeded": "已点击列表第一位玩家的头像。"}}
    nodes["Soc_ProfilePage"] = {**match("pf_title"), "action": "DoNothing", "timeout": 15000,
                                "next": ["Soc_Like", "Soc_AfterLike"],
                                "focus": focus("已进入【守密人档案】。")}
    nodes["Soc_Like"] = {"recognition": "And", "all_of": [match("pf_title"), match("pf_like", 10)], "box_index": 1,
                         "action": "Click", "target_offset": [6, 6, -12, -12], "post_delay": 1500,
                         "next": ["Soc_AfterLike"],
                         "focus": {"Node.Action.Succeeded": "已点击点赞按钮。"}}
    nodes["Soc_AfterLike"] = {"recognition": "DirectHit", "action": "DoNothing", "post_delay": 1800, "next": ["Soc_Back", "Soc_BackFixed1"],
                              "focus": focus("点赞完成（或已点过赞，按钮不是未点赞样式），准备返回主界面。")}
    back("Soc", None)
    nodes["Soc_SkipLike"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["Soc_Back"]}

    # ------------------------------------------------------------------ 信箱
    nodes["MB_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                         "next": ["MB_Page", "MB_FromHome"],
                         "focus": focus("信箱：从信箱页或主界面开始。")}
    nodes["MB_FromHome"] = {**home["NavHome_mail"], "next": ["MB_Page"], "timeout": 20000}
    nodes["MB_Page"] = {**match("mb_title"), "action": "DoNothing", "timeout": 15000, "next": ["MB_ClaimAll"],
                        "focus": focus("已进入【信箱】。")}
    nodes["MB_ClaimAll"] = {"recognition": "And", "all_of": [match("mb_title"), match("mb_claim_all", 20)], "box_index": 1,
                            "action": "Click", "target_offset": [12, 8, -24, -16], "post_delay": 2200,
                            "next": ["MB_Popup", "MB_Back"],
                            "focus": {"Node.Action.Succeeded": "已点击【全部领取】。"}}
    nodes["MB_Popup"] = {**match("mb_reward_title", 20), "action": "Click", **tap("mb_blank"), "post_delay": 1500,
                         "next": ["MB_Popup", "MB_Back"],
                         "focus": {"Node.Action.Succeeded": "已点击空白处关闭【获得物资】。"}}
    back("MB", None)
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
        print("social pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
