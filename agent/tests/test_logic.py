import copy
import json
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from morimens_logic import decisions, knowledge, policy, sim
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


class KnownEventRules(unittest.TestCase):
    """Every known event (resource/map_data/events.json) is wired into the event decision settings."""

    @classmethod
    def setUpClass(cls):
        cls.rules = json.loads((policy.EXPLORE_DIR / "event_rules.json").read_text(encoding="utf-8"))["rules"]
        cls.events = json.loads((policy.ROOT / "resource" / "map_data" / "events.json").read_text(encoding="utf-8"))["events"]

    def test_every_known_event_has_a_rule_entry(self):
        names = {e["event"] for e in self.events if e["event"] not in ("未知", "")}
        self.assertEqual(names, set(self.rules))
        for name, rule in self.rules.items():
            labels = {o["label"] for o in rule["options"]}
            for want in rule["prefer"] + rule["avoid"]:
                self.assertIn(want, labels, name)

    def test_rules_are_loaded_only_when_enabled(self):
        on = policy.load_policy()
        off = policy.load_policy(overrides={"event": {"use_known_rules": False}})
        self.assertTrue(policy.get(on, "event.known_rules"))
        self.assertFalse(policy.get(off, "event.known_rules"))

    def test_every_known_event_decides_with_a_valid_option(self):
        pol_on = pol()
        for name, rule in self.rules.items():
            labels = [o["label"] for o in rule["options"]]
            d = decisions.choose_event_option(pol_on, KN, name, labels, 0.9)
            self.assertTrue(0 <= d.index < len(labels), name)

    def test_preferred_option_is_chosen_without_hard_override(self):
        pol_on = pol()
        checked = 0
        for name, rule in self.rules.items():
            if rule["hard_override_in_default_policy"] or not rule["prefer"]:
                continue
            labels = [o["label"] for o in rule["options"]]
            d = decisions.choose_event_option(pol_on, KN, name, labels, 0.9)
            self.assertEqual(labels[d.index], rule["prefer"][0], f"{name}: {d.reason}")
            checked += 1
        self.assertGreater(checked, 100)

    def test_hard_override_beats_known_rule(self):
        labels = ["离开", "诈降", "闯入"]
        d = decisions.choose_event_option(pol(event={"overrides": {"监察点": {"prefer": ["闯入"]}}}), KN, "监察点", labels, 0.9)
        self.assertEqual(labels[d.index], "闯入")

    def test_user_can_turn_the_rules_off(self):
        name = next(n for n, r in self.rules.items() if r["prefer"] and not r["hard_override_in_default_policy"] and len(r["options"]) > 2)
        rule = self.rules[name]
        labels = [o["label"] for o in rule["options"]]
        flipped = [l for l in labels if l not in rule["prefer"]]
        d_on = decisions.choose_event_option(pol(), KN, name, labels, 0.9)
        self.assertIn("known event rule", d_on.ranked and [r[2] for r in d_on.ranked if r[1] == d_on.index][0])
        d_off = decisions.choose_event_option(pol(event={"use_known_rules": False}), KN, name, labels, 0.9)
        self.assertNotIn("known event rule", [r[2] for r in d_off.ranked if r[1] == d_off.index][0])
        self.assertTrue(flipped)


