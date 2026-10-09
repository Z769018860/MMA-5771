"""Test the 密境课室 / 幕间演习 pipeline against the real sample screenshots (MaaFramework, no game needed).

    python tools/test_daily.py
"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np
from maa.resource import Resource
from maa.tasker import Tasker

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_daily_pipeline as D  # noqa: E402
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402

NAV = B.NAV
UI = json.loads((NAV / "daily_ui.json").read_text(encoding="utf-8"))


def region(name):
    r = UI["regions"][name]
    x0, y0, x1, y1 = B.scale_box(r["box"], UI["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def tbox(tid):
    t = next(t for t in UI["templates"] if t["id"] == tid)
    x0, y0, x1, y1 = B.scale_box(t["box"], UI["screens"][t["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def img(name):
    return cv2.imdecode(np.fromfile(NAV / "samples" / f"{name}.png", dtype=np.uint8), cv2.IMREAD_COLOR)


class Script(T.FakeScreen):
    """Stateful fake: transitions[(state)] = list of (rect or None, new_state); None = any tap."""

    def __init__(self, images, transitions, start):
        super().__init__(images[start])
        self.images, self.transitions, self.state = images, transitions, start
        self.taps = []

    def on_tap(self, x, y):
        self.taps.append((self.state, x, y))
        for rect, new in self.transitions.get(self.state, []):
            if rect is None or (rect[0] - 2 <= x <= rect[0] + rect[2] + 2 and rect[1] - 2 <= y <= rect[1] + rect[3] + 2):
                self.state, self.image = new, self.images[new]
                return


def run(resource, script, entry, override=None):
    script.post_connection().wait()
    tasker = Tasker()
    tasker.bind(resource, script)
    ov = {}
    for f in (B.ROOT / "resource" / "pipeline").glob("*.json"):       # no diagnostic export (powershell) in tests
        ov.update({n: {"on_error": []} for n in json.loads(f.read_text(encoding="utf-8-sig"))})
    for k, v in (override or {}).items():
        ov.setdefault(k, {}).update(v)
    job = tasker.post_task(entry, ov).wait()
    detail = job.get()
    return [n.name for n in detail.nodes] if detail and detail.nodes else []


def main():
    resource = Resource()
    resource.post_bundle(str(B.ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    names = ["daily", "daily_claimed", "weekly", "interlude", "reward", "report"]
    images = {n: img(n) for n in names}
    # --- recognition matrix: node -> screens where it must (not) fire
    matrix = {
        "CR_PageDaily": {"daily", "daily_claimed"},
        "CR_PageWeekly": {"weekly"},
        "CR_D_Claim": {"daily"},
        "CR_W_Claim": {"daily"},
        "CR_D_Popup": {"reward"},
        "IL_Page": {"interlude"},
        "IL_OneClick": {"interlude"},
        "IL_Popup": {"reward"},
        "IL_Report": {"report"},
        "IL_ReportAgain": {"report"},
        "IL_ReportClose": {"report"},
    }
    for node, hits in matrix.items():
        for n in names:
            fired, ev = T.run_node(resource, images[n], node)
            expect(fired == (n in hits), f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    # --- click positions
    for node, screen, rect in (("CR_D_Claim", "daily", [1596, 174, 1788, 228]), ("IL_ReportAgain", "report", None),
                               ("IL_ReportClose", "report", None), ("IL_OneClick", "interlude", None),
                               ("CR_D_Popup", "reward", None)):
        fired, ev = T.run_node(resource, images[screen], node)
        target = {"CR_D_Claim": tbox("cr_claim"), "IL_ReportAgain": tbox("report_again"), "IL_ReportClose": tbox("report_close"),
                  "IL_OneClick": region("il_oneclick"), "CR_D_Popup": region("reward_blank")}[node]
        expect(fired and T.inside(ev, target), f"{node}: click outside its target {ev[:2]}")
    # --- flows
    gifts = [region(f"gift_{i}") for i in range(1, 5)]
    claim = tbox("cr_claim")
    tr = {"daily": [(claim, "reward")], "reward": [(None, "daily_claimed")],
          "daily_claimed": [(region("tab_weekly"), "weekly")], "weekly": []}
    scr = Script(images, tr, "daily")
    got = run(resource, scr, "CR_Start")
    expect(got and got[-1] == "CR_Done", f"flow daily+weekly: ended at {got[-3:]}")
    taps = [(s, x, y) for s, x, y in scr.taps]
    in_rect = lambda t, r: r[0] - 3 <= t[1] <= r[0] + r[2] + 3 and r[1] - 3 <= t[2] <= r[1] + r[3] + 3
    expect(any(in_rect(t, claim) and t[0] == "daily" for t in taps), "flow: the 领取 button was not clicked")
    expect(any(t[0] == "reward" for t in taps), "flow: reward popup was not dismissed")
    for g in gifts:
        expect(sum(in_rect(t, g) for t in taps) >= 2, f"flow: gift node {g} not clicked on both pages")
    expect(any(t[0] == "daily_claimed" and in_rect(t, region("tab_weekly")) for t in taps), "flow: weekly tab not clicked")
    # daily only / skip nodes
    scr = Script(images, tr, "daily")
    got = run(resource, scr, "CR_Start", {"CR_D_End": {"next": ["CR_Done"]}, "CR_D_Nodes": {"next": ["CR_D_End"]}})
    expect(got[-1] == "CR_Done" and not any(in_rect(t, g) for t in scr.taps for g in gifts) and scr.state != "weekly",
           f"flow daily only without nodes: {got[-3:]}, state {scr.state}")
    scr = Script(images, {"weekly": []}, "weekly")
    got = run(resource, scr, "CR_Start")
    expect(got[-1] == "CR_Done" and sum(in_rect(t, g) for t in scr.taps for g in gifts) >= 4, f"flow weekly start: {got[-3:]}")
    # weekly only, starting from the daily page: click the weekly tab first
    tr2 = {"daily": [(region("tab_weekly"), "weekly")], "weekly": []}
    scr = Script(images, tr2, "daily")
    got = run(resource, scr, "CR_Start", {"CR_Start": {"next": ["CR_PageWeekly", "CR_ToWeekly", "CR_FromHome"]}})
    expect(got[-1] == "CR_Done" and scr.state == "weekly" and not any(s == "daily" and in_rect((s, x, y), claim) for s, x, y in scr.taps),
           f"flow weekly only from daily page: {got[-3:]} state {scr.state}")
    # interlude
    tr = {"interlude": [(region("il_oneclick"), "reward")], "reward": [(None, "report")],
          "report": [(tbox("report_again"), "interlude_end")], "interlude_end": []}
    images["interlude_end"] = images["weekly"]          # any non-matching page after re-dispatch
    scr = Script(images, tr, "interlude")
    got = run(resource, scr, "IL_Start")
    expect(got and got[-1] == "IL_Done" and "IL_ReportAgain" in got and scr.state == "interlude_end", f"flow interlude re-dispatch: {got[-4:]} state {scr.state}")
    tr["report"] = [(tbox("report_close"), "interlude_end")]
    scr = Script(images, tr, "interlude")
    got = run(resource, scr, "IL_Start", {"IL_Report": {"next": ["IL_ReportClose"]}})
    expect(got and got[-1] == "IL_Done" and "IL_ReportClose" in got, f"flow interlude close: {got[-4:]}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
