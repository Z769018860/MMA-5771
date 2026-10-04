"""Generate the main-screen / chapter navigation pipeline and its templates.

    python tools/build_nav_pipeline.py            # templates -> resource/image/nav_*.png, pipeline -> resource/pipeline/navigation.json
    python tools/build_nav_pipeline.py --check    # fail if the generated files are out of date

Inputs: resource/navigation/nav_ui.json (what to recognise), nav_config.json (swipe/click geometry),
samples/*.png (real screenshots, 1280x720). Templates are cropped from the samples, so the recognised
look is exactly what the game rendered there. Chapter-number templates `nav_chapter_NN.png` are
optional: add them with tools/make_chapter_template.py; without one the chapter is not verified.
"""

import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "resource" / "navigation"
IMAGE = ROOT / "resource" / "image"
OUT = ROOT / "resource" / "pipeline" / "navigation.json"
W, H = 1280, 720


def scale_box(box, src):
    sw, sh = src
    x0, y0, x1, y1 = box
    return [round(x0 * W / sw), round(y0 * H / sh), round(x1 * W / sw), round(y1 * H / sh)]


def crop(screen_cfg, box):
    img = cv2.imread(str(NAV / "samples" / screen_cfg["sample"]))
    x0, y0, x1, y1 = scale_box(box, screen_cfg["src_size"])
    return img[y0:y1, x0:x1], [x0, y0, x1 - x0, y1 - y0]


def grow(rect, margin):
    x, y, w, h = rect
    x0, y0 = max(0, x - margin), max(0, y - margin)
    return [x0, y0, min(W, x + w + margin) - x0, min(H, y + h + margin) - y0]


