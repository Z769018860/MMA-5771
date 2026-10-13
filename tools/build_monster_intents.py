"""Monster action intents (意图) in the game's own format -> resource/map_data/monster_intents.json + intent icons

    python tools/build_monster_intents.py [--src DIR] [--icons DIR] [--check]

Reads the client's local config export (qdby_chinese/data/morimens/local-config/{monsters,skills}.json.gz) as plain
JSON (never executed) and writes, per monster, the action intents the way the in-game / wiki page shows them:
首轮行动 (InitSkillList) and 循环 1..n (CycleSkillListN) as ordered steps, each step with its intent icon
(resource/image/intent/intent_NNN.png), intent label (封印 = 强力削弱, 追猎 = 强力攻击, 攻击), target and the
official description.融灾 monsters also carry the stage values per level (data/morimens/dzone-info/by-monster.json:
damage and hit count), so "造成 886 点伤害 3 次" can be filled in for the real level.

Intent type -> icon id is the one of Morimens.Info.kr (images/dzone/intent); the 15 icons are game assets
(see resource/image/intent/README.md for their origin and rights).
"""

import argparse
import gzip
import json
import re
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resource" / "map_data" / "monster_intents.json"
ICON_DIR = ROOT / "resource" / "image" / "intent"
DEFAULT_SRC = Path("/home/user/z769018860/qdby_chinese")

INTENTS = OrderedDict([
    ("Intent_Attack", ("攻击", "001")), ("Intent_HeavyAttack", ("强力攻击", "002")),
    ("Intent_Debuff", ("削弱", "003")), ("Intent_StrongDebuff", ("强力削弱", "004")),
    ("Intent_Buff", ("强化", "005")), ("Intent_StrongBuff", ("强力强化", "006")),
    ("Intent_Defence", ("防御", "007")), ("Intent_AttackDefence", ("攻击·防御", "008")),
    ("Intent_AttackDebuff", ("攻击·削弱", "009")), ("Intent_AttackBuff", ("攻击·强化", "010")),
    ("Intent_DefenceBuff", ("防御·强化", "011")), ("Intent_DefenceDebuff", ("防御·削弱", "012")),
    ("Intent_Dizzy", ("眩晕", "013")), ("Intent_Unknown", ("特殊行动", "014")),
    ("Intent_Burst", ("特殊行动", "015")), ("Intent_Burst2", ("特殊行动", "015")), ("Intent_Burst3", ("行动", "015")),
])
TARGETS = {"FrontEnemy": "前排觉醒者", "PlayerRole": "我方", "CmdCaster": "自身", "AllAlly": "全体友方",
           "OtherAlly": "其他友方", "FrontAlly": "前排友方", "RandomAwaker": "随机觉醒者"}
CLASS = {"Common": "普通", "Elite": "精英", "Boss": "首领"}


def intent_of(types):
    t = next(iter(types.values()), "Intent_Unknown") if isinstance(types, dict) else "Intent_Unknown"
    if t not in INTENTS:
        t = re.sub(r"D\d+Skill\d+$", "", t)  # Intent_AttackDebuffD09Skill2 -> Intent_AttackDebuff
    if t not in INTENTS:
        t = "Intent_Unknown"
    return t


def clean_desc(text):
    """Argument placeholders become [ArgK] (filled from the level values); keyword tags keep their text."""
    text = re.sub(r"<(?:Damage|Block):\[(?:Damage|Block):(Arg\d)\]>", r"[\1]", text or "")
    text = re.sub(r"\[(?:Damage|Block|AttackTimes):(Arg\d)\]", r"[\1]", text)
    return re.sub(r"<[A-Za-z_0-9]+:\s*([^<>]*)>", r"\1", text)


def seq(lst):
    return [lst[k] for k in sorted(lst, key=int)] if isinstance(lst, dict) else []


