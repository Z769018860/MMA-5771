"""AUTO button logic: click only when the button is there but not lit, never loop (Story* nodes and the sync-rate nodes).

    python tools/test_auto.py

Screens: a real battle screenshot (current-battle2.png) with the real lit / gray AUTO button crops (auto_on.png,
auto_off.png) pasted in, and flat / blurred / map screens from other real screenshots.
"""

import sys
from pathlib import Path

import cv2
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

ROOT = B.ROOT
TAP = [57, 490, 20, 20]


def main():
    resource = Resource()
    resource.post_bundle(str(ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    def load(name):
        return cv2.resize(cv2.imread(str(ROOT / name)), (1280, 720))

    base = load("current-battle2.png")
    # real button crops from the device: auto_on.png (lit) / auto_off.png (gray), pasted where the button sits (0, 472)
    on, off = base.copy(), base.copy()
    for img, name in ((on, "auto_on"), (off, "auto_off")):
        img[472:472 + 59, 0:128] = cv2.imread(str(ROOT / "resource" / "image" / f"{name}.png"))
    others = {n: load(n) for n in ("current-game.png", "battle-later.png", "check2.png", "current-map.png", "next-tile.png",
                                   "after-card-detail.png", "event-after-choice.png", "lantern-selected.png")}
    images = {"on": on, "off": off, **others}
    for pre, ready, lit in (("Story", "StoryAutoControlReady", "StoryAutoAlreadyOn"), ("", "AutoControlReady", "AutoAlreadyOn")):
        for n, img in images.items():
            f, _ = T.run_node(resource, img, ready, timeout=200)
            expect(f == (n == "off"), f"{ready} on {n}: got {f}")
            f, _ = T.run_node(resource, img, lit, timeout=200)
            expect(f == (n == "on"), f"{lit} on {n}: got {f}")
        # flows: how many times is AUTO clicked?
        for label, trans, start, want_taps, want_state in (
                ("button lights up after one click", {"off": [(TAP, "on")]}, "off", 1, "on"),
                ("click has no effect: at most two clicks", {}, "off", 2, "off"),
                ("already lit: no click at all", {"on": [(TAP, "off")]}, "on", 0, "on")):
            scr = Script(images, trans, start)
            quick = {k: {"timeout": 1500, "on_error": []} for k in (pre + "AutoVerifyWait", pre + "AutoVerifyWait2", pre + "AutoRetryClick",
                                                                      pre + "AutoGiveUp", ready, lit)}
            for k in ("StoryBattleMonitor", "BattleMonitor", "BattleSpeedOne", "BattleSpeedTwo"):
                quick[k] = {"timeout": 800, "next": [], "on_error": [], "action": "DoNothing"}
            entry = pre + "HideCardsVerify"
            quick[entry] = {"next": [lit, ready]} if not pre else {"next": [pre + "HideCardsRetry", lit, ready]}
            got = run(resource, scr, entry, quick)
            expect(len(scr.taps) == want_taps and scr.state == want_state, f"{pre or 'sync'} flow '{label}': taps {scr.taps}, state {scr.state}, nodes {got}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
