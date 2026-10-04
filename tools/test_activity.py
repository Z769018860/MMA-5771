"""Test the generic activity entry for the sync-rate loop on real screenshots (MaaFramework, no game needed).

    python tools/test_activity.py
"""

import json
import sys
from pathlib import Path

import cv2
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_activity_pipeline as A  # noqa: E402
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "activity_ui.json").read_text(encoding="utf-8"))
INTERFACE = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))


def entry_box(side):
    e = UI["entries"][side]
    x0, y0, x1, y1 = B.scale_box(e["box"], UI["screens"][e["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def slot_box(i):
    sc = UI["screens"][UI["slots"]["screen"]]["src_size"]
    return [UI["slots"]["x"] * 1280 / sc[0] - 12, UI["slots"]["y"][i - 1] * 720 / sc[1] - 12, 24, 24]


def node_box(i):
    sc = UI["screens"][UI["nodes"]["screen"]]["src_size"]
    return [UI["nodes"]["x"][i - 1] * 1280 / sc[0] - 30, UI["nodes"]["y"] * 720 / sc[1] - 30, 60, 60]


def option_override(name, case):
    c = next(c for c in INTERFACE["option"][name]["cases"] if c["name"] == case)
    return c.get("pipeline_override", {})


def merge(*ovs):
    out = {}
    for ov in ovs:
        for k, v in ov.items():
            out.setdefault(k, {}).update(v)
    return out


def main():
    resource = Resource()
    resource.post_bundle(str(B.ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    names = ["home", "activity", "activity_stage", "daily", "interlude", "chapters", "stages", "mailbox", "profile"]
    images = {n: cv2.imread(str(B.NAV / "samples" / f"{n}.png")) for n in names}
    # recognition matrix
    for node, hits in {"ActivityScreen": {"activity"}, "ActEntry": {"activity"}, "ActStagePage": {"activity_stage"},
                       "ActNode1": {"activity_stage"}, "ActNode3": {"activity_stage"}, "HomeScreen": {"home"}}.items():
        for n in names:
            fired, _ = T.run_node(resource, images[n], node)
            expect(fired == (n in hits), f"{node} on {n}: expected {'hit' if n in hits else 'miss'}, got {fired}")
    # click positions
    fired, ev = T.run_node(resource, images["activity"], "ActEntry")
    expect(fired and T.inside(ev, entry_box("right"), 4), f"ActEntry default click {ev[:2]}")
    fired, ev = T.run_node(resource, images["activity"], "ActEntry", option_override("活动玩法入口", "left"))
    expect(fired and T.inside(ev, entry_box("left"), 4), f"ActEntry left click {ev[:2]}")
    for i in range(1, 6):
        fired, ev = T.run_node(resource, images["activity_stage"], f"ActNode{i}")
        expect(fired and T.inside(ev, node_box(i), 4), f"ActNode{i} click {ev[:2]}")
    for i in range(1, 9):
        fired, ev = T.run_node(resource, images["activity"], f"ActSlot{i}")
        expect(fired and T.inside(ev, slot_box(i), 4), f"ActSlot{i} click {ev[:2]}")
    # full flows: home -> activity -> entry -> stage -> node
    home_rect = next(b for b in json.loads((B.NAV / "nav_ui.json").read_text(encoding="utf-8"))["home_buttons"] if b["id"] == "banner_event")
    hx0, hy0, hx1, hy1 = B.scale_box(home_rect["box"], [1596, 898])
    banner = [hx0, hy0, hx1 - hx0, hy1 - hy0]
    for entry in ("right", "left"):
        for node in (1, 3):
            for slot in ("keep", "slot2"):
                tr = {"home": [(banner, "activity")], "activity": [(entry_box(entry), "activity_stage")],
                      "activity_stage": [(node_box(node), "detail")], "detail": []}
                images["detail"] = images["profile"]            # any page the router does not know
                if slot != "keep":
                    tr["activity"] = [(slot_box(2), "activity")] + tr["activity"]
                scr = Script(images, tr, "home")
                ov = merge(option_override("活动玩法入口", entry), option_override("活动关卡节点", f"node{node}"),
                           option_override("活动列表项", slot), {"HomeScreen": {"target": [banner[0] + 20, banner[1] + 20, 20, 20]}},
                           {"ActNode1": {"next": []}, "ActNodeRetry1": {"next": []}, "ActNodeRetry3": {"next": []},
                            "ActNode3": {"next": []}, **{k: {"timeout": 1500} for k in ("CycleStart", "ChooseFeather", "ChooseMadness", "OpenAssist")}})
                got = run(resource, scr, "EntryRouter", ov)
                order = [t[0] for t in scr.taps]
                ok = scr.state == "detail" and order[:1] == ["home"] and "activity_stage" in order
                if slot != "keep":
                    ok = ok and order.count("activity") == 2
                expect(ok, f"flow entry={entry} node={node} slot={slot}: state {scr.state}, taps {order}, nodes {got[-4:]}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
