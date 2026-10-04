"""Plan a route from the player's tile to the final battle using resource/map_data.

    python tools/plan_route.py 5-6                 # one map
    python tools/plan_route.py 5-6 --collect meltmark,contact   # also visit these tile types
    python tools/plan_route.py --check             # sufficiency report for all maps

Model (see resource/map_data/tile_effects.json for sources and confidence)
  * tiles are hex lattice cells; neighbours differ by (row,col) = (0,+-2) or (+-1,+-1)
  * 'blocking' tiles (cracked_rock) cannot be entered
  * locked_door needs a key; keys come from rusty_key tiles (--key-mode keep|consume).
    Every map has at most one key but up to five doors, so 'keep' (one key opens all) is the default
  * tunnel tiles are a bidirectional pair; oneway_in -> secret_exit is directed
  * cost per tile = tile_effects[type].cost, a planning weight only
"""

import argparse
import heapq
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "resource" / "map_data"
NEIGHBOURS = ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1))


def load(data=DATA):
    maps = json.loads((data / "maps.json").read_text(encoding="utf-8"))["maps"]
    effects = json.loads((data / "tile_effects.json").read_text(encoding="utf-8"))["effects"]
    return maps, effects


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

    def passable(self, key):
        return not self.effects[self.tiles[key]["type"]].get("blocking")

    def moves(self, key):
        island, row, col = key
        for dr, dc in NEIGHBOURS:
            nxt = (island, row + dr, col + dc)
            if nxt in self.tiles and self.passable(nxt):
                yield nxt
        for nxt in self.links.get(key, ()):
            yield nxt

    def cost(self, key, avoid):
        t = self.tiles[key]["type"]
        base = self.effects[t].get("cost", 1)
        return base * (avoid.get(t, 1))


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
            ncost = cost + graph.cost(nxt, avoid)
            if ncost < best.get(nstate, 1e18):
                best[nstate] = ncost
                parent[nstate] = state
                heapq.heappush(heap, (ncost, next(counter), nstate, None))
    return None


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--key-mode", choices=("consume", "keep"), default="keep",
                    help="keep: one key opens every door (default; maps have 1 key but up to 5 doors); consume: each door uses one key")
    ap.add_argument("--avoid", default="", help="comma list of tile types to penalise x5, e.g. illusion,battle")
    ap.add_argument("--collect", default="", help="comma list of tile types that must be visited at least once")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    maps, effects = load()
    avoid = {t: 5 for t in args.avoid.split(",") if t}
    collect = [t for t in args.collect.split(",") if t]
    if args.check:
        report, ok = {}, Counter()
        for name, m in maps.items():
            g = Graph(m, effects)
            res = {mode: plan(g, mode) for mode in ("consume", "keep")}
            status = "ok" if res["keep"] else "unreachable"
            ok[status] += 1
            report[name] = {"status": status, "tiles": len(g.tiles), "islands": len({k[0] for k in g.tiles}),
                            "doors": len(g.doors), "keys": len(g.keys), "problems": g.problems,
                            "cost": res["keep"][0] if res["keep"] else None,
                            "works_if_keys_consumed": bool(res["consume"]),
                            "reason": None if status == "ok" else diagnose(g)}
        print(dict(ok), "| routes that also work if each door consumes a key:",
              sum(r["works_if_keys_consumed"] for r in report.values()))
        for name, r in report.items():
            if r["status"] != "ok":
                print(name, r["status"], r["reason"], r["problems"])
        if args.out:
            args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    g = Graph(maps[args.map], effects)
    res = plan(g, args.key_mode, avoid, collect)
    if not res:
        raise SystemExit(f"no route: {diagnose(g)}")
    cost, path = res
    steps = [{"step": i, "type": g.tiles[k]["type"], "row": k[1], "col": k[2], "x": g.tiles[k]["x"], "y": g.tiles[k]["y"]}
             for i, k in enumerate(path)]
    text = json.dumps({"map": args.map, "cost": cost, "steps": steps}, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(" -> ".join(f"{s['type']}({s['row']},{s['col']})" for s in steps), f"\ncost {cost}")


if __name__ == "__main__":
    main()
