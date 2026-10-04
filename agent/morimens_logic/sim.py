"""Mock game for exercising the engine on the real maps without the game.

Assumptions (NOT verified in the real game; they only make the engine hit every code path):
  * stepping on battle/elite/final starts a battle; event/red_flesh/inquisitor open events whose options
    come from events.json; contact = heal/awaken; meltmark = shop; blackseal = seal pick; enrollment = card pick
  * tunnel/oneway teleport; rusty_key gives a key that opens every locked_door; others show a popup
Fault injection: ignored taps, unrecognised frames, random popups, failed localisation.

    python -m morimens_logic.sim --maps all --presets conservative,balanced,greedy --seeds 3
"""

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict

from .contract import Do, Observation, Screen, ShopItem
from .engine import Engine
from .knowledge import Knowledge
from .navigator import NEIGH
from .policy import load_policy


class MockGame:
    def __init__(self, kn, map_id, rng, noise=None, text_visible=True, known_map=True, forced_teleport=True):
        self.kn, self.map_id, self.rng = kn, map_id, rng
        self.noise = {"ignore": 0.08, "unknown": 0.04, "popup": 0.05, "no_pos": 0.10}
        self.noise.update(noise or {})
        self.text_visible, self.known_map = text_visible, known_map
        self.forced_teleport = forced_teleport
        entry = kn.maps[map_id]
        self.tiles = {(t["island"], t["row"], t["col"]): t["type"] for t in entry["tiles"]}
        players = sorted(k for k, t in self.tiles.items() if t == "player")
        self.pos = players[0]
        self.start = self.pos
        by = defaultdict(list)
        for k, t in self.tiles.items():
            by[t].append(k)
        self.links = {}
        tun = sorted(by["tunnel"])
        if len(tun) == 2:
            self.links[tun[0]], self.links[tun[1]] = tun[1], tun[0]
        if len(by["oneway_in"]) == 1 and len(by["secret_exit"]) == 1:
            self.links[by["oneway_in"][0]] = by["secret_exit"][0]
        self.hp, self.currency, self.has_key = 1.0, 120, False
        self.visited = {self.pos}
        self.screen, self.data = Screen.MAP, {}
        self.events = list(kn.by_map.get(map_id, []))
        rng.shuffle(self.events)
        self.reverts = 1
        self.success, self.failed, self.actions, self.tile_hist = False, False, 0, []
        self.pending_unknown = self.pending_popup = False
        self.after_popup = None
        self.stats = Counter()

    # ------------------------------------------------------------------ observation
    def _fingerprint(self):
        raw = repr((self.screen.value, self.pos, sorted(self.data.items(), key=lambda kv: kv[0]) if self.data else None,
                    len(self.visited), round(self.hp, 2), self.has_key))
        return hashlib.md5(raw.encode()).hexdigest()[:12]

    def observe(self):
        if self.pending_unknown:
            self.pending_unknown = False
            return Observation(Screen.UNKNOWN, fingerprint="unknown-frame")
        if self.pending_popup and self.screen != Screen.POPUP:
            self.pending_popup = False
            self.after_popup = (self.screen, self.data)
            self.screen, self.data = Screen.POPUP, {"popup": True}
        obs = Observation(self.screen, hp_ratio=round(max(self.hp, 0), 2), currency=self.currency,
                          fingerprint=self._fingerprint(), revive_available=self.reverts > 0)
        if self.known_map:
            obs.map_id = self.map_id
        if self.screen == Screen.MAP:
            obs.player = None if self.rng.random() < self.noise["no_pos"] else self.pos
            obs.candidates = [(k, self.tiles[k] if (self.known_map or k in self.visited or self.rng.random() < .5) else None)
                              for k in self._neigh(self.pos) if self.tiles.get(k) != "cracked_rock_blocked"]
            if self.rng.random() < self.noise["no_pos"]:
                obs.fingerprint = self._fingerprint()
        elif self.screen == Screen.EVENT:
            ev = self.data["event"]
            obs.event_title = ev["event"] if self.text_visible else None
            obs.options = [o["label"] for o in ev["options"]] if self.text_visible else [None] * len(ev["options"])
        elif self.screen == Screen.SHOP:
            obs.shop_items = [ShopItem(price=p, affordable=(p <= self.currency), sold=s) for p, s in self.data["items"]]
        elif self.screen in (Screen.PICK_ARTIFACT, Screen.PICK_SEAL, Screen.PICK_CARD):
            obs.choices = ["选项%d" % i if self.text_visible else None for i in range(3)]
        return obs

    def _neigh(self, pos):
        out = [(pos[0], pos[1] + dr, pos[2] + dc) for dr, dc in NEIGH]
        out = [k for k in out if k in self.tiles]
        if not self.forced_teleport and pos in self.links:
            out.append(self.links[pos])   # optional teleport: tap the partner from the entry tile
        return out

    # ------------------------------------------------------------------ actions
    def act(self, action):
        self.actions += 1
        if self.rng.random() < self.noise["ignore"]:
            self.stats["ignored_tap"] += 1
            return
        k, scr = action.kind, self.screen
        if self.screen == Screen.POPUP:
            if k in (Do.CLOSE_POPUP, Do.TAP_BLANK, Do.BACK):
                self.screen, self.data = self.after_popup or (Screen.MAP, {})
                self.after_popup = None
            return
        if k == Do.WAIT:
            if scr == Screen.BATTLE:
                self.data["ticks"] = self.data.get("ticks", 0) + 1
                if self.data["ticks"] >= self.data["len"]:
                    self._battle_done()
            return
        if scr == Screen.MAP and k == Do.TAP_TILE:
            self._enter(action.arg)
        elif scr == Screen.EVENT and k == Do.TAP_OPTION:
            self._option(action.arg)
        elif scr == Screen.SHOP:
            if k == Do.TAP_ITEM:
                items = self.data["items"]
                i = action.arg
                if 0 <= i < len(items) and not items[i][1] and items[i][0] <= self.currency:
                    self.currency -= items[i][0]
                    items[i] = (items[i][0], True)
                    self.stats["purchases"] += 1
            elif k in (Do.LEAVE, Do.BACK):
                self._back_to_map()
        elif scr in (Screen.PICK_ARTIFACT, Screen.PICK_SEAL, Screen.PICK_CARD):
            if k == Do.TAP_CHOICE:
                self.data["picked"] = action.arg
            elif k == Do.CONFIRM and "picked" in self.data:
                self.stats["picks"] += 1
                self._back_to_map()
        elif scr == Screen.CONTACT and k in (Do.CHOOSE_HEAL, Do.CHOOSE_AWAKEN):
            self.hp = min(1.0, self.hp + (0.4 if k == Do.CHOOSE_HEAL else 0.0))
            self._back_to_map()
        elif scr == Screen.FORMATION and k == Do.START_BATTLE:
            self.screen, self.data = Screen.BATTLE, {"len": self.rng.randint(2, 6), "tile": self.data["tile"]}
        elif scr == Screen.DEFEAT:
            if k == Do.REVIVE and self.reverts > 0:
                self.reverts -= 1
                self.hp = 0.5
                self._win_battle()
            elif k == Do.RETREAT:
                self.pos = self.data["from"]
                self.hp = max(self.hp, 0.3)
                self.visited.discard(self.data["tile"])
                self._back_to_map()
        elif scr == Screen.DIALOGUE and k in (Do.SKIP, Do.TAP_BLANK):
            self.data["lines"] -= 1
            if self.data["lines"] <= 0:
                self._back_to_map()
        elif scr == Screen.RESULT and k == Do.FINISH:
            self.success = True
        if self.rng.random() < self.noise["unknown"]:
            self.pending_unknown = True
        if self.rng.random() < self.noise["popup"] and self.screen == Screen.MAP:
            self.pending_popup = True

    def _back_to_map(self):
        self.screen, self.data = Screen.MAP, {}

    def _enter(self, tile):
        if tile not in self._neigh(self.pos):
            self.stats["bad_tap"] += 1
            return
        ty = self.tiles[tile]
        if ty == "locked_door" and not self.has_key:
            self.stats["door_blocked"] += 1
            return
        prev = self.pos
        self.pos = tile
        self.tile_hist.append(tile)
        first = tile not in self.visited
        self.visited.add(tile)
        if tile in self.links and self.forced_teleport:
            self.pos = self.links[tile]
            self.visited.add(self.pos)
            return
        if not first:
            return
        if ty == "rusty_key":
            self.has_key = True
        if ty in ("battle", "elite", "final_battle"):
            self.screen, self.data = Screen.FORMATION, {"tile": tile, "from": prev}
        elif ty in ("event", "red_flesh", "inquisitor", "mother_of_brood", "unfinished_statue"):
            self._open_event(ty)
        elif ty == "contact":
            self.screen, self.data = Screen.CONTACT, {}
        elif ty == "meltmark":
            self.screen, self.data = Screen.SHOP, {"items": [(self.rng.choice([30, 60, 90]), False) for _ in range(3)]}
        elif ty == "blackseal":
            self.screen, self.data = Screen.PICK_SEAL, {}
        elif ty == "enrollment":
            self.screen, self.data = Screen.PICK_CARD, {}
        elif ty == "story":
            self.screen, self.data = Screen.DIALOGUE, {"lines": self.rng.randint(1, 4)}
        elif ty in ("illusion", "purple_rift"):
            self.hp -= 0.05
        elif ty in ("extract", "detention", "kind_gift", "honey_wine", "strange_cyst", "proxy_rite", "white_sail", "inquisitor"):
            self.pending_popup = True

    def _open_event(self, ty):
        name = {"red_flesh": "血污之池", "inquisitor": "监察点"}.get(ty)
        ev = None
        if name:
            ev = next((e for e in self.kn.events if e["event"] == name), None)
        elif self.events:
            ev = self.events.pop()
        if ev is None:
            ev = {"event": "未知事件", "options": [{"label": "离开", "effects": []}, {"label": "探索", "effects": []}]}
        self.screen, self.data = Screen.EVENT, {"event": ev}

    def _option(self, idx):
        ev = self.data["event"]
        if not 0 <= idx < len(ev["options"]):
            return
        self.stats["events"] += 1
        opt = ev["options"][idx]
        effects = opt["effects"] or ([{"type": self.rng.choice(["heal", "lose_health", "gain_blackseal", "none"])}]
                                     if "离开" not in opt["label"] else [])
        nxt = (Screen.MAP, {})
        for e in effects:
            t = e["type"]
            if t == "heal":
                self.hp = min(1.0, self.hp + 0.25)
            elif t == "lose_health":
                self.hp -= 0.2
            elif t == "gain_symptom":
                self.hp -= 0.05
            elif t == "teleport":
                safe = [k for k, t in self.tiles.items() if t in ("plain", "cracked_rock", "contact", "searchlight")]
                self.pos = self.rng.choice(safe or [self.start])
                self.visited.add(self.pos)
            elif t == "gain_artifact":
                nxt = (Screen.PICK_ARTIFACT, {})
            elif t == "gain_blackseal":
                self.pending_popup = True
        if self.hp <= 0:
            self.screen, self.data = Screen.DEFEAT, {"from": self.pos, "tile": self.pos}
            self.hp = 0.0
        else:
            self.screen, self.data = nxt

    def _battle_done(self):
        tile = self.data["tile"]
        ty = self.tiles[tile]
        loss = {"battle": 0.12, "elite": 0.3, "final_battle": 0.25}[ty] * self.rng.uniform(0.5, 1.3)
        self.hp -= loss
        if self.hp <= 0:
            self.hp = 0.0
            self.screen, self.data = Screen.DEFEAT, {"from": self.data.get("from", self.start), "tile": tile}
        else:
            self._win_battle(tile)

    def _win_battle(self, tile=None):
        tile = tile or self.data.get("tile") or self.pos
        if self.tiles[tile] == "final_battle":
            self.screen, self.data = Screen.RESULT, {}
        else:
            self._back_to_map()


