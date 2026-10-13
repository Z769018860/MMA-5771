"""Monster action intents (意图) in the game's format, from resource/map_data/monster_intents.json.

    python -m morimens_logic.intents 撕裂维度之足 [--level 99]

首轮行动 / 循环 n lines: every step shows the intent label (and icon file), skill name, target and the official
description with the damage / hit count filled in for a level (融灾 monsters carry per-level values).
"""

import argparse
import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "resource" / "map_data" / "monster_intents.json"
ICON_DIR = ROOT / "resource" / "image" / "intent"


@lru_cache(maxsize=1)
def load():
    return json.loads(DATA.read_text(encoding="utf-8"))


def find(name_or_id):
    d = load()["monsters"]
    if str(name_or_id) in d:
        return [(str(name_or_id), d[str(name_or_id)])]
    return [(k, v) for k, v in d.items() if v["name"] == name_or_id]


def fill(desc, args):
    """[ArgK] -> value of the K-th argument (left as 'X' when the level is unknown)."""
    def rep(m):
        k = int(m.group(1)) - 1
        return str(args[k]) if args and k < len(args) else "X"
    return re.sub(r"\[Arg(\d)\]", rep, desc)


def level_row(monster, level=None):
    rows = [r for p in monster.get("levels", []) for r in p["rows"]]
    if not rows:
        return None
    if level is None:
        return max(rows, key=lambda r: r["lv"])
    return min(rows, key=lambda r: abs(r["lv"] - level))


def step(sid, monster, row):
    d = load()
    s = d["skills"][str(sid)]
    args = (row or {}).get("values", {}).get(str(sid))
    return {"id": sid, "name": s["name"] or "(无名称)", "label": s["label"], "icon": ICON_DIR / f"intent_{s['icon']}.png",
            "target": s["target"], "desc": fill(s["desc"], args), "args": args}


def sequences(monster, level=None):
    """[(title, [step, ...]), ...] — 首轮行动 then 循环 1..n."""
    row = level_row(monster, level)
    out = [("首轮行动", [step(i, monster, row) for i in monster["opening"]])]
    out += [(f"循环 {n}", [step(i, monster, row) for i in cy]) for n, cy in enumerate(monster["cycles"], 1)]
    return out


def format_monster(monster, level=None):
    row = level_row(monster, level)
    head = f"{monster['name']}（{monster['class']}）" + (f" Lv{row['lv']} 攻击力 {row['atk']} 防御 {row['def']} 生命 {row['hp']}" if row else "")
    lines = [head, "行动意图（按回合顺序）"]
    for title, steps in sequences(monster, level):
        lines.append(f"  {title}: " + " → ".join(f"[{s['label']}]{s['name']}" for s in steps))
    lines.append("技能详情")
    seen = set()
    for _, steps in sequences(monster, level):
        for s in steps:
            if s["id"] not in seen:
                seen.add(s["id"])
                lines.append(f"  {s['name']} | {s['label']} | {s['target'] or '—'} | {s['desc']}")
    return "\n".join(lines)


def html_page(only_levels=True):
    """Static page like the wiki's 行动意图 block: icons, step arrows, skill table. Images are relative to docs/."""
    from html import escape
    d = load()
    rel = "../resource/image/intent/"
    legend = "".join(f'<span class="lg"><img src="{rel}intent_{v["icon"]}.png">{escape(v["label"])}</span>'
                     for k, v in d["intents"].items() if k not in ("Intent_Burst2", "Intent_Burst3"))
    out = []
    for mid, m in d["monsters"].items():
        if only_levels and "levels" not in m:
            continue
        blocks = []
        for title, steps in sequences(m):
            chips = '<span class="ar">→</span>'.join(
                f'<span class="chip"><img src="{rel}intent_{d["skills"][str(x["id"])]["icon"]}.png"><b>{escape(x["name"])}</b>'
                f'<small>{escape(x["label"])}</small></span>' for x in steps)
            blocks.append(f'<div class="row"><span class="t">{escape(title)}</span>{chips}</div>')
        rows = "".join(f'<tr><td>{escape(x["name"])}</td><td><img src="{rel}intent_{d["skills"][str(x["id"])]["icon"]}.png"> {escape(x["label"])}</td>'
                       f'<td>{escape(x["target"] or "—")}</td><td>{escape(x["desc"])}</td></tr>'
                       for x in {y["id"]: y for _, st in sequences(m) for y in st}.values())
        row = level_row(m)
        meta = f' Lv{row["lv"]} 攻击力 {row["atk"]} 防御 {row["def"]} 生命 {row["hp"]}' if row else ""
        out.append(f'<section><h2>{escape(m["name"])} <small>{escape(m["class"])}{meta}</small></h2><p>{escape(m["desc"])}</p>'
                   f'{"".join(blocks)}<table><tr><th>技能</th><th>类型</th><th>目标</th><th>官方描述</th></tr>{rows}</table></section>')
    css = ("body{background:#0b1220;color:#dbe4f0;font:14px/1.5 sans-serif;max-width:1000px;margin:auto;padding:16px}"
           "section{border:1px solid #243049;border-radius:8px;padding:12px;margin:14px 0;background:#0f1a2e}"
           "h2 small{font-size:12px;color:#8aa;margin-left:8px}.row{margin:6px 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}"
           ".t{width:64px;color:#9ab}.chip{display:inline-flex;align-items:center;gap:6px;border:1px solid #334;border-radius:8px;padding:3px 8px}"
           ".chip img{height:26px}.chip small{color:#8aa}.ar{color:#678}table{width:100%;border-collapse:collapse;margin-top:8px}"
           "td,th{border-top:1px solid #243049;padding:4px 6px;text-align:left;vertical-align:top}td img{height:18px;vertical-align:middle}"
           ".lg{display:inline-flex;align-items:center;gap:4px;margin:0 12px 6px 0}.lg img{height:22px}")
    return (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>怪物行动意图</title><style>{css}</style><h1>怪物行动意图</h1><div>{legend}</div>{"".join(out)}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", help="write the page for all monsters that carry level values to this path")
    ap.add_argument("monster", nargs="?", help="monster name or id")
    ap.add_argument("--level", type=int)
    a = ap.parse_args()
    if a.html:
        Path(a.html).write_text(html_page(), encoding="utf-8")
        return
    found = find(a.monster)
    if not found:
        raise SystemExit(f"no monster {a.monster}")
    for _, m in found:
        print(format_monster(m, a.level))


if __name__ == "__main__":
    main()
