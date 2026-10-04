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
        self.maps = read("maps.json")["maps"]
        self.effects = read("tile_effects.json")["effects"]
        self.events = read("events.json")["events"] if (data_dir / "events.json").is_file() else []
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

    def tile_effect(self, tile_type):
        return self.effects.get(tile_type, {"passable": True, "cost": 3})
