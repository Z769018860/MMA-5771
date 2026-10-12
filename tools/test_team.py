"""Test the generic team switching (默认编队 / 本任务编队) on the real formation screenshots.

    python tools/test_team.py
"""

import json
import sys
from pathlib import Path

import cv2
from maa.resource import Resource

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nav_pipeline as B  # noqa: E402
import build_team_pipeline as TM  # noqa: E402
import test_navigation as T  # noqa: E402
from test_daily import Script, run  # noqa: E402
from team_options import TEAM_OPTIONS  # noqa: E402

UI = json.loads((B.NAV / "team_ui.json").read_text(encoding="utf-8"))
IFACE = json.loads((B.ROOT / "interface.json").read_text(encoding="utf-8"))
PIPE = {}
for f in (B.ROOT / "resource" / "pipeline").glob("*.json"):
    PIPE.update(json.loads(f.read_text(encoding="utf-8-sig")))


SLOT_Y = {  # centre of each numeral's slot in the original screenshot (dd_formation 1604x899, dive_live_formation 1600x900)
    "dd_formation": ({3: 133, 4: 233, 5: 333, 6: 433, 7: 533, 8: 633, 9: 733}, (1604, 899), 6),
    "dive_live_formation": ({8: 130, 9: 230, 10: 330, 11: 430, 12: 530, 13: 630, 14: 730}, (1600, 900), 11),
}


def slot_rect(sample, team):
    ys, (w, h), _ = SLOT_Y[sample]
    sx, sy = 1280 / w, 720 / h
    return [round(22 * sx), round((ys[team] - 30) * sy), round(62 * sx), round(60 * sy)]


def option(name, case):
    return next(c for c in IFACE["option"][name]["cases"] if c["name"] == case).get("pipeline_override", {})


