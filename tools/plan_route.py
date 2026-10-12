"""Plan a route from the player's tile to the final battle using resource/map_data.

    python tools/plan_route.py 5-6                 # one map (our key, client map id or stage name)
    python tools/plan_route.py 5-6 --collect meltmark,contact   # also visit these tile types
    python tools/plan_route.py 5-6 --source recognized          # the screenshot-recognised map instead of the client one
    python tools/plan_route.py --check             # sufficiency report for all maps (client maps by default)

Model (see resource/map_data/tile_effects.json for sources and confidence)
  * tiles are hex lattice cells; neighbours differ by (row,col) = (0,+-2) or (+-1,+-1)
  * 'blocking' tiles (cracked_rock) cannot be entered
  * locked_door needs a key; keys come from rusty_key tiles (--key-mode keep|consume).
    Every map has at most one key but up to five doors, so 'keep' (one key opens all) is the default
  * tunnel tiles are a bidirectional pair; oneway_in -> secret_exit is directed
  * cost per tile = tile_effects[type].cost, a planning weight only; a cell with random variants (`alts`) costs the mean
  * 监察点 (checkpoint) cannot be walked through; its only way on is the optional teleport to a 羁押点 (detention) = the 8-2
    live run's 诈降 option (costs a symptom)
  * if the goal island cannot be reached at all, speculative bridges between the nearest tiles of different islands are
    added as a last resort (the game links such islands with events we have no data for); the plan marks those hops
Maps: resource/map_data/maps_client.json (all 1171 client maps, exact: walls, plain floor, random variants) is the default
source; resource/map_data/maps.json (screenshot recognition) is kept for comparison.
"""

import argparse
import heapq
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "resource" / "map_data"
NEIGHBOURS = ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1))


CHECKPOINT_PENALTY = 4.0   # surrendering at a checkpoint costs a symptom: weighted like an elite fight
BRIDGE_COST = 8.0


def load(data=DATA, source="client"):
    """Returns (maps, effects). maps: our recognised keys (client layout when the alias table knows it) and client map ids."""
    effects = json.loads((data / "tile_effects.json").read_text(encoding="utf-8"))["effects"]
    recognised = json.loads((data / "maps.json").read_text(encoding="utf-8"))["maps"]
    if source == "recognized" or not (data / "maps_client.json").is_file():
        return recognised, effects
    client = json.loads((data / "maps_client.json").read_text(encoding="utf-8"))["maps"]
    aliases = json.loads((data / "client" / "aliases.json").read_text(encoding="utf-8"))["aliases"]
    maps = dict(client)
    for key, a in aliases.items():
        maps[key] = {**client[a["client_map"]], "id": key, "client_map": a["client_map"]}
    return maps, effects


def resolve(maps, ref):
    """Map entry for one of our keys, a client map id or a stage name (the first map of that stage), else None."""
    if ref in maps:
        return maps[ref]
    for m in maps.values():
        if ref in m.get("stage_names", ()):
            return m
    return None