def forced_unsolvable(kn, map_id, policy):
    """Maps whose objective cannot be reached if stepping on a link tile always teleports (data suggests this is not the rule)."""
    from .navigator import Navigator
    nav = Navigator(policy, kn, map_id)
    nav.teleport_forced = True
    start = sorted(k for k, t in nav.tiles.items() if t == "player")[0]
    nav.arrive(start)
    dist, _ = nav._dijkstra(start, False)
    return nav._best(dist, nav._goal_tiles()) is None


def run_one(kn, map_id, policy, seed, noise=None, text_visible=True, known_map=True, budget=2500, forced_teleport=True):
    rng = random.Random(f"{map_id}/{seed}")
    game = MockGame(kn, map_id, rng, noise, text_visible, known_map, forced_teleport)
    engine = Engine(policy, kn, map_id if known_map else None)
    for _ in range(budget):
        obs = game.observe()
        act = engine.step(obs)
        if act.kind == Do.STOP:
            game.failed = True
            break
        game.act(act)
        if game.success:
            break
    return {"map": map_id, "success": game.success, "actions": game.actions, "stopped": game.failed,
            "reason": engine.log[-1].reason if game.failed else None, "hp": round(game.hp, 2), "stats": dict(game.stats),
            "engine_steps": engine.guard.steps}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--maps", default="all")
    ap.add_argument("--presets", default="balanced")
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--no-text", action="store_true", help="options/choices have no text (OCR unavailable)")
    ap.add_argument("--unknown-map", action="store_true", help="do not tell the engine which map it is on")
    ap.add_argument("--optional-teleport", action="store_true", help="entry tiles do not force a teleport")
    ap.add_argument("--noise", type=float, default=1.0, help="multiplier for fault injection")
    ap.add_argument("--json", help="write detailed results")
    args = ap.parse_args()
    kn = Knowledge()
    maps = list(kn.maps) if args.maps == "all" else args.maps.split(",")
    noise = {"ignore": .08 * args.noise, "unknown": .04 * args.noise, "popup": .05 * args.noise, "no_pos": .10 * args.noise}
    results = []
    skipped = set()
    for preset in args.presets.split(","):
        pol = load_policy(preset=preset)
        for m in maps:
            if not args.optional_teleport and forced_unsolvable(kn, m, pol):
                skipped.add(m)
                continue
            for s in range(args.seeds):
                r = run_one(kn, m, pol, s, noise, not args.no_text, not args.unknown_map, forced_teleport=not args.optional_teleport)
                r["preset"], r["seed"] = preset, s
                results.append(r)
    if skipped:
        print(f"skipped {len(skipped)} maps that are unsolvable if link tiles force a teleport: {sorted(skipped)}")
    ok = [r for r in results if r["success"]]
    print(f"runs {len(results)}  success {len(ok)} ({100 * len(ok) / len(results):.1f}%)  median actions {sorted(r['actions'] for r in ok)[len(ok)//2] if ok else '-'}")
    bad = [r for r in results if not r["success"]]
    for r in bad[:25]:
        print("FAIL", r["preset"], r["map"], r["seed"], "stopped" if r["stopped"] else "budget", r["reason"], r["actions"])
    tot = Counter()
    for r in results:
        tot.update(r["stats"])
    print("totals", dict(tot))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
