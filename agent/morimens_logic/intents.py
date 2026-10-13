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
    """[ArgK] -> value of the K-th argument (left as 'X' when it is unknown or depends on the battle state)."""
    def rep(m):
        k = int(m.group(1)) - 1
        return str(args[k]) if args and k < len(args) and args[k] is not None else "X"
    return re.sub(r"\[Arg(\d)\]", rep, desc)


_SAFE = re.compile(r"^[0-9.+\-*/() ]*$")


def evaluate(para, atk, df=None):
    """Skill Para 'BattleAtkForce*0.35,3' -> [886, 3]. Only plain arithmetic with BattleAtkForce / BattleDefForce is
    evaluated; arguments that depend on states, hp or cards give None."""
    out = []
    for part in str(para if para is not None else "").split(","):
        expr = part.strip()
        expr = expr.replace("math.ceil", "").replace("math.floor", "")
        if "BattleAtkForce" in expr:
            expr = expr.replace("BattleAtkForce", f"({atk})")
        if "BattleDefForce" in expr:
            if df is None:
                out.append(None)
                continue
            expr = expr.replace("BattleDefForce", f"({df})")
        layer = re.sub(r"(?:CmdCaster|PlayerRole|FrontEnemy)\.GetStateLayer\(\d+\)", "层数", expr)
        if layer != expr and _SAFE.match(layer.replace("层数", "")):
            out.append(layer)  # depends on a state's layers: shown symbolically, e.g. "层数+5"
            continue
        if not expr or not _SAFE.match(expr):
            out.append(None)
            continue
        try:
            v = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 - validated: digits and + - * / ( ) only
        except Exception:
            out.append(None)
            continue
        out.append(round(v) if abs(v - round(v)) > 1e-9 else int(round(v)))
    return out


def level_row(monster, level=None):
    """Official 融灾 rows when the monster has them, otherwise the template estimate (row['estimated'] is True)."""
    rows = [dict(r, estimated=False) for p in monster.get("levels", []) for r in p["rows"]]
    if not rows:
        rows = [dict(r, estimated=True) for r in monster.get("template_rows", [])]
    if not rows:
        return None
    if level is None:
        return max(rows, key=lambda r: r["lv"])
    return min(rows, key=lambda r: abs(r["lv"] - level))


def step(sid, monster, row):
    d = load()
    s = d["skills"][str(sid)]
    args = (row or {}).get("values", {}).get(str(sid))
    if args is None and row:
        args = evaluate(s["para"], row["atk"], None if row.get("estimated") else row["def"])
    value = "—"
    if args and "Attack" in s["intent"] and args[0] is not None:
        times = args[1] if len(args) > 1 and args[1] is not None else 1
        value = f"伤害 {args[0]}" + (f" × {times}" if times != 1 else "")
    return {"id": sid, "value": value, "name": s["name"] or "(无名称)", "label": s["label"], "icon": ICON_DIR / f"intent_{s['icon']}.png",
            "target": s["target"], "desc": fill(s["desc"], args), "args": args}


def sequences(monster, level=None):
    """[(title, [step, ...]), ...] — 首轮行动 then 循环 1..n."""
    row = level_row(monster, level)
    out = [("首轮行动", [step(i, monster, row) for i in monster["opening"]])]
    out += [(f"循环 {n}", [step(i, monster, row) for i in cy]) for n, cy in enumerate(monster["cycles"], 1)]
    return out


def format_monster(monster, level=None):
    row = level_row(monster, level)
    head = f"{monster['name']}（{monster['class']}）" + (
        f" Lv{row['lv']} 攻击力 {row['atk']} 防御 {row['def']} 生命 {row['hp']}" + ("（按关卡数值模板估算）" if row["estimated"] else "") if row else "")
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


PAGES = (("boss", "首领", ("首领",)), ("elite", "精英", ("精英",)), ("common", "普通", ("普通",)))


