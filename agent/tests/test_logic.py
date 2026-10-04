import copy
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morimens_logic import decisions, policy, sim
from morimens_logic.contract import Do, Observation, Screen, ShopItem
from morimens_logic.engine import Engine
from morimens_logic.guard import StuckGuard
from morimens_logic.knowledge import Knowledge
from morimens_logic.navigator import Navigator

KN = Knowledge()


def pol(**over):
    return policy.load_policy(overrides=over or None)


class PolicyTests(unittest.TestCase):
    def test_default_valid_and_presets(self):
        for name in ("conservative", "balanced", "greedy"):
            self.assertEqual(policy.load_policy(preset=name)["preset"], name)

    def test_validation_catches_typos_and_bad_values(self):
        errors, warnings = policy.validate({"event": {"choice_mode": "wild", "blnd": 1}, "contact": {"heal_below_hp": 2}})
        self.assertTrue(any("choice_mode" in e for e in errors))
        self.assertTrue(any("heal_below_hp" in e for e in errors))
        self.assertTrue(any("blnd" in w for w in warnings))

    def test_invalid_user_override_is_rejected(self):
        with self.assertRaises(ValueError):
            pol(shop={"mode": "everything"})

    def test_user_override_merges(self):
        p = pol(shop={"max_purchases": 1})
        self.assertEqual(p["shop"]["max_purchases"], 1)
        self.assertEqual(p["shop"]["mode"], "priority")


class EventTests(unittest.TestCase):
    def test_override_prefers_listed_option(self):
        d = decisions.choose_event_option(pol(), KN, "监察点", ["离开", "诈降", "闯入"], 0.9)
        self.assertEqual(d.index, 0)
        d = decisions.choose_event_option(pol(event={"overrides": {"监察点": {"prefer": ["诈降"]}}}), KN, "监察点", ["离开", "诈降", "闯入"], 0.9)
        self.assertEqual(d.index, 1)

    def test_required_checkpoint_surrenders(self):
        d = decisions.choose_event_option(
            pol(), KN, "监察点", ["离开", "诈降", "闯入"], 0.9, "8-2",
            required_checkpoint=True,
        )
        self.assertEqual(d.index, 1)
        self.assertEqual(decisions.choose_event_option(
            pol(), KN, "监察点", ["离开", "闯入"], 0.9, "8-2",
            required_checkpoint=True,
        ).index, 0)

    def test_8_2_checkpoint_blocks_known_route(self):
        nav = Navigator(pol(), KN, "8-2")
        self.assertTrue(nav.required_for_goal((0, 3, 2), (0, 3, 4)))
        self.assertFalse(nav.required_for_goal((0, 1, 8), (0, 0, 7)))
        self.assertFalse(nav.blacklist)

    def test_searchlight_event_is_taken_not_left(self):
        # live 8-2: the searchlight is an event whose option reveals the map; a "leave" bias must not skip it
        for title in ("探照灯", None):
            d = decisions.choose_event_option(pol(), KN, title, ["打开开关", "离开"], 0.9, "8-2")
            self.assertEqual(d.index, 0, title)

    def test_live_observations_applied(self):
        ev = {e["event"]: e for e in KN.events if e["map_id"] == "8-2"}
        opt = next(o for o in ev["监察点"]["options"] if o["label"] == "诈降")
        self.assertTrue(opt.get("live_verified"))
        self.assertIn("gain_symptom", [x["type"] for x in opt["effects"]])
        self.assertEqual(KN.maps["8-2"]["tiles"][[i for i, t in enumerate(KN.maps["8-2"]["tiles"]) if t.get("hidden_event")][0]]["hidden_event"], "监察点")

    def test_blind_choice_without_text(self):
        self.assertEqual(decisions.choose_event_option(pol(), KN, None, [None] * 3).index, 2)
        self.assertEqual(decisions.choose_event_option(pol(event={"blind_choice": "first"}), KN, None, [None] * 3).index, 0)
        self.assertEqual(decisions.choose_event_option(pol(event={"blind_choice": "middle"}), KN, None, [None] * 3).index, 1)

    def test_hp_guard_avoids_damage(self):
        ev = {"event": "测试", "options": [{"label": "硬扛", "effects": [{"type": "lose_health"}, {"type": "gain_artifact"}]},
                                            {"label": "绕开", "effects": []}]}
        kn = copy.copy(KN)
        kn.events = list(KN.events) + [ev]
        kn.by_title = dict(KN.by_title)
        kn.by_map = KN.by_map
        d_high = decisions.choose_event_option(pol(event={"weights": {"gain_artifact": 3.5}}), kn, "测试", ["硬扛", "绕开"], 0.9)
        d_low = decisions.choose_event_option(pol(event={"weights": {"gain_artifact": 3.5}}), kn, "测试", ["硬扛", "绕开"], 0.1)
        self.assertEqual(d_high.index, 0)   # 3.5-3 > 0 with healthy hp
        self.assertEqual(d_low.index, 1)    # lose_health x3 when hp is low

    def test_choice_mode_leave(self):
        d = decisions.choose_event_option(pol(event={"choice_mode": "leave"}), KN, None, ["拿走", "离开", "调查"])
        self.assertEqual(d.index, 1)

    def test_always_valid_index(self):
        rng = random.Random(1)
        for _ in range(200):
            n = rng.randint(1, 5)
            labels = [rng.choice([None, "离开", "未知选项", "闯入"]) for _ in range(n)]
            d = decisions.choose_event_option(pol(), KN, rng.choice([None, "血污之池", "乱码"]), labels, rng.choice([None, 0.1, 0.9]))
            self.assertTrue(0 <= d.index < n)


