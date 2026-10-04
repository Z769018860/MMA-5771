"""Decision engine: Observation -> Action, one step at a time, with stuck protection."""

from .contract import Action, Do, Screen
from . import decisions
from .guard import StuckGuard
from .knowledge import Knowledge
from .navigator import Navigator
from .policy import get, load_policy


class Engine:
    def __init__(self, policy=None, knowledge=None, map_id=None):
        self.policy = policy or load_policy()
        self.kn = knowledge or Knowledge()
        self.map_id = map_id
        self.nav = Navigator(self.policy, self.kn, map_id)
        self.guard = StuckGuard(self.policy)
        self.moved_to = None          # tile we last tapped
        self.expect_pos = None        # where the tap should leave us
        self.alt_cursor = 0           # rotates alternative choices when stuck
        self.log = []
        self.done = False
        self.finishing = False
        self._last_pos = None
        self._shop_buys = 0
        self._pick_pending = False
        self.awaken_blocked = False
        self.tap_fp = None
        self.cur_tile = None          # tile whose content we are resolving
        self.defeats = {}             # tile -> times a defeat followed it
        self.tried = {}               # tile -> event options already tried there

    # ------------------------------------------------------------------ helpers
    def _emit(self, kind, arg=None, reason=""):
        act = Action(kind, arg, reason)
        self.guard.note(act)
        self.log.append(act)
        return act

    def _set_map(self, obs):
        if obs.map_id and obs.map_id != self.map_id:
            self.map_id = obs.map_id
            self.nav = Navigator(self.policy, self.kn, obs.map_id)

    def _localise(self, obs):
        pos = obs.player
        if pos is None and self.expect_pos is not None:
            pos = self.expect_pos
        return pos

    # ------------------------------------------------------------------ main entry
    def step(self, obs):
        if self.finishing and obs.screen != Screen.RESULT:
            self.done = True
            return self._emit(Do.STOP, "completed", "result page closed: objective reached")
        if self.done:
            return self._emit(Do.STOP, "done", "already finished")
        self._set_map(obs)
        level = self.guard.observe(obs)
        if level >= 4:
            return self._give_up(obs)
        handler = {
            Screen.MAP: self._on_map, Screen.EVENT: self._on_event, Screen.SHOP: self._on_shop,
            Screen.PICK_ARTIFACT: lambda o, l: self._on_pick(o, l, "artifact"),
            Screen.PICK_SEAL: lambda o, l: self._on_pick(o, l, "seal"),
            Screen.PICK_CARD: lambda o, l: self._on_pick(o, l, "card"),
            Screen.PICK_AWAKEN: lambda o, l: self._on_pick(o, l, "awaken"),
            Screen.CONTACT: self._on_contact, Screen.FORMATION: self._on_formation,
            Screen.BATTLE: self._on_battle, Screen.DEFEAT: self._on_defeat,
            Screen.DIALOGUE: self._on_dialogue, Screen.POPUP: self._on_popup,
            Screen.RESULT: self._on_result, Screen.LOADING: self._on_wait, Screen.UNKNOWN: self._on_unknown,
        }[obs.screen]
        return handler(obs, level)

    # ------------------------------------------------------------------ give up
    def _give_up(self, obs):
        if get(self.policy, "stuck.on_give_up") == "skip_tile" and self.moved_to is not None and obs.screen == Screen.MAP:
            self.nav.blacklist.add(self.moved_to)
            self.guard.progressed()
            return self._emit(Do.TAP_BLANK, None, f"give up tile {self.moved_to}: blacklisted, replanning")
        self.done = True
        return self._emit(Do.STOP, "stuck", f"giving up after {self.guard.steps} steps; last: {self.guard.history[-3:]}")

    # ------------------------------------------------------------------ MAP
    def _on_map(self, obs, level):
        pos = self._localise(obs)
        if self.moved_to is not None:
            if obs.player is None:
                changed = obs.fingerprint is None or obs.fingerprint != self.tap_fp   # cannot localise: did the frame change?
            else:
                changed = obs.player != self._last_pos
            if changed:
                # the previous tap changed our position (or we cannot tell): count it as arrival
                landed = obs.player
                if landed is not None:
                    self.nav.learn_teleport(self.moved_to, landed)
                self.nav.arrive(self.expect_pos if landed is None else landed)
                self.guard.progressed()
            else:
                self.nav.mark_failed(self.moved_to)
            self.moved_to = None
        elif pos is not None:
            self.nav.arrive(pos)
        self._last_pos = pos
        limit = get(self.policy, "stuck.max_tile_entries", 8) * (3 if self.nav.dynamic else 1)
        if pos is not None and self.nav.entries[pos] > limit:
            self.done = True
            return self._emit(Do.STOP, "loop", f"entered tile {pos} {self.nav.entries[pos]} times: walking in circles")
        if level == 3:
            return self._emit(Do.BACK, None, "stuck on map: back out")
        if self.nav.dynamic and pos is not None:
            self.nav.learn(pos, obs.candidates)
        if self.nav.has_prior and pos is not None:
            cand = self.nav.next_tile(pos, obs.hp_ratio)
            if cand:
                tile, plan = cand
                if level == 2:
                    alt = self._alternative_tile(obs, pos, tile)
                    if alt:
                        tile = alt
                self.moved_to = self.cur_tile = tile
                self.tap_fp = obs.fingerprint
                self.expect_pos = self.nav.links[tile] if (tile in self.nav.links and self.nav.teleport_forced) else tile
                return self._emit(Do.TAP_TILE, tile, f"{plan['reason']} -> {plan['target']} ({self.nav.type_of(tile)})")
        if obs.candidates:
            pick = self.nav.choose_candidate(obs.candidates)
            if pick:
                self.moved_to, self.expect_pos, self.tap_fp = pick[0], pick[0], obs.fingerprint
                self.cur_tile = pick[0]
                return self._emit(Do.TAP_TILE, pick[0], f"no prior map: candidate {pick[1]}")
        return self._emit(Do.WAIT, None, "map: nothing to do (no route / no candidates)")

    def _alternative_tile(self, obs, pos, current):
        """When tapping the planned tile does nothing, try another enterable neighbour."""
        opts = [t for t in obs.candidates] or []
        opts = [k for k, _ in opts if k != current and k not in self.nav.blacklist]
        if not opts:
            opts = [(pos[0], pos[1] + dr, pos[2] + dc) for dr, dc in ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1))]
            opts = [k for k in opts if k in self.nav.tiles and k != current and k not in self.nav.blacklist]
        if not opts:
            return None
        self.alt_cursor += 1
        return opts[self.alt_cursor % len(opts)]

    # ------------------------------------------------------------------ EVENT
    def _on_event(self, obs, level):
        n = len(obs.options)
        if n == 0:
            return self._emit(Do.CLOSE_POPUP if level else Do.WAIT, None, "event without options")
        if level >= 2:  # tapping the chosen option did nothing: rotate through the others
            self.alt_cursor += 1
            idx = (n - 1 - self.alt_cursor) % n
            return self._emit(Do.TAP_OPTION, idx, f"stuck level {level}: rotating options")
        required = self.nav.required_for_goal(self._last_pos, self.cur_tile)
        dec = decisions.choose_event_option(
            self.policy, self.kn, obs.event_title, obs.options, obs.hp_ratio, self.map_id,
            required_checkpoint=required,
        )
        idx, why = dec.index, dec.reason
        tried = self.tried.setdefault(self.cur_tile, set())
        if self.defeats.get(self.cur_tile) and idx in tried and len(tried) < n:
            # this tile already ended in a defeat with that option: try something else next time
            order = [i for _, i, _ in sorted(dec.ranked, key=lambda r: -r[0])] or list(range(n - 1, -1, -1))
            idx = next(i for i in order + list(range(n)) if i not in tried)
            why = f"defeat followed option {sorted(tried)} here: trying {idx}"
        tried.add(idx)
        return self._emit(Do.TAP_OPTION, idx, why)

    # ------------------------------------------------------------------ SHOP
    def _on_shop(self, obs, level):
        if level >= 1:
            return self._emit(Do.LEAVE, None, f"shop stuck level {level}: leave")
        buys = decisions.choose_shop(self.policy, obs.shop_items, obs.currency)
        already = self._shop_buys
        if buys and already < len(buys) and self.guard.same == 0:
            idx = buys[already]
            self._shop_buys = already + 1
            return self._emit(Do.TAP_ITEM, idx, f"buy item {idx} ({already + 1}/{len(buys)})")
        self._shop_buys = 0
        return self._emit(Do.LEAVE, None, "shop done")

    # ------------------------------------------------------------------ PICK
    def _on_pick(self, obs, level, kind):
        n = len(obs.choices)
        if n == 0:
            return self._emit(Do.CONFIRM, None, f"{kind}: no choices visible, confirm")
        if level >= 2:
            if self._pick_pending:      # a rotated tap was just made: confirm it, otherwise rotation never completes a pick
                self._pick_pending = False
                return self._emit(Do.CONFIRM, None, f"{kind} stuck: confirm the rotated choice")
            cands = [i for i in range(n) if not (kind == "awaken" and obs.choice_enabled and i < len(obs.choice_enabled) and not obs.choice_enabled[i])]
            if not cands:
                self.awaken_blocked = True
                return self._emit(Do.BACK, None, "awaken: nothing can be chosen, going back")
            self.alt_cursor += 1
            self._pick_pending = True
            return self._emit(Do.TAP_CHOICE, cands[self.alt_cursor % len(cands)], f"{kind} stuck: rotate choices")
        if level == 1 or self._pick_pending:
            self._pick_pending = False
            return self._emit(Do.CONFIRM, None, f"{kind}: confirm")
        if kind == "awaken":
            dec = decisions.choose_awaken(self.policy, obs.choices, obs.choice_enabled)
            if dec is None:   # nobody can be awakened: leave and heal at contact points from now on
                self.awaken_blocked = True
                return self._emit(Do.BACK, None, "awaken: no character can be awakened, going back to heal instead")
        else:
            dec = decisions.choose_pick(self.policy, kind, obs.choices)
        self._pick_pending = True
        return self._emit(Do.TAP_CHOICE, dec.index, dec.reason)

    # ------------------------------------------------------------------ CONTACT
    def _on_contact(self, obs, level):
        which, why = decisions.contact_choice(self.policy, obs.hp_ratio, obs.contact_awaken_available, self.awaken_blocked)
        if level >= 2:
            which = "awaken" if which == "heal" else "heal"
            why = "stuck: try the other contact option"
        return self._emit(Do.CHOOSE_HEAL if which == "heal" else Do.CHOOSE_AWAKEN, None, why)

    # ------------------------------------------------------------------ battle flow
    def _on_formation(self, obs, level):
        return self._emit(Do.START_BATTLE, None, "formation: investigate" + (" (retry)" if level else ""))

    def _on_battle(self, obs, level):
        return self._emit(Do.WAIT, None, "battle running (auto)")

    def _on_defeat(self, obs, level):
        which, why = decisions.defeat_choice(self.policy, obs.revive_available)
        if self.guard.same == 0 and self.cur_tile is not None:
            self.defeats[self.cur_tile] = self.defeats.get(self.cur_tile, 0) + 1
        if level >= 2:
            which, why = "retreat", "stuck on defeat dialog: retreat"
        return self._emit(Do.REVIVE if which == "revive" else Do.RETREAT, None, why)

    def _on_result(self, obs, level):
        self.finishing = True
        return self._emit(Do.FINISH, None, "result page: finish (repeat until it closes)")

    # ------------------------------------------------------------------ misc screens
    def _on_dialogue(self, obs, level):
        return self._emit(Do.SKIP if level < 2 else Do.TAP_BLANK, None, "skip dialogue")

    def _on_popup(self, obs, level):
        return self._emit(Do.CLOSE_POPUP if level < 2 else Do.TAP_BLANK if level == 2 else Do.BACK, None, "close popup")

    def _on_wait(self, obs, level):
        return self._emit(Do.WAIT, None, "loading")

    def _on_unknown(self, obs, level):
        ladder = [Do.WAIT, Do.TAP_BLANK, Do.CLOSE_POPUP, Do.BACK]
        step = ladder[min(level + 1, 3)] if self.guard.same else Do.WAIT   # first look, then escalate while nothing changes
        return self._emit(step, None, "unrecognised screen")