def html_page(classes=("首领", "精英", "普通"), title="怪物行动意图", nav=""):
    """Static page in the format of the wiki's 融灾 monster block: header (等级/攻击力/防御/生命), 行动意图 (按回合顺序)
    with icons, 技能详情 table (技能 / 类型 / 目标 / 数值 / 官方描述). Images are relative to docs/monster_intents/."""
    from html import escape
    d = load()
    rel = "../../resource/image/intent/"
    img = lambda sid: f'<img src="{rel}intent_{d["skills"][str(sid)]["icon"]}.png" alt="">'
    legend = "".join(f'<span class="lg"><img src="{rel}intent_{v["icon"]}.png" alt="">{escape(v["label"])}</span>'
                     for k, v in d["intents"].items() if k not in ("Intent_Burst2", "Intent_Burst3"))
    out = []
    for mid, m in d["monsters"].items():
        if m["class"] not in classes:
            continue
        row = level_row(m)
        meta = (f'<div class="st"><span>等级 <b>{row["lv"]}</b></span><span>攻击力 <b>{row["atk"]}</b></span>'
                f'<span>防御 <b>{row["def"]}</b></span><span>生命 <b>{row["hp"]:,}</b></span>'
                + ('<em>按关卡数值模板估算</em>' if row["estimated"] else '<em>融灾官方数值</em>') + '</div>') if row else ""
        seqs = sequences(m)
        blocks = []
        for t, steps in seqs:
            chips = '<span class="ar">→</span>'.join(
                f'<span class="chip">{img(x["id"])}<span><b>{escape(x["name"])}</b><small>{escape(x["label"])}'
                f'{" · " + escape(x["value"]) if x["value"] != "—" else ""}</small></span></span>' for x in steps)
            blocks.append(f'<div class="row"><span class="t">{escape(t)}</span>{chips}</div>')
        uniq = {y["id"]: y for _, st in seqs for y in st}.values()
        rows = "".join(f'<tr><th>{escape(x["name"])}</th><td>{img(x["id"])} {escape(x["label"])}</td><td>{escape(x["target"] or "—")}</td>'
                       f'<td>{escape(x["value"])}</td><td>{escape(x["desc"])}</td></tr>' for x in uniq)
        out.append(f'<details id="m{mid}"><summary><b>{escape(m["name"])}</b> <small>{escape(m["class"])} · #{mid}</small></summary>'
                   f'<p class="ds">{escape(m["desc"])}</p>{meta}<h4>行动意图（按回合顺序）</h4>{"".join(blocks)}<h4>技能详情</h4>'
                   f'<table><tr><th>技能</th><th>类型</th><th>目标</th><th>数值</th><th>官方描述</th></tr>{rows}</table></details>')
    css = ("body{background:#0b1220;color:#dbe4f0;font:14px/1.5 sans-serif;max-width:1040px;margin:auto;padding:16px}a{color:#7fb2ff}"
           "details{border:1px solid #243049;border-radius:8px;padding:8px 12px;margin:8px 0;background:#0f1a2e}summary{cursor:pointer}"
           "summary small{color:#8aa;margin-left:8px}.ds{color:#a9b8cc}.st span{margin-right:16px}.st em{color:#789;font-size:12px}"
           ".row{margin:6px 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}.t{width:64px;color:#9ab}"
           ".chip{display:inline-flex;align-items:center;gap:6px;border:1px solid #334;border-radius:8px;padding:3px 8px;background:#101c33}"
           ".chip img{height:28px}.chip b{display:block;line-height:1.2}.chip small{color:#8aa}.ar{color:#678}h4{margin:12px 0 4px;color:#e6c78a}"
           "table{width:100%;border-collapse:collapse}td,th{border-top:1px solid #243049;padding:4px 6px;text-align:left;vertical-align:top}"
           "td img{height:18px;vertical-align:middle}.lg{display:inline-flex;align-items:center;gap:4px;margin:0 12px 6px 0}.lg img{height:22px}")
    return (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><style>{css}</style><h1>{escape(title)}</h1><p>{nav}</p><div>{legend}</div>{"".join(out)}')


def write_pages(out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    d = load()
    count = {c: sum(1 for m in d["monsters"].values() if m["class"] == c) for _, c, _ in PAGES}
    nav = " · ".join(f'<a href="{k}.html">{c}（{count[c]}）</a>' for k, c, _ in PAGES)
    (out_dir / "index.html").write_text(html_page(("首领",), "怪物行动意图", nav), encoding="utf-8")
    for k, c, cl in PAGES:
        (out_dir / f"{k}.html").write_text(html_page(cl, f"怪物行动意图 · {c}", nav), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", metavar="DIR", help="write index/boss/elite/common pages to this directory (docs/monster_intents)")
    ap.add_argument("monster", nargs="?", help="monster name or id")
    ap.add_argument("--level", type=int)
    a = ap.parse_args()
    if a.html:
        write_pages(a.html)
        return
    found = find(a.monster)
    if not found:
        raise SystemExit(f"no monster {a.monster}")
    for _, m in found:
        print(format_monster(m, a.level))


if __name__ == "__main__":
    main()