class Graph:
    def __init__(self, map_entry, effects):
        self.tiles = {(t["island"], t["row"], t["col"]): t for t in map_entry["tiles"]}
        self.effects = effects
        by_type = defaultdict(list)
        for key, t in self.tiles.items():
            by_type[t["type"]].append(key)
        self.by_type = by_type
        self.links = defaultdict(list)  # teleport edges
        self.problems = []
        tun = by_type["tunnel"]
        if len(tun) == 2:
            self.links[tun[0]].append(tun[1])
            self.links[tun[1]].append(tun[0])
        elif tun:
            self.problems.append(f"{len(tun)} tunnels: cannot pair")
        one, out = by_type["oneway_in"], by_type["secret_exit"]
        if len(one) == 1 and len(out) == 1:
            self.links[one[0]].append(out[0])
        elif one or out:
            self.problems.append(f"{len(one)} oneway_in / {len(out)} secret_exit: cannot pair")
        self.keys = sorted(by_type["rusty_key"])
        self.doors = sorted(by_type["locked_door"])
        self.alts = {(t["island"], t["row"], t["col"]): t["alts"] for t in map_entry["tiles"] if t.get("alts")}
        # 监察点 -> 羁押点: optional teleport, not a forced link (leaving returns to the previous tile)
        self.optional = {c: list(by_type["detention"]) for c in by_type["checkpoint"]} if by_type["detention"] else {}
        self.bridges = {}

    def passable(self, key):
        return not self.effects[self.tiles[key]["type"]].get("blocking")

    def moves(self, key):
        island, row, col = key
        if self.tiles[key]["type"] == "checkpoint":
            # 8-2 live: you cannot walk on through a checkpoint - leaving returns you to the previous tile, only the
            # 诈降 option (teleport to a 羁押点) gets you anywhere
            yield from self.optional.get(key, ())
            return
        for dr, dc in NEIGHBOURS:
            nxt = (island, row + dr, col + dc)
            if nxt in self.tiles and self.passable(nxt):
                yield nxt
        for nxt in self.links.get(key, ()):
            yield nxt
        for nxt in self.optional.get(key, ()):
            yield nxt
        for nxt in self.bridges.get(key, ()):
            yield nxt

    def step_cost(self, a, b, avoid):
        """Cost of moving a -> b: the entered tile's cost, plus the symptom of a surrender or a bridge's guess."""
        extra = CHECKPOINT_PENALTY if b in self.optional.get(a, ()) else (BRIDGE_COST if b in self.bridges.get(a, ()) else 0.0)
        return self.cost(b, avoid) + extra

    def cost(self, key, avoid):
        types = [self.tiles[key]["type"], *self.alts.get(key, ())]          # random variants: expected cost
        return sum(self.effects[t].get("cost", 1) * avoid.get(t, 1) for t in types) / len(types)

    def add_bridges(self):
        """Last resort for maps whose islands are not connected by anything we know: link the nearest tile pairs."""
        by_island = defaultdict(list)
        for k in self.tiles:
            by_island[k[0]].append(k)
        islands = sorted(by_island)
        for i, a in enumerate(islands):
            for b in islands[i + 1:]:
                best = min(((abs(p[1] - q[1]) + abs(p[2] - q[2]), p, q) for p in by_island[a] for q in by_island[b]
                            if self.passable(p) and self.passable(q)), default=None)
                if best:
                    _, p, q = best
                    self.bridges.setdefault(p, []).append(q)
                    self.bridges.setdefault(q, []).append(p)


def plan(graph, key_mode="keep", avoid=None, collect=(), target="final_battle"):
    """Dijkstra over (tile, keys picked, doors opened, collected-targets). Returns (cost, [tile keys]) or None."""
    avoid = avoid or {}
    starts = graph.by_type["player"]
    goals = set(graph.by_type[target])
    if not starts or not goals:
        return None
    want = [k for ty in collect for k in graph.by_type[ty]]
    wi = {k: i for i, k in enumerate(want)}
    ki = {k: i for i, k in enumerate(graph.keys)}
    di = {k: i for i, k in enumerate(graph.doors)}
    counter = itertools.count()
    start = (starts[0], 0, 0, 0)
    best = {start: 0}
    heap = [(0, next(counter), start, None)]
    parent = {}
    while heap:
        cost, _, state, _ = heapq.heappop(heap)
        if best.get(state, 1e18) < cost:
            continue
        tile, kmask, dmask, wmask = state
        if tile in goals and wmask == (1 << len(want)) - 1:
            path = [tile]
            while state in parent:
                state = parent[state]
                path.append(state[0])
            return cost, path[::-1]
        for nxt in graph.moves(tile):
            nk, nd, nw = kmask, dmask, wmask
            if nxt in di and not (dmask >> di[nxt]) & 1:
                have = bin(kmask).count("1") - (bin(dmask).count("1") if key_mode == "consume" else 0)
                if have <= 0:
                    continue
                nd |= 1 << di[nxt]
            if nxt in ki:
                nk |= 1 << ki[nxt]
            if nxt in wi:
                nw |= 1 << wi[nxt]
            nstate = (nxt, nk, nd, nw)
            ncost = cost + graph.step_cost(tile, nxt, avoid)
            if ncost < best.get(nstate, 1e18):
                best[nstate] = ncost
                parent[nstate] = state
                heapq.heappush(heap, (ncost, next(counter), nstate, None))
    return None


