"""Static game knowledge: maps, tile effects, wiki event catalogue; fuzzy text matching for OCR output."""

import difflib
import json
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "resource" / "map_data"
_PUNCT = re.compile(r"[\s·・,，.。:：!！?？「」『』\"'“”()（）\-—_]+")


def norm(text):
    return _PUNCT.sub("", text or "")


def similar(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


class Knowledge:
    def __init__(self, data_dir=DATA):
        data_dir = Path(data_dir)
        read = lambda n: json.loads((data_dir / n).read_text(encoding="utf-8"))
        self.recognised_maps = read("maps.json")["maps"]           # screenshot recognition (wiki images)
        self.maps = dict(self.recognised_maps)
        self.stage_maps = defaultdict(list)                       # stage name -> client map keys
        client_file = data_dir / "maps_client.json"
        if client_file.is_file() and (data_dir / "client" / "aliases.json").is_file():
            # the game client's own maps are exact (walls, plain floor, hidden event tiles, random variants):
            # they replace the recognised layout of every map we could match, and add all the others under their id
            client = json.loads(client_file.read_text(encoding="utf-8"))["maps"]
            aliases = json.loads((data_dir / "client" / "aliases.json").read_text(encoding="utf-8"))["aliases"]
            self.maps.update(client)
            for key, a in aliases.items():
                self.maps[key] = {**client[a["client_map"]], "id": key, "client_map": a["client_map"]}
            for mid, m in client.items():
                for name in m["stage_names"]:
                    self.stage_maps[name].append(mid)
        self.effects = read("tile_effects.json")["effects"]
        self.events = read("events.json")["events"] if (data_dir / "events.json").is_file() else []
        self._ident_index = None
        self.by_title = defaultdict(list)
        self.by_map = defaultdict(list)
        for ev in self.events:
            self.by_title[norm(ev["event"])].append(ev)
            if ev.get("map_id"):
                self.by_map[ev["map_id"]].append(ev)

    def match_event(self, title, map_id=None, cutoff=0.62):
        """Best catalogue entry for an OCR'd event title (prefers events of the current map)."""
        if not title:
            return None
        pools = [self.by_map.get(map_id, []), self.events] if map_id else [self.events]
        for pool in pools:
            best, score = None, 0.0
            for ev in pool:
                s = similar(title, ev["event"])
                if s > score:
                    best, score = ev, s
            if best and score >= cutoff:
                return best
        return None

    def match_option(self, event, label, cutoff=0.7):
        if not event or not label:
            return None
        best, score = None, 0.0
        for opt in event["options"]:
            s = similar(label, opt["label"])
            if s > score:
                best, score = opt, s
        return best if score >= cutoff else None

    def resolve_map(self, ref):
        """Map key for one of our keys (8-2), a client map id or a stage name; None when unknown."""
        if ref in self.maps:
            return ref
        return self.stage_maps[ref][0] if self.stage_maps.get(ref) else None

    def identify_map(self, observed, min_typed=5, pool=None):
        """Which client map(s) show these tiles? observed: {(row, col): type} in any lattice frame (types as in maps;
        plain / unknown tiles are ignored). Returns [(typed matches, client map id, (dr, dc))], best first, where
        client position = observed position + (dr, dc), keeping only maps in which EVERY observed typed tile agrees.
        Maps with the same layout (normal / hard / crazy versions) are reported once."""
        typed = {k: t for k, t in observed.items() if t not in ("plain", "unknown", "player", None)}
        if len(typed) < min_typed:
            return []
        if self._ident_index is None:
            self._ident_index = {}
            seen = {}
            for key, m in self.maps.items():
                if not key.isdigit():
                    continue
                cells = {(t["row"], t["col"]): {t["type"], *t.get("alts", ())} for t in m["tiles"]}
                sig = tuple(sorted((k, tuple(sorted(v))) for k, v in cells.items()))
                if sig in seen:
                    continue
                seen[sig] = key
                self._ident_index[key] = (cells, defaultdict(list))
                for k, types_ in cells.items():
                    for ty in types_:
                        self._ident_index[key][1][ty].append(k)
        pool = set(pool) if pool else None
        a0, t0 = min(typed.items())
        out = []
        for key, (cells, by_type) in self._ident_index.items():
            if pool is not None and key not in pool:
                continue
            for cand in by_type.get(t0, ()):
                dr, dc = cand[0] - a0[0], cand[1] - a0[1]
                if all(t in cells.get((r + dr, c + dc), ()) for (r, c), t in typed.items()):
                    out.append((len(typed), key, (dr, dc)))
        out.sort(key=lambda x: (x[1].isdigit() and int(x[1]), x[1]))
        return out

    def tile_effect(self, tile_type):
        return self.effects.get(tile_type, {"passable": True, "cost": 3})