class ShopPickTests(unittest.TestCase):
    items = [ShopItem(100, name="甲"), ShopItem(50, False, name="乙"), ShopItem(30, name="丙")]

    def test_modes(self):
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "none"}), self.items, 500), [])
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "first"}), self.items, 500), [0])
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "all"}), self.items, 500), [0, 2])

    def test_unaffordable_stop(self):
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "all", "unaffordable": "stop"}), self.items, 500), [0])

    def test_reserve_and_budget(self):
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "all", "reserve_currency": 80}), self.items, 150), [2])
        self.assertEqual(decisions.choose_shop(pol(shop={"mode": "all"}), self.items, 110), [0])

    def test_priority_and_skip(self):
        p = pol(shop={"mode": "priority", "priority_names": ["丙"], "skip_names": ["甲"]})
        self.assertEqual(decisions.choose_shop(p, self.items, 500), [2])

    def test_pick_priority_avoid_position(self):
        p = pol(pick={"artifact": {"priority_names": ["金色怀表"]}})
        self.assertEqual(decisions.choose_pick(p, "artifact", ["a", "金色怀表", "c"]).index, 1)
        self.assertEqual(decisions.choose_pick(pol(), "artifact", [None] * 3).index, 1)   # position_order [1,0,2]
        p = pol(pick={"seal": {"avoid_keywords": ["诅咒"], "position_order": [0, 1]}})
        self.assertEqual(decisions.choose_pick(p, "seal", ["诅咒之印", "平凡之印"]).index, 1)
        self.assertEqual(decisions.choose_pick(pol(), "card", ["x"]).index, 0)

    def test_contact_prefers_awaken(self):
        self.assertEqual(decisions.contact_choice(pol(), 0.3)[0], "awaken")           # default: awaken even when hurt
        self.assertEqual(decisions.contact_choice(pol(), None)[0], "awaken")
        self.assertEqual(decisions.contact_choice(pol(contact={"heal_below_hp": 0.5}), 0.3)[0], "heal")
        self.assertEqual(decisions.contact_choice(pol(), 0.9, awaken_available=False)[0], "heal")
        self.assertEqual(decisions.contact_choice(pol(), 0.9, awaken_blocked=True)[0], "heal")
        self.assertEqual(policy.load_policy(preset="conservative")["contact"]["heal_below_hp"], 0.25)

    def test_awaken_order(self):
        names = [None] * 4
        self.assertEqual(decisions.choose_awaken(pol(), names).index, 0)                             # left to right
        self.assertEqual(decisions.choose_awaken(pol(), names, [False, True, True, True]).index, 1)  # skips the awakened
        self.assertEqual(decisions.choose_awaken(pol(pick={"awaken": {"order": [3, 1]}}), names).index, 2)
        self.assertEqual(decisions.choose_awaken(pol(pick={"awaken": {"order": [3, 1]}}), names, [True, True, False, True]).index, 0)
        self.assertEqual(decisions.choose_awaken(pol(pick={"awaken": {"order": [9]}}), names).index, 0)  # out of range -> left to right
        p = pol(pick={"awaken": {"priority_names": ["茉夏"], "order": [4]}})
        self.assertEqual(decisions.choose_awaken(p, ["甲", "茉夏", "丙", "丁"]).index, 1)            # names beat order
        self.assertIsNone(decisions.choose_awaken(pol(), names, [False] * 4))

    def test_engine_awakens_then_falls_back_to_heal(self):
        eng = Engine(pol(pick={"awaken": {"order": [2]}}), KN, "5-6")
        self.assertEqual(eng.step(Observation(Screen.CONTACT, hp_ratio=0.4, fingerprint="c1")).kind, Do.CHOOSE_AWAKEN)
        act = eng.step(Observation(Screen.PICK_AWAKEN, choices=[None] * 4, choice_enabled=[True] * 4, fingerprint="a1"))
        self.assertEqual((act.kind, act.arg), (Do.TAP_CHOICE, 1))
        self.assertEqual(eng.step(Observation(Screen.PICK_AWAKEN, choices=[None] * 4, choice_enabled=[True] * 4, fingerprint="a2")).kind, Do.CONFIRM)
        eng2 = Engine(pol(), KN, "5-6")
        act = eng2.step(Observation(Screen.PICK_AWAKEN, choices=[None] * 4, choice_enabled=[False] * 4, fingerprint="b1"))
        self.assertEqual(act.kind, Do.BACK)
        self.assertEqual(eng2.step(Observation(Screen.CONTACT, hp_ratio=0.9, fingerprint="b2")).kind, Do.CHOOSE_HEAL)

    def test_contact_and_defeat(self):
        self.assertEqual(decisions.defeat_choice(pol(), True)[0], "retreat")
        self.assertEqual(decisions.defeat_choice(pol(battle={"use_revive": True}), True)[0], "revive")
        self.assertEqual(decisions.defeat_choice(pol(battle={"use_revive": True}), False)[0], "retreat")