def merged(*sources):
    out = {}
    for src in sources:
        for k, v in src.items():
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

    S = B.NAV / "samples"
    images = {n: cv2.imread(str(S / f"{n}.png")) for n in ("dd_formation", "star_formation", "dd_entry", "dd_list_top",
                                                          "star_difficulty", "home", "main_stages", "daily", "chapters")}
    # ---- structure: options on every task with a formation page, Fix nodes disabled by default and in the lists
    for task in IFACE["task"]:
        has = [o for o in TEAM_OPTIONS if o in task["option"]]
        expect((task["name"] in TM.TEAM_TASKS) == (len(has) == 2), f"task {task['name']}: team options {has}")
    expect(all(PIPE[f"Team{f}_Fix"]["enabled"] is False for f in TM.FAMILIES), "Fix nodes must be disabled by default")
    for fam, items in TM.LIST_PATCHES.items():
        for fname, node, before in items:
            nxt = PIPE[node]["next"]
            fixes = [f"Team{fam}_{x}" for x in TM.FIXES]
            expect(all(f in nxt for f in fixes) and (not before or nxt.index(fixes[-1]) < nxt.index(before)), f"{node}: Fix nodes not in front of {before or 'list'}: {nxt}")
    for node, fam in (("Sweep_ClearRouter", "A"), ("DD_AfterTeam", "A"), ("TR_FormationRouter", "B")):
        expect(all(f"Team{fam}_{x}" in PIPE[node]["next"] for x in TM.FIXES), f"{node} lacks the Team{fam} Fix nodes")
    for case in IFACE["option"]["同调率助战"]["cases"]:
        ov = case.get("pipeline_override")
        if ov:
            expect("TeamA_Fix" in ov["CycleStart"]["next"] and "TeamA_FixHi" in ov["EntryRouter"]["next"]
                   and ov["TeamA_Resume"]["next"] == ["StartInvestigation"], "no-assist option must carry the team handlers")
    expect(set(c["name"] for c in IFACE["option"]["默认编队"]["cases"]) == {"keep", *[f"t{n}" for n in TM.ROMAN]}, "默认编队 cases")
    expect(set(c["name"] for c in IFACE["option"]["本任务编队"]["cases"]) == {"follow", "keep", *[f"t{n}" for n in TM.ROMAN]}, "本任务编队 cases")
    # ---- recognition: the column shows the current team in the middle and three teams on each side
    images["dive_live_formation"] = cv2.imread(str(S / "dive_live_formation.png"))
    for fam in TM.FAMILIES:
        for sample, (ys, _, current) in SLOT_Y.items():
            visible = set(ys) - {current}
            for n in TM.ROMAN:
                ov = option("默认编队", f"t{n}")
                fix_hits = {}
                for node in ("Fix", "FixLo", "FixHi"):
                    fired, ev = T.run_node(resource, images[sample], f"Team{fam}_{node}", ov, timeout=300)
                    fix_hits[node] = (fired, ev)
                if n in TM.GLYPHS:
                    want = n in visible
                    expect(fix_hits["Fix"][0] == want, f"Team{fam}_Fix[t{n}] on {sample}: expected {want}, got {fix_hits['Fix'][0]}")
                    if want:
                        expect(T.inside(fix_hits["Fix"][1], slot_rect(sample, n), 2), f"Team{fam}_Fix[t{n}] must click slot of {n} on {sample}: {fix_hits['Fix'][1][:1]}")
                    expect(not fix_hits["FixLo"][0] and not fix_hits["FixHi"][0], f"Team{fam}_FixLo/Hi must be off for t{n}")
                else:
                    lower, higher = TM.VIA[n]
                    for node, nb, offset_slot in (("FixLo", lower, +1), ("FixHi", higher, -1)):
                        # the neighbour glyph must be visible and not in the last / first slot (so the offset stays in the column)
                        ys_ = ys
                        want = nb in visible and (ys_[nb] < max(ys_.values()) if offset_slot > 0 else ys_[nb] > min(ys_.values()))
                        fired, ev = fix_hits[node]
                        expect(fired == want, f"Team{fam}_{node}[t{n}] on {sample}: expected {want}, got {fired}")
                        if fired:
                            expect(T.inside(ev, slot_rect(sample, nb + offset_slot), 2), f"Team{fam}_{node}[t{n}] must click the slot of {nb + offset_slot}: {ev[:1]}")
                    expect(not fix_hits["Fix"][0], f"Team{fam}_Fix must be off for t{n}")
        ov = option("默认编队", "t4")
        for sname in ("dd_entry", "dd_list_top", "star_difficulty", "home", "main_stages", "daily", "chapters"):
            for node in ("Fix", "FixLo", "FixHi"):
                fired, _ = T.run_node(resource, images[sname], f"Team{fam}_{node}", ov, timeout=300)
                expect(not fired, f"Team{fam}_{node} must not fire on {sname}")
    # ---- flows
    formation_iv = images["dd_formation"].copy()          # looks the same; only the position of the next tap matters
    shots = {**images, "formation_iv": formation_iv, "started": cv2.imread(str(S / "star_start.png"))}
    invest = [830, 625, 360, 60]
    quick = {k: {"timeout": 1500, "on_error": []} for k in ("CycleStart", "StartInvestigation", "StoryAfterRoute", "StoryFormation",
                                                           "StoryFirstFormation", "TeamA_Fix", "TeamA_FixLo", "TeamA_FixHi", "TeamA_Resume",
                                                           "TeamB_Fix", "TeamB_FixLo", "TeamB_FixHi", "TeamB_Resume")}
    for k in ("OpenAssistPurple", "OpenAssistRed", "OpenAssist", "InvestigationWarningUnchecked", "InvestigationWarningChecked"):
        quick[k] = {"timeout": 800, "on_error": []}
    quick["StartInvestigation"]["next"] = []
    quick["StoryFormation"]["next"] = []
    no_assist = option("同调率助战", "不使用助战")
    cases = [  # (label, entry, screen, option overrides, expected taps)
        ("sync, 默认编队=IV", "CycleStart", "dd_list_top", [no_assist, option("默认编队", "t4")], ["dd_list_top", "dd_formation", "formation_iv"]),
        ("sync, 本任务编队=IV (默认 沿用)", "CycleStart", "dd_list_top", [no_assist, option("本任务编队", "t4")], ["dd_list_top", "dd_formation", "formation_iv"]),
        ("sync, 本任务编队 跟随 -> 默认 IV", "CycleStart", "dd_list_top", [no_assist, option("默认编队", "t4"), option("本任务编队", "follow")],
         ["dd_list_top", "dd_formation", "formation_iv"]),
        ("sync, 默认 IV but 本任务 沿用当前", "CycleStart", "dd_list_top", [no_assist, option("默认编队", "t4"), option("本任务编队", "keep")],
         ["dd_list_top", "dd_formation"]),
        ("sync, no team option at all", "CycleStart", "dd_list_top", [no_assist], ["dd_list_top", "dd_formation"]),
        ("story, 默认编队=IV", "StoryAfterRoute", "dd_formation", [option("默认编队", "t4")], ["dd_formation", "formation_iv"]),
        ("story, 本任务编队=IV", "StoryAfterRoute", "dd_formation", [option("本任务编队", "t4")], ["dd_formation", "formation_iv"]),
        ("story, no team option", "StoryAfterRoute", "dd_formation", [], ["dd_formation"]),
    ]
    for label, entry, screen, opts, want in cases:
        tr = {"dd_list_top": [(region_list_challenge(), "dd_formation")],
              "dd_formation": [(slot_rect("dd_formation", 4), "formation_iv"), (invest, "started")],
              "formation_iv": [(invest, "started")]}
        scr = Script(shots, tr, screen)
        # the tab click must win over the investigate click only because the Fix node runs first
        got = run(resource, scr, entry, merged(*opts, quick))
        taps = [t[0] for t in scr.taps]
        expect(taps == want or taps[:len(want)] == want, f"flow '{label}': taps {scr.taps}, nodes {got}")
    print(f"{checks} checks, {len(failures)} failures")
    for f in failures:
        print("FAIL", f)
    sys.exit(1 if failures else 0)


def region_list_challenge():
    ui = json.loads((B.NAV / "dive_ui.json").read_text(encoding="utf-8"))
    r = ui["regions"]["list_challenge"]
    x0, y0, x1, y1 = B.scale_box(r["box"], ui["screens"]["dd_list_top"]["src_size"])
    return [x0, y0, x1 - x0, y1 - y0]


if __name__ == "__main__":
    main()
