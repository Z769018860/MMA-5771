"""Pure decision functions: event options, shop purchases, artifact/seal/card picks, contact, defeat.

All of them work without any text (OCR unavailable): pass None labels/names and positional policy
settings (event.blind_choice, *.position_order) decide. Every function always returns a valid choice.
"""

import difflib
from dataclasses import dataclass, field

from .knowledge import norm, similar
from .policy import get


@dataclass
class Decision:
    index: int
    reason: str
    ranked: list = field(default_factory=list)


def _blind_index(mode, n):
    return {"first": 0, "middle": n // 2, "last": n - 1}[mode]


def _keyword_hit(label, words):
    nl = norm(label)
    return any(norm(w) in nl for w in words if w)


def _override_for(policy, name):
    best, score = None, 0.0
    for key, rule in (get(policy, "event.overrides") or {}).items():
        s = similar(name, key)
        if s > score:
            best, score = rule, s
    return best if score >= 0.8 else None


def _same_label(a, b):
    """Exact or near-exact match (difflib, no substring shortcut: '离开' must not match '带它离开')."""
    a, b = norm(a), norm(b)
    return bool(a) and (a == b or difflib.SequenceMatcher(None, a, b).ratio() >= 0.85)


def _known_rule_for(policy, name):
    """Soft rule generated from the known events; only used when no hard override exists for this event."""
    rules = get(policy, "event.known_rules") or {}
    if not name:
        return None
    if name in rules:
        return rules[name]
    best, score = None, 0.0
    for key, rule in rules.items():
        sc = similar(name, key)
        if sc > score:
            best, score = rule, sc
    return best if score >= 0.8 else None


def score_option(policy, effects, label, hp_ratio):
    """Weighted effect score of one event option. Unknown effects score 0."""
    weights = dict(get(policy, "event.weights") or {})
    guard = get(policy, "event.hp_guard", 0.0)
    low = hp_ratio is not None and hp_ratio < guard
    total = 0.0
    for eff in effects or []:
        w = weights.get(eff.get("type"), 0.0)
        if low:
            if eff.get("type") == "lose_health":
                w *= 3
            elif eff.get("type") == "gain_symptom":
                w *= 1.5
            elif eff.get("type") == "heal":
                w *= 2
        total += w
    if label:
        if _keyword_hit(label, get(policy, "event.leave_keywords", [])):
            total += get(policy, "event.leave_score", 0.0)
        if _keyword_hit(label, get(policy, "event.prefer_keywords", [])):
            total += get(policy, "event.prefer_score", 0.0)
        if _keyword_hit(label, get(policy, "event.risky_keywords", [])):
            total += get(policy, "event.risky_score", 0.0)
    return total


def choose_event_option(policy, kn, title, options, hp_ratio=None, map_id=None, required_checkpoint=False):
    n = len(options)
    if n == 0:
        raise ValueError("event without options")
    mode = get(policy, "event.choice_mode")
    labels = list(options)
    if all(l is None for l in labels):
        idx = _blind_index(get(policy, "event.blind_choice"), n)
        return Decision(idx, f"no option text: blind_choice={get(policy, 'event.blind_choice')}")
    if required_checkpoint and title and "监察点" in title:
        for i, label in enumerate(labels):
            if label and "诈降" in label:
                return Decision(i, "required checkpoint: surrender to detention, then resolve inquisitor")
    if mode == "first":
        return Decision(0, "choice_mode=first")
    if mode == "last":
        return Decision(n - 1, "choice_mode=last")
    ev = kn.match_event(title, map_id) if (kn and title) else None
    rule = _override_for(policy, ev["event"] if ev else (title or ""))
    soft = None if rule else _known_rule_for(policy, ev["event"] if ev else (title or ""))
    soft_score = get(policy, "event.known_rule_score", 2.0)
    ranked = []
    for i, label in enumerate(labels):
        opt = kn.match_option(ev, label) if (kn and ev) else None
        s = score_option(policy, opt["effects"] if opt else [], label, hp_ratio)
        note = "catalogue" if opt else "keywords"
        if rule and label:
            for rank, want in enumerate(rule.get("prefer", [])):
                if similar(label, want) >= 0.8 or norm(want) in norm(label):
                    s += 100 - rank
                    note = f"override prefer '{want}'"
            for want in rule.get("avoid", []):
                if similar(label, want) >= 0.8 or norm(want) in norm(label):
                    s -= 100
                    note = f"override avoid '{want}'"
        if soft and label:
            for want in soft.get("prefer", []):
                if _same_label(label, want):
                    s += soft_score
                    note = f"known event rule: prefer '{want}'"
            for want in soft.get("avoid", []):
                if _same_label(label, want):
                    s -= soft_score
                    note = f"known event rule: avoid '{want}'"
        ranked.append((s, i, note))
    if mode == "leave":
        for _, i, _ in ranked:
            if labels[i] and _keyword_hit(labels[i], get(policy, "event.leave_keywords", [])):
                return Decision(i, "choice_mode=leave: leave keyword", ranked)
    top = max(r[0] for r in ranked)
    tied = [r for r in ranked if abs(r[0] - top) < 1e-9]
    tb = get(policy, "event.tie_break")
    if len(tied) > 1:
        if tb == "leave":
            for r in tied:
                if labels[r[1]] and _keyword_hit(labels[r[1]], get(policy, "event.leave_keywords", [])):
                    return Decision(r[1], "tie -> leave option", ranked)
        pick = tied[0] if tb in ("first", "leave") else tied[-1]
        return Decision(pick[1], f"tie -> {tb}", ranked)
    return Decision(tied[0][1], f"best score {top:.1f} ({tied[0][2]})", ranked)


def choose_shop(policy, items, currency=None):
    """Indexes of items to buy, in order. Never raises; empty list means leave immediately."""
    mode = get(policy, "shop.mode")
    if mode == "none" or not items:
        return []
    order = [i for i in get(policy, "shop.position_order", [0, 1, 2]) if i < len(items)]
    order += [i for i in range(len(items)) if i not in order]
    skip = get(policy, "shop.skip_names", [])
    prio = get(policy, "shop.priority_names", [])
    if mode == "priority" and prio:
        def rank(i):
            name = items[i].name
            for r, want in enumerate(prio):
                if name and similar(name, want) >= 0.8:
                    return r
            return len(prio)
        position = {i: p for p, i in enumerate(order)}
        order.sort(key=lambda i: (rank(i), position[i]))
    limit = 1 if mode == "first" else get(policy, "shop.max_purchases", 3)
    reserve = get(policy, "shop.reserve_currency", 0)
    stop_on_unaffordable = get(policy, "shop.unaffordable") == "stop"
    left, buys = currency, []
    for i in order:
        it = items[i]
        if len(buys) >= limit:
            break
        if it.sold or (it.name and any(similar(it.name, s) >= 0.8 for s in skip)):
            continue
        if not it.affordable:
            if stop_on_unaffordable:
                break
            continue
        if left is not None and it.price is not None:
            if left - it.price < reserve:
                continue
            left -= it.price
        buys.append(i)
    return buys


def choose_pick(policy, kind, names):
    """Index of the artifact/seal/card to take. names: list of str or None."""
    cfg = get(policy, f"pick.{kind}") or {}
    n = len(names)
    if n == 0:
        raise ValueError("nothing to pick")
    key_prio = "priority_names" if kind == "artifact" else "priority_keywords"
    key_avoid = "avoid_names" if kind == "artifact" else "avoid_keywords"
    for want in cfg.get(key_prio, []):
        for i, nm in enumerate(names):
            if nm and (similar(nm, want) >= 0.8 or norm(want) in norm(nm)):
                return Decision(i, f"priority '{want}'")
    avoid = cfg.get(key_avoid, [])
    ok = [i for i, nm in enumerate(names) if not (nm and any(norm(a) in norm(nm) or similar(nm, a) >= 0.8 for a in avoid))]
    for i in cfg.get("position_order", []):
        if i < n and i in ok:
            return Decision(i, f"position_order -> {i}")
    return Decision((ok or [0])[0], "fallback first acceptable")


def contact_choice(policy, hp_ratio, awaken_available=None, awaken_blocked=False):
    """Contact point: awakening a character is preferred; heal when hp is below contact.heal_below_hp,
    when the awaken option is unusable, or when a previous awaken attempt found nobody to awaken."""
    if awaken_blocked or awaken_available is False:
        return "heal", "nobody can be awakened: heal"
    if hp_ratio is not None and hp_ratio < get(policy, "contact.heal_below_hp"):
        return "heal", f"hp {hp_ratio:.2f} below threshold"
    pref = get(policy, "contact.otherwise")
    if hp_ratio is None and pref == "awaken":
        return "awaken", "hp unknown: awaken (preferred)"
    return pref, f"hp {hp_ratio if hp_ratio is None else round(hp_ratio, 2)} ok: {pref}"


def choose_awaken(policy, names, enabled=None):
    """Which character to awaken. Priority: contact names -> pick.awaken.order (1-based, left to right) -> left to right.
    Characters that cannot be awakened (enabled[i] false) are skipped. None when nobody can be awakened."""
    n = len(names)
    ok = [i for i in range(n) if not enabled or i >= len(enabled) or enabled[i]]
    if not ok:
        return None
    cfg = get(policy, "pick.awaken") or {}
    for want in cfg.get("priority_names", []):
        for i in ok:
            nm = names[i]
            if nm and (similar(nm, want) >= 0.8 or norm(want) in norm(nm)):
                return Decision(i, f"awaken priority name '{want}'")
    for pos in cfg.get("order", []):
        i = int(pos) - 1
        if i in ok:
            return Decision(i, f"awaken order: position {pos}")
    return Decision(ok[0], "awaken: left to right")


def defeat_choice(policy, revive_available):
    if get(policy, "battle.use_revive") and revive_available is not False:
        return "revive", "policy: use revive"
    return "retreat", "retreat"