class GuardTests(unittest.TestCase):
    def test_escalation_levels(self):
        g = StuckGuard(pol())
        obs = Observation(Screen.UNKNOWN, fingerprint="x")
        levels = [g.observe(obs) for _ in range(20)]
        self.assertEqual(levels[0], 0)
        self.assertIn(1, levels)
        self.assertIn(2, levels)
        self.assertIn(3, levels)
        self.assertEqual(levels[-1], 4)
        self.assertEqual(levels, sorted(levels))

    def test_progress_resets(self):
        g = StuckGuard(pol())
        for i in range(30):
            self.assertEqual(g.observe(Observation(Screen.MAP, fingerprint=str(i))), 0)


class EngineTests(unittest.TestCase):
    def test_never_loops_forever_on_frozen_screen(self):
        for screen in Screen:
            eng = Engine(pol(), KN, "5-6")
            obs = Observation(screen, fingerprint="frozen", options=[None, None], choices=[None] * 3,
                              shop_items=[ShopItem(10)], candidates=[((0, 0, 2), "plain")], player=(0, 0, 0))
            stopped = False
            for _ in range(60):
                if eng.step(obs).kind == Do.STOP:
                    stopped = True
                    break
            self.assertTrue(stopped, f"engine did not give up on frozen {screen}")

    def test_every_screen_yields_an_action(self):
        eng = Engine(pol(), KN, "5-6")
        for screen in Screen:
            obs = Observation(screen, options=["离开"], choices=[None], shop_items=[ShopItem(5)], player=(0, 0, 0), fingerprint=screen.value)
            self.assertIsNotNone(eng.step(obs).kind)

    def test_defeat_changes_event_option(self):
        eng = Engine(pol(), KN, "5-6")
        eng.cur_tile = (0, 9, 9)
        first = eng.step(Observation(Screen.EVENT, options=[None] * 3, fingerprint="e1")).arg
        eng.step(Observation(Screen.DEFEAT, fingerprint="d1"))
        second = eng.step(Observation(Screen.EVENT, options=[None] * 3, fingerprint="e2")).arg
        self.assertNotEqual(first, second)

    def test_simulated_runs_complete(self):
        for mid in ("5-6", "5-11", "一步之遥02", "8-2", "9-1", "7-6"):
            for preset in ("conservative", "balanced", "greedy"):
                r = sim.run_one(KN, mid, policy.load_policy(preset=preset), 7, forced_teleport=False)
                self.assertTrue(r["success"], (mid, preset, r))

    def test_simulated_runs_without_text_or_map_id(self):
        for mid in ("5-6", "8-2", "2-8"):
            r = sim.run_one(KN, mid, pol(), 3, text_visible=False, known_map=False, forced_teleport=False)
            self.assertTrue(r["success"] or r["stopped"], (mid, r))   # may give up, must never hang


if __name__ == "__main__":
    unittest.main()
