"""Editable settings: defaults <- preset <- user file, with validation.

    python -m morimens_logic.policy --validate config/explore_policy.json
    python -m morimens_logic.policy --show --preset greedy
"""

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPLORE_DIR = ROOT / "resource" / "explore"
USER_POLICY = ROOT / "config" / "explore_policy.json"

ENUMS = {
    "event.choice_mode": {"best_score", "leave", "first", "last"},
    "event.blind_choice": {"first", "middle", "last"},
    "event.tie_break": {"leave", "first", "last"},
    "shop.mode": {"none", "first", "all", "priority"},
    "shop.unaffordable": {"skip", "stop"},
    "contact.otherwise": {"heal", "awaken"},
    "battle.on_defeat": {"retreat", "revive"},
    "stuck.on_give_up": {"stop", "skip_tile"},
    "route.key_policy": {"pick_when_needed", "always_pick", "never"},
    "route.objective": {"final_battle"},
}


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _walk(d, prefix=""):
    for k, v in d.items():
        yield prefix + k, v
        if isinstance(v, dict):
            yield from _walk(v, prefix + k + ".")


FREE_FORM = ("route.avoid", "event.weights", "event.overrides", "event.known_rules")


def validate(policy, default=None):
    """Return (errors, warnings). Errors make the policy unusable; warnings are probable typos."""
    default = default or load_default()
    errors, warnings = [], []
    dflat = dict(_walk(default))
    for path, val in _walk(policy):
        free = any(path.startswith(f + ".") for f in FREE_FORM)
        if path not in dflat and not free:
            warnings.append(f"未知设置项 {path}（拼写错误？会被忽略）")
            continue
        if path in dflat and not free:
            ref = dflat[path]
            if ref is not None and val is not None and type(ref) is not type(val) and not (
                    isinstance(ref, (int, float)) and isinstance(val, (int, float)) and not isinstance(val, bool)):
                errors.append(f"{path}: 类型应为 {type(ref).__name__}，实际为 {type(val).__name__}")
        if path in ENUMS and val not in ENUMS[path]:
            errors.append(f"{path}: 取值应为 {sorted(ENUMS[path])} 之一，实际为 {val!r}")
    for path in ("contact.heal_below_hp", "event.hp_guard", "route.visit_contact_below_hp"):
        v = get(policy, path)
        if isinstance(v, (int, float)) and not 0 <= v <= 1:
            errors.append(f"{path}: 应在 0–1 之间")
    for path in ("shop.max_purchases", "route.max_detour_cost", "stuck.max_steps_per_map", "stuck.max_attempts_per_tile"):
        v = get(policy, path)
        if isinstance(v, (int, float)) and v < 0:
            errors.append(f"{path}: 不能为负数")
    s = policy.get("stuck", {})
    a, b, c = s.get("same_state_retry", 0), s.get("same_state_alternate", 0), s.get("same_state_recover", 0)
    if not a < b < c:
        errors.append("stuck: 需要 same_state_retry < same_state_alternate < same_state_recover")
    return errors, warnings


def get(policy, dotted, default=None):
    cur = policy
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def load_default():
    return json.loads((EXPLORE_DIR / "policy.default.json").read_text(encoding="utf-8"))


def load_known_rules():
    """Soft per-event rules generated from the known events (tools/build_event_rules.py): {event: {prefer, avoid}}."""
    f = EXPLORE_DIR / "event_rules.json"
    if not f.is_file():
        return {}
    rules = json.loads(f.read_text(encoding="utf-8")).get("rules", {})
    return {name: {"prefer": r.get("prefer", []), "avoid": r.get("avoid", [])} for name, r in rules.items()
            if r.get("prefer") or r.get("avoid")}


def load_policy(user_path=None, preset=None, overrides=None):
    """Effective policy. user_path defaults to config/explore_policy.json when it exists."""
    policy = load_default()
    user = {}
    user_path = Path(user_path) if user_path else (USER_POLICY if USER_POLICY.is_file() else None)
    if user_path:
        user = json.loads(user_path.read_text(encoding="utf-8-sig"))
    name = preset or user.get("preset") or policy.get("preset")
    preset_file = EXPLORE_DIR / "presets" / f"{name}.json"
    if not preset_file.is_file():
        raise ValueError(f"未知预设 {name!r}；可用：{sorted(p.stem for p in (EXPLORE_DIR / 'presets').glob('*.json'))}")
    policy = deep_merge(policy, json.loads(preset_file.read_text(encoding="utf-8")))
    policy = deep_merge(policy, {k: v for k, v in user.items() if k != "preset"})
    if overrides:
        policy = deep_merge(policy, overrides)
    policy["preset"] = name
    if get(policy, "event.use_known_rules", True):
        policy["event"]["known_rules"] = load_known_rules()
    errors, _ = validate(policy)
    if errors:
        raise ValueError("设置无效：\n  " + "\n  ".join(errors))
    return policy


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--validate", type=Path, help="check a user policy file")
    ap.add_argument("--show", action="store_true", help="print the effective policy")
    ap.add_argument("--preset")
    args = ap.parse_args()
    if args.validate:
        user = json.loads(args.validate.read_text(encoding="utf-8-sig"))
        try:
            eff = load_policy(args.validate, args.preset)
            errors, warnings = validate(eff)
        except ValueError as exc:
            print(exc)
            sys.exit(1)
        for w in validate(deep_merge(load_default(), user))[1]:
            print("警告:", w)
        print("设置有效")
    if args.show:
        print(json.dumps(load_policy(preset=args.preset), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