def build():
    ui = json.loads((NAV / "nav_ui.json").read_text(encoding="utf-8"))
    cfg = json.loads((NAV / "nav_config.json").read_text(encoding="utf-8"))
    thr, margin = cfg["template_threshold"], cfg["roi_margin"]
    images, nodes = {}, {}
    home = ui["screens"]["home"]

    def tpl(name, screen, box):
        img, rect = crop(ui["screens"][screen], box)
        images[name] = img
        return rect

    def match(template, rect, threshold=thr):
        return {"recognition": "TemplateMatch", "template": template, "roi": grow(rect, margin),
                "threshold": threshold, "method": 10001}

    # ---------------------------------------------------------------- home screen
    marker_rects = {}
    for b in ui["home_buttons"]:
        if b["id"] in ui["home_markers"]:
            marker_rects[b["id"]] = tpl(f"nav_home_{b['id']}.png", "home", b["box"])
    for b in ui["home_buttons"]:
        if b["id"].startswith("banner_"):
            continue
        rect = tpl(f"nav_home_{b['id']}.png", "home", b["box"])
        marker_rects[b["id"]] = rect
        node = match(f"nav_home_{b['id']}.png", rect)
        if b["id"] in ui.get("small_icons", []):
            # small icons also look like parts of other pages: require the home markers as well
            node = {"recognition": "And", "all_of": [node] + [match(f"nav_home_{m}.png", marker_rects[m]) for m in ui["home_markers"]],
                    "box_index": 0}
        if "click_box" in b:
            cx0, cy0, cx1, cy1 = scale_box(b["click_box"], home["src_size"])
            node.update(action="Click", target=[cx0 + 20, cy0 + 20, cx1 - cx0 - 40, cy1 - cy0 - 40])
        else:
            node.update(action="Click", target_offset=[4, 4, -8, -8])
        node.update(post_delay=1500, next=[],
                    focus={"Node.Recognition.Succeeded": f"主界面按钮【{b['label']}】已识别。",
                           "Node.Action.Succeeded": f"已点击主界面按钮【{b['label']}】。"})
        nodes[f"NavHome_{b['id']}"] = node
    for b in ui["home_buttons"]:
        if not b["id"].startswith("banner_"):
            continue
        x0, y0, x1, y1 = scale_box(b["box"], home["src_size"])
        nodes[f"NavHome_{b['id']}"] = {
            "recognition": "And",
            "all_of": [match(f"nav_home_{m}.png", marker_rects[m]) for m in ui["home_markers"]],
            "box_index": 0, "action": "Click", "target": [x0 + 10, y0 + 10, x1 - x0 - 20, y1 - y0 - 20],
            "post_delay": 1500, "next": [],
            "focus": {"Node.Action.Succeeded": f"已点击主界面【{b['label']}】（活动内容每天变化，只按固定位置点击，不做图像识别）。"}}

    nodes["NavHomeRouter"] = {
        "recognition": "And",
        "all_of": [match(f"nav_home_{m}.png", marker_rects[m]) for m in ui["home_markers"]],
        "box_index": 0, "action": "DoNothing", "next": ["NavHome_investigate"], "timeout": 30000,
        "focus": {"Node.Recognition.Succeeded": "已识别主界面；按【主界面按钮】设置点击对应按钮。"}}
    nodes["NavHome_investigate"]["next"] = ["NavChapterScreen"]
    nodes["NavHome_investigate"]["timeout"] = 20000

    # ---------------------------------------------------------------- chapter select
    for m in ui["chapter_markers"]:
        rect = tpl(f"nav_chapters_{m['id']}.png", m["screen"], m["box"])
        m["_rect"] = rect
    title = next(m for m in ui["chapter_markers"] if m["id"] == "title")
    nodes["NavChapterScreen"] = {
        **match("nav_chapters_title.png", title["_rect"], 0.75), "action": "DoNothing", "timeout": 20000,
        "next": ["NavToFirst_1"],
        "focus": {"Node.Recognition.Succeeded": "已进入【调查行动】章节选择页。"}}
    sw = cfg["swipe"]

    def swipe(direction):
        return {"action": "Swipe", "begin": sw[direction]["begin"], "end": sw[direction]["end"],
                "duration": sw[direction]["duration"], "post_delay": sw["post_delay"]}

    n_reset = cfg["reset_swipes"]
    for i in range(1, n_reset + 1):
        nodes[f"NavToFirst_{i}"] = {"recognition": "DirectHit", **swipe("to_previous"),
                                    "next": [f"NavToFirst_{i + 1}" if i < n_reset else "NavToFirstDone"]}
    nodes["NavToFirstDone"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["NavC1_Start"],
                               "focus": {"Node.Recognition.Succeeded": "已滑到第 1 章，开始向右数到目标章节。"}}
    numeral_rect = cfg["chapter_numeral_roi"]
    for k in range(1, cfg["chapters"] + 1):
        last = "NavEnterCenterCard"
        verify = f"NavC{k}_Verify"
        template = IMAGE / f"nav_chapter_{k:02d}.png"
        if template.is_file():
            nodes[verify] = {"recognition": "TemplateMatch", "template": template.name, "roi": numeral_rect,
                             "threshold": 0.9, "method": 10001, "action": "DoNothing", "timeout": 6000,
                             "next": [last],
                             "focus": {"Node.Recognition.Succeeded": f"章节页中央的章节编号与第 {k} 章模板一致。"}}
        else:
            nodes[verify] = {"recognition": "DirectHit", "action": "DoNothing", "next": [last],
                             "focus": {"Node.Recognition.Succeeded": f"第 {k} 章没有编号模板，未验证中央章节（可用 tools/make_chapter_template.py 添加）。"}}
        steps = [f"NavC{k}_F{i}" for i in range(1, k)]
        for idx, name in enumerate(steps):
            nodes[name] = {"recognition": "DirectHit", **swipe("to_next"),
                           "next": [steps[idx + 1] if idx + 1 < len(steps) else verify]}
        nodes[f"NavC{k}_Start"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [steps[0] if steps else verify]}
    cx, cy, cw, ch = cfg["center_card_click"]
    nodes["NavEnterCenterCard"] = {"recognition": "DirectHit", "action": "Click", "target": [cx, cy, cw, ch],
                                   "post_delay": 2200, "next": ["NavStageScreen"],
                                   "focus": {"Node.Action.Succeeded": "已点击中央章节卡片，等待关卡列表。"}}

    # ---------------------------------------------------------------- stage list
    for m in ui["stage_markers"]:
        m["_rect"] = tpl(f"nav_stages_{m['id']}.png", m["screen"], m["box"])
    bar = next(m for m in ui["stage_markers"] if m["id"] == "bottom_bar")
    nodes["NavStageScreen"] = {**match("nav_stages_bottom_bar.png", bar["_rect"], 0.75), "action": "DoNothing",
                               "timeout": 20000, "next": ["NavStageDone"],
                               "focus": {"Node.Recognition.Succeeded": "已进入章节关卡列表。"}}
    for name, key in (("NavDiff_normal", "normal"), ("NavDiff_hard", "hard")):
        nodes[name] = {"recognition": "DirectHit", "action": "Click", "target": cfg["stage_tabs"][key],
                       "post_delay": 1200, "next": ["NavStageDone"]}
    nodes["NavStageDone"] = {"recognition": "DirectHit", "action": "DoNothing", "next": [],
                             "focus": {"Node.Recognition.Succeeded": "导航完成：停在关卡列表。"}}
    for name, key in (("NavStagePrevChapter", "prev"), ("NavStageNextChapter", "next")):
        nodes[name] = {"recognition": "DirectHit", "action": "Click", "target": cfg["stage_arrows"][key],
                       "post_delay": 1500, "next": ["NavStageScreen"]}
    nodes["NavStageOpenLatest"] = {"recognition": "DirectHit", "action": "DoNothing", "next": ["StoryEntryRouter"],
                                   "focus": {"Node.Recognition.Succeeded": "交给自动推剧情流程：点击最右侧最新关卡。"}}
    compass = next(m for m in ui["chapter_markers"] if m["id"] == "compass")
    nodes["NavBack"] = {**match("nav_chapters_compass.png", compass["_rect"], 0.7), "action": "Click",
                        "target_offset": [8, 8, -16, -16], "post_delay": 1500, "next": []}
    nodes["NavMainEntry"] = {"recognition": "DirectHit", "action": "DoNothing", "timeout": 30000,
                             "next": ["NavStageScreen", "NavChapterScreen", "NavHomeRouter"],
                             "focus": {"Node.Recognition.Succeeded": "导航入口：从关卡列表、章节选择页或主界面开始。"}}
    return images, nodes


def render(nodes):
    return json.dumps(nodes, ensure_ascii=False, indent=2) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    images, nodes = build()
    text = render(nodes)
    if args.check:
        stale = [] if OUT.is_file() and OUT.read_text(encoding="utf-8") == text else [str(OUT)]
        for name in images:
            path = IMAGE / name
            if not path.is_file():
                stale.append(str(path))
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("navigation pipeline is up to date")
        return
    for name, img in images.items():
        cv2.imwrite(str(IMAGE / name), img)
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(images)} templates, {len(nodes)} nodes -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
