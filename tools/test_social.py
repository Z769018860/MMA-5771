"""Test the 校友会 / 信箱 pipelines against real sample screenshots (MaaFramework, no game needed).

    python tools/test_social.py
"""

import json
import sys
from pathlib import Path

import cv2
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402
import build_social_pipeline as S  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402

UI = json.loads((B.NAV / "social_ui.json").read_text(encoding="utf-8"))
HOME_UI = json.loads((B.NAV / "nav_ui.json").read_text(encoding="utf-8"))


def rect_of(items, key, id_):
    t = next(t for t in items[key] if t["id"] == id_)
    return t


def region(name):
    r = UI["regions"][name]
    x0, y0, x1, y1 = B.scale_box(r["box"], UI["screens"][r["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def tbox(tid):
    t = rect_of(UI, "templates", tid)
    x0, y0, x1, y1 = B.scale_box(t["box"], UI["screens"][t["screen"]]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def home_btn(bid):
    b = next(b for b in HOME_UI["home_buttons"] if b["id"] == bid)
    x0, y0, x1, y1 = B.scale_box(b["box"], HOME_UI["screens"]["home"]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


def main():
    resource = Resource()
    resource.post_bundle(str(B.ROOT / "resource")).wait()
    failures, checks = [], 0

    def expect(ok, text):
        nonlocal checks
        checks += 1
        if not ok:
            failures.append(text)

    names = ["home", "alumni_list", "profile", "profile_liked", "mailbox", "mail_reward", "daily", "interlude"]
    images = {n: cv2.imread(str(B.NAV / "samples" / f"{n}.png")) for n in names}
    matrix = {
        "Soc_ListPage": {"alumni_list"}, "Soc_OpenFirst": {"alumni_list"}, "Soc_ProfilePage": {"profile", "profile_liked"},
        "Soc_Like": {"profile"}, "MB_Page": {"mailbox"}, "MB_ClaimAll": {"mailbox"}, "MB_Popup": {"mail_reward"},
        "Soc_HomeReached": {"home"}, "Soc_Back": {"alumni_list", "profile", "mailbox", "daily", "interlude"},
    }
    for node, hits in matrix.items():
        for n in names:
            fired, _ = T.run_node(resource, images[n], node)
            want = n in hits
            if node == "Soc_Back" and n in ("daily", "interlude", "profile_liked"):
                continue                    # compass looks the same on every page: that is intended, not asserted
            expect(fired == want, f"{node} on {n}: expected {'hit' if want else 'miss'}, got {fired}")
    for node, screen, target in (("Soc_OpenFirst", "alumni_list", region("al_first_avatar")), ("Soc_Like", "profile", tbox("pf_like")),
                                 ("MB_ClaimAll", "mailbox", tbox("mb_claim_all")), ("MB_Popup", "mail_reward", region("mb_blank")),
                                 ("Soc_Back", "profile", tbox("compass"))):
        fired, ev = T.run_node(resource, images[screen], node)
        expect(fired and T.inside(ev, target, 12), f"{node}: click outside target {ev[:2]}")
    # whole flows -------------------------------------------------------------------------------
    in_rect = lambda t, r: r[0] - 4 <= t[1] <= r[0] + r[2] + 4 and r[1] - 4 <= t[2] <= r[1] + r[3] + 4
    compass = tbox("compass")
    tr = {"home": [(home_btn("social"), "alumni_list")], "alumni_list": [(region("al_first_avatar"), "profile")],
          "profile": [(tbox("pf_like"), "profile_liked")], "profile_liked": [(compass, "alumni_list2")],
          "alumni_list2": [(compass, "home")], "home": [(home_btn("social"), "alumni_list")]}
    images["alumni_list2"] = images["alumni_list"]
    scr = Script(images, tr, "home")
    got = run(resource, scr, "Soc_Start")
    expect(got and got[-1] == "Soc_HomeReached" and scr.state == "home", f"flow 校友会 from home: {got[-4:]} state {scr.state}")
    order = [t[0] for t in scr.taps]
    expect(order[:3] == ["home", "alumni_list", "profile"] and "profile_liked" in order, f"flow 校友会 tap order {order}")
    # already liked (button not in unliked style) -> no like click, still returns home
    tr2 = {"profile_liked": [(compass, "alumni_list2")], "alumni_list2": [(compass, "home")]}
    scr = Script(images, tr2, "profile_liked")
    got = run(resource, scr, "Soc_Start")
    expect(got[-1] == "Soc_HomeReached" and scr.state == "home" and "Soc_Like" not in got, f"flow already liked: {got[-4:]} {scr.state}")
    # mailbox
    tr3 = {"home": [(home_btn("mail"), "mailbox")], "mailbox": [(tbox("mb_claim_all"), "mail_reward")],
           "mail_reward": [(region("mb_blank"), "mailbox2")], "mailbox2": [(compass, "home")]}
    images["mailbox2"] = images["mailbox"]
    scr = Script(images, tr3, "home")
    got = run(resource, scr, "MB_Start")
    expect(got and got[-1] == "Soc_HomeReached" and scr.state == "home", f"flow 信箱 from home: {got[-4:]} state {scr.state}")
    expect(any(t[0] == "mailbox" and in_rect(t, tbox("mb_claim_all")) for t in scr.taps), "flow 信箱: 全部领取 not clicked")
    expect(any(t[0] == "mail_reward" for t in scr.taps), "flow 信箱: reward popup not dismissed")
    # the popup needs two taps to close -> still ends at home
    tr4 = {"mailbox": [(tbox("mb_claim_all"), "mail_reward")], "mail_reward": [(region("mb_blank"), "mail_reward_b")],
           "mail_reward_b": [(region("mb_blank"), "mailbox2")], "mailbox2": [(compass, "home")]}
    images["mail_reward_b"] = images["mail_reward"]
    scr = Script(images, tr4, "mailbox")
    got = run(resource, scr, "MB_Start")
    expect(got[-1] == "Soc_HomeReached" and scr.state == "home", f"flow 信箱 popup closes on 2nd tap: {got[-4:]} {scr.state}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