def build(src):
    cfg = Path(src) / "data" / "morimens" / "local-config"
    monsters = json.load(gzip.open(cfg / "monsters.json.gz", "rt", encoding="utf-8"))
    skills = {s["id"]: s for s in json.load(gzip.open(cfg / "skills.json.gz", "rt", encoding="utf-8"))}
    bym = json.loads((Path(src) / "data/morimens/dzone-info/by-monster.json").read_text(encoding="utf-8"))
    dz = {}
    for v in bym.values():
        dz.setdefault(v["tid"], []).append(v)

    def skill_entry(sid):
        s = skills.get(sid)
        if not s:
            return {"id": sid, "intent": "Intent_Unknown", "label": "特殊行动", "icon": "014", "name": "", "target": "", "desc": ""}
        c = s["config"]
        t = intent_of(s.get("types"))
        name = (c.get("Name") or "").split("|", 1)[-1] if c.get("Name") else ""
        return OrderedDict([("id", sid), ("name", name), ("intent", t), ("label", INTENTS[t][0]), ("icon", INTENTS[t][1]),
                            ("target", TARGETS.get(c.get("CmdTarget"), c.get("CmdTarget") or "")),
                            ("para", c.get("Para", "")), ("desc", clean_desc(s.get("description")))])

    used, mons = set(), OrderedDict()
    for m in sorted(monsters, key=lambda x: x["id"]):
        c = m["config"]
        init = seq(c.get("InitSkillList"))
        cycles = [seq(c[k]) for k in sorted((k for k in c if k.startswith("CycleSkillList")), key=lambda k: int(k[14:]))]
        if not init and not cycles:
            continue
        ids = list(dict.fromkeys(init + [x for cy in cycles for x in cy] + m.get("skillIds", [])))
        used.update(ids)
        e = OrderedDict([("name", m["name"]), ("class", CLASS.get(c.get("MonsterClass"), c.get("MonsterClass") or "")),
                         ("size", c.get("BodySize", "")), ("desc", m.get("description", "")),
                         ("opening", init), ("cycles", cycles)])
        if m["id"] in dz:
            e["levels"] = [OrderedDict([("period", r["period"]), ("rows", [OrderedDict([("lv", x["lv"]), ("hp", x["hp"]), ("atk", x["atk"]),
                                                                                          ("def", x["def"]), ("values", x["a"])]) for x in r["rows"]])])
                           for r in dz[m["id"]]]
        mons[str(m["id"])] = e
    sk = OrderedDict((str(i), skill_entry(i)) for i in sorted(used))
    return OrderedDict([
        ("schema", 1),
        ("note", "行动意图：opening=首轮行动，cycles=循环1..n（打完 opening 后依次轮换）。skills 里 label 是游戏内意图名，icon 对应 resource/image/intent/intent_<icon>.png；"
                 "values[技能id]=[数值, 次数, ...]（融灾怪物按关卡等级）。desc 中 [ArgK] 是第 K 个参数（伤害/次数/层数），用 values 填入。"),
        ("intents", OrderedDict((k, {"label": v[0], "icon": v[1]}) for k, v in INTENTS.items())),
        ("counts", {"monsters": len(mons), "skills": len(sk), "with_levels": sum(1 for m in mons.values() if "levels" in m)}),
        ("monsters", mons), ("skills", sk)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--icons", help="directory with intent_NNN.png to copy into resource/image/intent")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.icons:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(Path(a.icons).glob("intent_*.png")):
            shutil.copyfile(p, ICON_DIR / p.name)
    text = json.dumps(build(a.src), ensure_ascii=False, indent=1) + "\n"
    missing = [i for _, i in INTENTS.values() if not (ICON_DIR / f"intent_{i}.png").exists()]
    if a.check:
        bad = (not OUT.exists() or OUT.read_text(encoding="utf-8") != text)
        print("monster intents " + ("out of date" if bad else "up to date") + (f"; missing icons {sorted(set(missing))}" if missing else ""))
        return 1 if bad or missing else 0
    OUT.write_text(text, encoding="utf-8")
    d = json.loads(text)
    print(d["counts"], "missing icons", sorted(set(missing)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
