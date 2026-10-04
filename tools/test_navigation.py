"""Run the navigation pipeline against the real sample screenshots with MaaFramework (no game needed).

    pip install MaaFw opencv-python-headless numpy
    python tools/test_navigation.py

A fake controller serves one screenshot and records clicks/swipes. For every navigation node the test
checks that it fires on its own screen (click lands inside the expected box) and does NOT fire on the
other screens. Exit code 1 on any failure.
"""

import json
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from maa.controller import CustomController
from maa.resource import Resource
from maa.tasker import Tasker

ROOT = Path(__file__).resolve().parents[1]
NAV = ROOT / "resource" / "navigation"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402


class FakeScreen(CustomController):
    def __init__(self, image):
        super().__init__()
        self.image = image
        self.events = []

    def connect(self):
        return True

    def request_uuid(self):
        return "fake"

    def start_app(self, intent):
        return True

    def stop_app(self, intent):
        return True

    def screencap(self):
        return self.image

    def click(self, x, y):
        self.events.append(("click", x, y))
        self.on_tap(x, y)
        return True

    def swipe(self, x1, y1, x2, y2, duration):
        self.events.append(("swipe", x1, y1, x2, y2))
        return True

    def touch_down(self, contact, x, y, pressure):
        self.events.append(("down", x, y))
        self._touch = [x, y, False]
        return True

    def touch_move(self, contact, x, y, pressure):
        self.events.append(("move", x, y))
        if getattr(self, "_touch", None):
            self._touch[2] = True
        return True

    def touch_up(self, contact):
        self.events.append(("up",))
        t = getattr(self, "_touch", None)
        self._touch = None
        if t and not t[2]:
            self.events.append(("tap", t[0], t[1]))
            self.on_tap(t[0], t[1])
        elif t:
            self.events.append(("drag",))
        return True

    def on_tap(self, x, y):
        pass

    def click_key(self, keycode):
        return True

    def input_text(self, text):
        return True

    def key_down(self, keycode):
        return True

    def key_up(self, keycode):
        return True


def load_image(name):
    return cv2.imread(str(NAV / "samples" / name))


def run_node(resource, image, node, override=None, timeout=2500):
    """Run one node alone. Returns (fired, controller events)."""
    ctrl = FakeScreen(image)
    ctrl.post_connection().wait()
    tasker = Tasker()
    tasker.bind(resource, ctrl)
    ov = {node: {"next": [], "timeout": timeout, "post_delay": 0, "pre_delay": 0, "on_error": []}}
    for k, v in (override or {}).items():
        ov.setdefault(k, {}).update(v)
    job = tasker.post_task(node, ov).wait()
    detail = job.get()
    fired = bool(detail and detail.nodes and any(n.recognition and n.recognition.hit for n in detail.nodes))
    return fired, ctrl.events


def inside(events, rect, tol=3):
    x, y, w, h = rect
    clicks = [e for e in events if e[0] in ("click", "tap")]
    return any(x - tol <= c[1] <= x + w + tol and y - tol <= c[2] <= y + h + tol for c in clicks)


class FlowScreen(FakeScreen):
    """Stateful fake game: home -> (click 调查) -> chapter page -> (click centre card) -> stage list."""

    def __init__(self, screens, cfg, ui):
        super().__init__(screens["home"])
        self.screens, self.cfg, self.ui = screens, cfg, ui
        self.state = "home"
        sc = ui["screens"]["home"]["src_size"]
        b = next(b for b in ui["home_buttons"] if b["id"] == "investigate")
        x0, y0, x1, y1 = B.scale_box(b["click_box"], sc)
        self.invest = (x0, y0, x1, y1)

    def on_tap(self, x, y):
        if self.state == "home" and self.invest[0] <= x <= self.invest[2] and self.invest[1] <= y <= self.invest[3]:
            self.state, self.image = "chapters", self.screens["chapters"]
        elif self.state == "chapters":
            cx, cy, cw, ch = self.cfg["center_card_click"]
            if cx <= x <= cx + cw and cy <= y <= cy + ch:
                self.state, self.image = "stages", self.screens["stages"]


def run_flow(resource, screens, cfg, ui, override, start="home", timeout=90000):
    ctrl = FlowScreen(screens, cfg, ui)
    ctrl.state, ctrl.image = start, screens[start]
    ctrl.post_connection().wait()
    tasker = Tasker()
    tasker.bind(resource, ctrl)
    ov = {name: {"on_error": []} for name in B.build()[1]}
    for name, val in override.items():
        ov.setdefault(name, {}).update(val)
    job = tasker.post_task("NavMainEntry", ov).wait()
    detail = job.get()
    names = [n.name for n in detail.nodes] if detail and detail.nodes else []
    return ctrl, names