def plan_robust(graph, key_mode="keep", avoid=None, collect=(), target="final_battle"):
    """plan(), and when the goal is unreachable add speculative island bridges and try again.
    Returns (cost, path, speculative_hops) or None."""
    res = plan(graph, key_mode, avoid, collect, target)
    if res:
        return res[0], res[1], []
    graph.add_bridges()
    res = plan(graph, key_mode, avoid, collect, target)
    if not res:
        return None
    cost, path = res
    hops = [i for i in range(1, len(path)) if path[i] in graph.bridges.get(path[i - 1], ())]
    return cost, path, hops


def diagnose(graph):
    """Why is the goal unreachable? Return a short reason."""
    if not graph.by_type["player"]:
        return "no player tile"
    if not graph.by_type["final_battle"]:
        return "no final_battle tile"
    seen, stack = set(), [graph.by_type["player"][0]]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(graph.moves(cur))  # ignores doors
    if not any(g in seen for g in graph.by_type["final_battle"]):
        islands = len({k[0] for k in graph.tiles})
        return f"goal not connected even ignoring doors ({islands} islands; likely missing tiles in the data)"
    return "goal needs more keys than the map offers"


def check_all(maps, effects):
    report = {}
    for name, m in maps.items():
        g = Graph(m, effects)
        if not g.by_type["final_battle"]:
            report[name] = {"status": "no_goal", "tiles": len(g.tiles), "islands": len({k[0] for k in g.tiles})}
            continue
        keep, consume = plan(g, "keep"), plan(g, "consume")
        entry = {"tiles": len(g.tiles), "islands": len({k[0] for k in g.tiles}), "doors": len(g.doors), "keys": len(g.keys),
                 "problems": g.problems, "works_if_keys_consumed": bool(consume)}
        if keep:
            entry.update(status="ok", cost=keep[0], steps=len(keep[1]) - 1)
        else:
            reason = diagnose(g)
            robust = plan_robust(Graph(m, effects))
            entry.update(status="bridged" if robust else "unreachable", reason=reason)
            if robust:
                entry.update(cost=robust[0], steps=len(robust[1]) - 1, speculative_hops=len(robust[2]))
        report[name] = entry
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--key-mode", choices=("consume", "keep"), default="keep",
                    help="keep: one key opens every door (default; maps have 1 key but up to 5 doors); consume: each door uses one key")
    ap.add_argument("--avoid", default="", help="comma list of tile types to penalise x5, e.g. illusion,battle")
    ap.add_argument("--collect", default="", help="comma list of tile types that must be visited at least once")
    ap.add_argument("--source", choices=("client", "recognized"), default="client")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    maps, effects = load(source=args.source)
    avoid = {t: 5 for t in args.avoid.split(",") if t}
    collect = [t for t in args.collect.split(",") if t]
    if args.check:
        report = check_all(maps, effects)
        count = Counter(r["status"] for r in report.values())
        print(dict(count), "| keys must be reusable (keep mode needed) on",
              sum(1 for r in report.values() if r["status"] == "ok" and not r["works_if_keys_consumed"]), "maps")
        for name, r in report.items():
            if r["status"] in ("unreachable", "bridged"):
                print(name, r["status"], r.get("reason"), r.get("speculative_hops", ""))
        if args.out:
            args.out.write_bytes(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True).encode("utf-8"))
        return
    entry = resolve(maps, args.map)
    if entry is None:
        raise SystemExit(f"unknown map {args.map!r}; use one of our keys (8-2), a client map id or a stage name")
    g = Graph(entry, effects)
    res = plan_robust(g, args.key_mode, avoid, collect)
    if not res:
        raise SystemExit(f"no route: {diagnose(g)}")
    cost, path, hops = res
    steps = [{"step": i, "type": g.tiles[k]["type"], "row": k[1], "col": k[2], "x": g.tiles[k].get("x"), "y": g.tiles[k].get("y"),
              **({"speculative": True} if i in hops else {})} for i, k in enumerate(path)]
    text = json.dumps({"map": args.map, "cost": cost, "steps": steps}, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(" -> ".join(f"{s['type']}({s['row']},{s['col']}){'*' if s.get('speculative') else ''}" for s in steps), f"\ncost {cost}"
              + (" (* = speculative bridge, no data)" if hops else ""))


if __name__ == "__main__":
    main()
