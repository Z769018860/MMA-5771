"""Route choice on the hex map: replans every step from the current position.

Uses the static maps.json as prior knowledge when the stage id is known; otherwise picks among the
tiles the screen currently offers (observation.candidates) by type priority.
"""

import heapq
import itertools
from collections import Counter

from .policy import get

NEIGH = ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1))


class Navigator:
    def __init__(self, policy, kn, map_id=None):
        self.policy, self.kn, self.map_id = policy, kn, map_id
        entry = kn.maps.get(map_id) if map_id else None
        self.dynamic = entry is None            # no prior map: learn tiles from what the screen shows
        self.tiles = {(t["island"], t["row"], t["col"]): t["type"] for t in entry["tiles"]} if entry else {}
        self._version = 0
        self.visited, self.blacklist = set(), set()
        self.attempts = Counter()
        self.entries = Counter()      # how often each tile was entered: loop detection
        self.has_key = False
        self.teleport_forced = None   # learnt at runtime: does stepping on an entry tile always teleport?
        self.links = {}
        by = self.by_type
        tun = sorted(by.get("tunnel", []))
        if len(tun) == 2:
            self.links[tun[0]], self.links[tun[1]] = tun[1], tun[0]
        one, out = by.get("oneway_in", []), by.get("secret_exit", [])
        if len(one) == 1 and len(out) == 1:
            self.links[one[0]] = out[0]

    # ------------------------------------------------------------------ bookkeeping
    @property
    def has_prior(self):
        return bool(self.tiles)

    @property
    def by_type(self):
        by = {}
        for key, ty in self.tiles.items():
            by.setdefault(ty, []).append(key)
        return by

    def learn(self, pos, candidates):
        """Dynamic mode: remember the player's tile and the enterable tiles shown on screen."""
        if not self.dynamic or pos is None:
            return
        self.tiles.setdefault(pos, "unknown")
        for key, ty in candidates:
            if ty:
                self.tiles[key] = ty
            else:
                self.tiles.setdefault(key, "unknown")

    def arrive(self, pos):
        """The player now stands on pos (after any teleport)."""
        if pos is None:
            return
        self.visited.add(pos)
        if self.dynamic:
            self.tiles.setdefault(pos, "unknown")
        self.entries[pos] += 1
        for a, b in self.links.items():  # a teleport visits both ends
            if pos == b and a in self.tiles:
                self.visited.add(a)
        if self.tiles.get(pos) == "rusty_key" and get(self.policy, "route.key_policy") != "never":
            self.has_key = True

    def learn_teleport(self, entered, landed):
        """After tapping a link tile: landing on its partner means teleports are forced; staying means optional."""
        if entered not in self.links or landed is None:
            return
        if landed == self.links[entered]:
            self.teleport_forced = True
        elif landed == entered:
            self.teleport_forced = False

    def mark_failed(self, tile):
        self.attempts[tile] += 1
        if self.tiles.get(tile) == "locked_door" and self.has_key and self.attempts[tile] >= 2:
            # we believed we held a key but the door refuses: revise the belief and go and fetch one again
            self.has_key = False
            for k in self.by_type.get("rusty_key", []):
                self.visited.discard(k)
        if self.attempts[tile] > get(self.policy, "stuck.max_attempts_per_tile", 4):
            self.blacklist.add(tile)
            return True
        return False

    def type_of(self, key):
        return self.tiles.get(key)

    # ------------------------------------------------------------------ costs and graph
    def _cost(self, key):
        ty = self.tiles[key]
        if key in self.visited:
            return 1.0 + 2.0 * max(0, self.entries[key] - 2)   # discourage walking in circles
        eff = self.kn.tile_effect(ty)
        base = float(eff.get("cost", 1))
        mult = float((get(self.policy, "route.avoid") or {}).get(ty, 1.0))
        if eff.get("hazard") and not get(self.policy, "route.allow_hazard", True):
            mult *= 1000
        return max(base * mult, 0.1)

    def _passable(self, key, has_key):
        ty = self.tiles.get(key)
        if ty is None or key in self.blacklist:
            return False
        eff = self.kn.tile_effect(ty)
        if eff.get("blocking") or eff.get("passable") is False:
            return False
        if ty == "locked_door" and not has_key:
            return False
        return True

    def _neighbours(self, key):
        island, row, col = key
        for dr, dc in NEIGH:
            yield (island, row + dr, col + dc)
        # teleport happens when a tunnel/entry tile is entered (handled in dijkstra)

    def _dijkstra(self, start, has_key):
        """Single-source costs over states (tile, has_key). Returns dist, parent."""
        counter = itertools.count()
        start_state = (start, has_key)
        dist, parent = {start_state: 0.0}, {}
        heap = [(0.0, next(counter), start_state)]
        key_ok = get(self.policy, "route.key_policy") != "never"
        while heap:
            d, _, state = heapq.heappop(heap)
            if d > dist.get(state, 1e18):
                continue
            tile, hk = state
            steps = [(n, False) for n in self._neighbours(tile) if n in self.tiles]
            if tile in self.links and (tile != start or self.teleport_forced is not True):
                if self.teleport_forced and tile != start:
                    steps = []                                # learnt: stepping on an entry tile always teleports
                steps.append((self.links[tile], True))
            for nxt, is_link in steps:
                if not self._passable(nxt, hk):
                    continue
                nhk = hk or (key_ok and self.tiles[nxt] == "rusty_key")
                nstate = (nxt, nhk)
                nd = d + (0.0 if is_link else self._cost(nxt))
                if nd < dist.get(nstate, 1e18):
                    dist[nstate], parent[nstate] = nd, state
                    heapq.heappush(heap, (nd, next(counter), nstate))
        return dist, parent

    def _path(self, parent, state):
        out = [state[0]]
        while state in parent:
            state = parent[state]
            out.append(state[0])
        return out[::-1]

    def _best(self, dist, goals):
        best = None
        for (tile, hk), d in dist.items():
            if tile in goals and (best is None or d < best[0]):
                best = (d, (tile, hk))
        return best

    # ------------------------------------------------------------------ planning
    def _goal_tiles(self):
        return {k for k, t in self.tiles.items() if t == get(self.policy, "route.objective", "final_battle")}

    def required_for_goal(self, pos, tile):
        """Whether every currently known route to the goal crosses this tile."""
        if pos not in self.tiles or tile not in self.tiles or tile == pos or tile in self.blacklist:
            return False
        goals = self._goal_tiles()
        if not goals or not self._best(self._dijkstra(pos, self.has_key)[0], goals):
            return False
        self.blacklist.add(tile)
        try:
            return self._best(self._dijkstra(pos, self.has_key)[0], goals) is None
        finally:
            self.blacklist.remove(tile)

    def _extras(self, hp):
        pol, out = self.policy, {}
        want = list(get(pol, "route.must_visit", []))
        if get(pol, "route.use_searchlight", True):
            want.append("searchlight")
        if get(pol, "route.key_policy") == "always_pick":
            want.append("rusty_key")
        for ty in want:
            for k in self.by_type.get(ty, []):
                if k not in self.visited:
                    out[k] = "must_visit"
        thr = get(pol, "route.visit_contact_below_hp")
        if hp is not None and hp < thr:
            for k in self.by_type.get("contact", []):
                if k not in self.visited:
                    out[k] = "low_hp_contact"
        return out

    def plan(self, pos, hp=None):
        """Return dict(target, path, reason, cost) or None when no goal is reachable."""
        if not self.has_prior or pos not in self.tiles:
            return None
        goals = self._goal_tiles()
        dist, parent = self._dijkstra(pos, self.has_key)
        if not goals:                               # objective not seen yet: explore the cheapest unvisited known tile
            frontier = {k for k in self.tiles if k not in self.visited and k != pos}
            hit = self._best(dist, frontier)
            if not hit:
                return None
            path = self._path(parent, hit[1])
            return {"target": path[-1], "path": path[1:], "reason": "explore", "cost": hit[0]}
        final = self._best(dist, goals)
        extras = {k: why for k, why in self._extras(hp).items() if k != pos}
        limit = get(self.policy, "route.max_detour_cost", 12)
        picks = []
        for k, why in extras.items():
            hit = self._best(dist, {k})
            if not hit:
                continue
            d1, st = hit
            dist2, _ = self._dijkstra(k, st[1])
            tail = self._best(dist2, goals)
            if final and tail and why != "low_hp_contact" and d1 + tail[0] - final[0] > limit:
                continue
            picks.append((d1, k, why, st))
        if picks:
            d1, k, why, st = min(picks, key=lambda p: (p[2] != "low_hp_contact", p[0]))
            path = self._path(parent, st)
            return {"target": k, "path": path[1:], "reason": why, "cost": d1}
        if final:
            path = self._path(parent, final[1])
            return {"target": path[-1], "path": path[1:], "reason": "objective", "cost": final[0]}
        return None

    def next_tile(self, pos, hp=None):
        """First tile to tap, or None. Teleport hops are skipped (you land on them automatically)."""
        plan = self.plan(pos, hp)
        if not plan:
            return None
        for tile in plan["path"]:
            if tile in self.tiles and self._adjacent(pos, tile):
                return tile, plan
            break
        # path starts with a teleport hop: nothing to tap, caller should wait/relocalise
        return (plan["path"][0], plan) if plan["path"] else None

    @staticmethod
    def _adjacent(a, b):
        return a[0] == b[0] and (b[1] - a[1], b[2] - a[2]) in NEIGH

    # ------------------------------------------------------------------ unknown map
    def choose_candidate(self, candidates):
        """Without a prior map: pick among enterable tiles [(key, type|None)] by type priority."""
        prio = get(self.policy, "route.unknown_map_priority", [])
        best = None
        for key, ty in candidates:
            if key in self.blacklist:
                continue
            rank = prio.index(ty) if ty in prio else len(prio)
            if key in self.visited:
                rank += len(prio) + 1
            if best is None or rank < best[0]:
                best = (rank, key, ty)
        return (best[1], best[2]) if best else None