class ClientMaps(unittest.TestCase):
    """The game client's own maps (resource/map_data/maps_client.json) drive the route planning."""

    @classmethod
    def setUpClass(cls):
        d = policy.ROOT / "resource" / "map_data"
        cls.client = json.loads((d / "maps_client.json").read_text(encoding="utf-8"))["maps"]
        cls.aliases = json.loads((d / "client" / "aliases.json").read_text(encoding="utf-8"))["aliases"]
        cls.grid = json.loads((d / "client" / "maps.json").read_text(encoding="utf-8"))
        cls.stages = json.loads((d / "client" / "stages.json").read_text(encoding="utf-8"))

    def test_all_maps_are_imported_and_consistent(self):
        self.assertEqual(len(self.client), 1171)
        self.assertEqual(set(self.client), set(self.grid))
        for mid, m in self.client.items():
            self.assertEqual(m["tile_count"], len(m["tiles"]), mid)
            keys = {(t["island"], t["row"], t["col"]) for t in m["tiles"]}
            self.assertEqual(len(keys), len(m["tiles"]), mid)
            self.assertTrue(all((t["row"] + t["col"]) % 2 == (m["tiles"][0]["row"] + m["tiles"][0]["col"]) % 2 for t in m["tiles"]), mid)
            self.assertNotIn("wall", m["counts"], mid)
            self.assertEqual(m["counts"].get("player"), 1, mid)
        for sid, st in self.stages.items():
            for mid in st.get("m", []):
                self.assertIn(str(mid), self.client, sid)

    def test_our_maps_match_the_client_maps(self):
        good = [k for k, a in self.aliases.items() if a["score"] >= 0.6]
        self.assertGreaterEqual(len(good), 105)
        self.assertEqual(self.aliases["8-2"]["client_map"], "56507")
        self.assertEqual(KN.maps["8-2"]["client_map"], "56507")

    def test_8_2_route_follows_the_live_run(self):
        # live: the checkpoint cannot be walked through; 诈降 teleports to the 羁押点, the inquisitor is reached from there
        nav = Navigator(pol(), KN, "8-2")
        start = next(k for k, t in nav.tiles.items() if t == "player")
        dist, parent = nav._dijkstra(start, False)
        path = [nav.tiles[k] for k in nav._path(parent, nav._best(dist, nav._goal_tiles())[1])]
        self.assertIn("checkpoint", path)
        self.assertEqual(path[path.index("checkpoint") + 1], "detention")
        self.assertEqual(path[-1], "final_battle")

    def test_forced_teleport_landing_can_be_left_again(self):
        nav = Navigator(pol(), KN, "5-6")
        pairs = nav.links
        if not pairs:
            self.skipTest("no tunnel on 5-6")
        nav.teleport_forced = True
        goals = nav._goal_tiles()
        dist, parent = nav._dijkstra(next(k for k, t in nav.tiles.items() if t == "player"), False)
        self.assertTrue(nav._best(dist, goals))

    def test_door_without_key_is_never_blacklisted(self):
        nav = Navigator(pol(), KN, "5-6")
        door = next((k for k, t in nav.tiles.items() if t == "locked_door"), None)
        if door is None:
            self.skipTest("no door on 5-6")
        for _ in range(10):
            self.assertFalse(nav.mark_failed(door))
        self.assertNotIn(door, nav.blacklist)

    def test_random_variants_cost_the_mean(self):
        cell = next((m, t) for m in self.client.values() for t in m["tiles"] if t.get("alts"))
        m, t = cell
        nav = Navigator(pol(), KN, [k for k, v in KN.maps.items() if v is m or v.get("id") == m["id"]][0])
        key = (t["island"], t["row"], t["col"])
        costs = [float(KN.tile_effect(x).get("cost", 1)) for x in [t["type"], *t["alts"]]]
        mult = float(policy.get(pol(), "route.avoid").get(t["type"], 1.0))
        self.assertAlmostEqual(nav._cost(key), max(sum(costs) / len(costs), 0.1) if mult == 1.0 else nav._cost(key))

    def test_every_client_map_with_a_goal_has_a_plan(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("plan_route", policy.ROOT / "tools" / "plan_route.py")
        pr = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pr)
        maps, effects = pr.load()
        report = pr.check_all(maps, effects)
        statuses = {s: sum(1 for r in report.values() if r["status"] == s) for s in ("ok", "bridged", "unreachable", "no_goal")}
        self.assertEqual(statuses["unreachable"], 0, statuses)
        self.assertGreater(statuses["ok"], 900)
        self.assertLessEqual(statuses["bridged"], 25, statuses)

    def test_simulated_runs_on_client_maps(self):
        for mid in ("56507", "35852", "47857", "129", "314", "357"):
            r = sim.run_one(KN, mid, pol(), 1, forced_teleport=False)
            self.assertTrue(r["success"] or r["stopped"], (mid, r))
        for mid in ("314", "357", "22737", "338"):                      # these looped before the forced-teleport fixes
            r = sim.run_one(KN, mid, pol(), 0, forced_teleport=True)
            self.assertTrue(r["success"], (mid, r))


if __name__ == "__main__":
    unittest.main()