def main():
    images, nodes = B.build()
    ui = json.loads((NAV / "nav_ui.json").read_text(encoding="utf-8"))
    cfg = json.loads((NAV / "nav_config.json").read_text(encoding="utf-8"))
    resource = Resource()
    resource.post_bundle(str(ROOT / "resource")).wait()
    screens = {s: load_image(c["sample"]) for s, c in ui["screens"].items()}
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    # home buttons: fire on home, click inside the button, never fire on the other screens
    for b in ui["home_buttons"]:
        node = f"NavHome_{b['id']}"
        fired, ev = run_node(resource, screens["home"], node)
        sc = ui["screens"]["home"]["src_size"]
        x0, y0, x1, y1 = B.scale_box(b.get("click_box", b["box"]), sc)
        expect(fired, f"{node}: not recognised on the home screen")
        expect(fired and inside(ev, [x0, y0, x1 - x0, y1 - y0]), f"{node}: click outside the button {ev[:2]}")
        for other in ("chapters", "stages"):
            f2, _ = run_node(resource, screens[other], node)
            expect(not f2, f"{node}: false positive on the {other} screen")
    # screen detectors
    for node, screen in (("NavHomeRouter", "home"), ("NavChapterScreen", "chapters"), ("NavStageScreen", "stages")):
        for name, img in screens.items():
            fired, _ = run_node(resource, img, node)
            expect(fired == (name == screen), f"{node}: expected {'hit' if name == screen else 'miss'} on {name}, got {fired}")
    # chapter-number template: 8 is centred in the sample
    fired8, _ = run_node(resource, screens["chapters"], "NavC8_Verify")
    expect(fired8, "NavC8_Verify: chapter 8 not verified on a page where chapter 8 is centred")
    # only chapter 8 has a number template (no real screenshot of the other chapters yet): the rest skip verification
    expect("template" in nodes["NavC8_Verify"] and "template" not in nodes["NavC9_Verify"], "chapter templates changed unexpectedly")
    # actions that need no recognition
    fired, ev = run_node(resource, screens["chapters"], "NavEnterCenterCard")
    expect(fired and inside(ev, cfg["center_card_click"]), "NavEnterCenterCard: wrong click")
    fired, ev = run_node(resource, screens["chapters"], "NavToFirst_1")
    xs = [e[1] for e in ev if e[0] in ("down", "move")] + [e[3] for e in ev if e[0] == "swipe"]
    expect(len(xs) >= 2 and xs[-1] > xs[0], f"NavToFirst_1: expected a rightward drag, got {ev[:3]}")
    fired, ev = run_node(resource, screens["stages"], "NavDiff_hard")
    expect(fired and inside(ev, cfg["stage_tabs"]["hard"]), "NavDiff_hard: wrong click")
    fired, ev = run_node(resource, screens["chapters"], "NavBack")
    expect(fired, "NavBack: compass not recognised on the chapter page")
    fired, ev = run_node(resource, screens["stages"], "NavBack")
    expect(fired, "NavBack: compass not recognised on the stage page")
    # whole flow: home -> chapter page -> stage list, for several target chapters and starting pages
    for k in (1, 5, 8, 9):
        for start in ("home", "chapters"):
            ctrl, names = run_flow(resource, screens, cfg, ui, {"NavToFirstDone": {"next": [f"NavC{k}_Start"]}}, start)
            swipes = sum(1 for e in ctrl.events if e[0] == "drag")
            expect(names and names[-1] == "NavStageDone", f"flow chapter {k} from {start}: ended at {names[-3:] if names else names}")
            expect(swipes == cfg["reset_swipes"] + (k - 1), f"flow chapter {k} from {start}: {swipes} swipes, expected {cfg['reset_swipes'] + k - 1}")
            expect(ctrl.state == "stages", f"flow chapter {k} from {start}: ended in state {ctrl.state}")
    ctrl, names = run_flow(resource, screens, cfg, ui, {"NavChapterScreen": {"next": ["NavEnterCenterCard"]}}, "home")
    expect(names and names[-1] == "NavStageDone" and not any(e[0] == "drag" for e in ctrl.events), "flow without swiping (current chapter) failed")
    ctrl, names = run_flow(resource, screens, cfg, ui, {"NavStageScreen": {"next": ["NavDiff_hard"]}}, "stages")
    expect(names[-2:] == ["NavDiff_hard", "NavStageDone"], f"flow hard tab: {names[-3:]}")
    # every option case of the "主界面按钮" setting must click its own button on the home screen
    interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))
    for case in interface["option"]["主界面按钮"]["cases"]:
        b = next(b for b in ui["home_buttons"] if b["id"] == case["name"])
        ctrl, names = run_flow(resource, screens, cfg, ui, {**case["pipeline_override"], "NavHome_investigate": {"next": []}}, "home")
        x0, y0, x1, y1 = B.scale_box(b.get("click_box", b["box"]), ui["screens"]["home"]["src_size"])
        names_hit = f"NavHome_{b['id']}" in names
        expect(names_hit and inside(ctrl.events, [x0, y0, x1 - x0, y1 - y0]), f"option 主界面按钮/{b['id']}: ran {names[-3:]}, events {ctrl.events[:2]}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