class DiveLayouts(unittest.TestCase):
    """Dive layout catalogue and layout identification from observed tiles."""

    @classmethod
    def setUpClass(cls):
        cls.d = json.loads((policy.ROOT / "resource" / "map_data" / "dive_layouts.json").read_text(encoding="utf-8"))
        cls.kn = knowledge.Knowledge()

    def test_catalogue_has_24_layouts_per_pian(self):
        self.assertEqual(self.d["count"], {"忘却篇": 24, "星辰篇": 24})
        for e in self.d["layouts"]:
            self.assertIn("1", e["difficulties"])
            self.assertIn("癫狂", e["difficulties"])

    def test_identify_map_finds_the_layout_from_a_few_tiles(self):
        e = self.d["layouts"][0]
        tiles = self.kn.maps[e["map"]]["tiles"] if e["map"] in self.kn.maps else None
        if not tiles:
            self.skipTest("map not in knowledge")
        obs = {(t["row"], t["col"]): t["type"] for t in tiles if t.get("type") not in (None, "plain")}
        found = self.kn.identify_map(obs, min_typed=3)
        self.assertTrue(found)
        hit = [f for f in found if f[1] == e["map"]]
        self.assertTrue(hit, found)
        self.assertEqual(hit[0][2], (0, 0))


class StageCatalogues(unittest.TestCase):
    """activity_stages.json / train_corridor.json / events_all.json agree with the client data."""

    @classmethod
    def setUpClass(cls):
        d = policy.ROOT / "resource" / "map_data"
        load = lambda n: json.loads((d / n).read_text(encoding="utf-8"))
        cls.acts, cls.train, cls.events = load("activity_stages.json"), load("train_corridor.json"), load("events_all.json")
        cls.stages = load("client/stages.json")

    def test_every_activity_stage_is_counted(self):
        total = sum(a["stages"] for a in self.acts["activities"])
        self.assertEqual(total, sum(1 for v in self.stages.values() if v["c"] == "活动 / 支线"))
        for a in self.acts["activities"]:
            self.assertEqual(len(a["stage_ids"]), a["stages"])

    def test_train_has_all_three_difficulties_and_chapter_pools(self):
        self.assertEqual(set(self.train["difficulties"]), {"普通", "困难", "癫狂"})
        for r in self.train["routes"].values():
            pools = [p for p in r["phases"] if p["kind"] == "chapters"]
            self.assertEqual(len(pools), 3)
            for p in pools:
                self.assertEqual(len(p["groups"]), 4)

    def test_train_events_are_listed_in_the_event_catalogue(self):
        te = self.events["train_events"]
        self.assertGreaterEqual(len(te), 12)
        self.assertEqual(self.events["counts"]["train_events"], len(te))


class MonsterIntents(unittest.TestCase):
    """Monster action intents in the game's format (monster_intents.json + intent icons)."""

    @classmethod
    def setUpClass(cls):
        from morimens_logic import intents
        cls.intents = intents

    def test_every_intent_type_has_an_icon_file(self):
        d = self.intents.load()
        for k, v in d["intents"].items():
            self.assertTrue((self.intents.ICON_DIR / f"intent_{v['icon']}.png").exists(), k)
        for s in d["skills"].values():
            self.assertIn(s["intent"], d["intents"])

    def test_rendendclaw_matches_the_wiki_page(self):
        (mid, m), = self.intents.find("撕裂维度之足")
        seqs = self.intents.sequences(m, 99)
        self.assertEqual([s["label"] for s in seqs[0][1]], ["强力削弱", "强力攻击", "攻击", "攻击"])
        self.assertEqual([s["name"] for s in seqs[0][1]][:2], ["封印", "追猎"])
        self.assertIn("886 点伤害 3 次", seqs[0][1][1]["desc"])
        self.assertIn("3036", seqs[0][1][3]["desc"])

    def test_all_actions_resolve_to_known_skills(self):
        d = self.intents.load()
        for m in d["monsters"].values():
            for sid in m["opening"] + [x for c in m["cycles"] for x in c]:
                self.assertIn(str(sid), d["skills"])

    def test_other_monsters_get_computed_values(self):
        (mid, m), = self.intents.find("提灯教牧")
        steps = dict((t, st) for t, st in self.intents.sequences(m))["首轮行动"]
        self.assertTrue(steps[0]["value"].startswith("伤害 "))
        self.assertNotIn("[Arg", steps[0]["desc"])
        self.assertEqual(self.intents.evaluate("BattleAtkForce*0.35,3", 2530), [886, 3])
        self.assertEqual(self.intents.evaluate("CmdCaster.GetStateLayer(5)+5", 100), ["层数+5"])

