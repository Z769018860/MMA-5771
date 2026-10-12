"""Import every map of the game client config dump (repo Z769018860/qdby_chinese) into resource/map_data/client/.

    python tools/import_client_maps.py <path to a qdby_chinese checkout> [--check]

Source files (read as plain JSON, nothing from that repo is executed):
  data/morimens/local-config/{maps,nodes,node-types}.json.gz   raw tables exported from the client (README there)
  data/morimens/maps/{index,train}.json                        stage index (names, categories) and the 记忆回廊 route

Output (all deterministic, safe to re-run):
  client/node_types.json   80 client node types -> our tile type, with the client flags
  client/nodes.json        node id -> [type id, battle config id]
  client/maps.json         map id -> {stages, cn, w, g}; g = 8 rows (top row first = client y 8) x w cells:
                           0 = wall (虚无), null = plain floor (the client stores no node), int = node id, [ids] = variants
  client/stages.json       stage id -> name / category / level / map ids / linear node sequence
  client/train.json        记忆回廊「疾驰的欢愉专列」 route (copied)
  client/SOURCE.md         provenance
  maps_client.json         the same maps converted to our planner model (island/row/col lattice, tile types)

Grid facts (verified on 8-2 against the screenshot recognition and the live run): 8 rows y=1..8 (y=8 is the bottom),
columns x=1..13; odd rows are shifted right by half a tile; lattice col = 2*x + (y odd), row = -y; a cell missing from
the table is plain floor, node 虚无 (type 18393) is a wall.
"""

import argparse
import gzip
import json
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "resource" / "map_data" / "client"
CONVERTED = ROOT / "resource" / "map_data" / "maps_client.json"
WALL_TYPE = 18393
START_TYPE = 18402
ROWS = 8

# client node type name -> our tile type. Everything named "银钥将你指引向此地…" (resonance events) stays an event.
NAME_TO_OURS = {
    "战斗": "battle", "精英": "elite", "最终战": "final_battle", "事件": "event", "剧情": "story", "开始": "player",
    "联络点": "contact", "探照灯": "searchlight", "锈蚀门扉": "locked_door", "锈蚀钥匙": "rusty_key", "隧道": "tunnel",
    "单行密道": "oneway_in", "密道出口": "secret_exit", "幻象": "illusion", "隐藏奖励": "extract", "黑印": "blackseal",
    "造物": "artifact", "银芯": "silver_core", "影池": "shadow_pool", "恶沼": "swamp", "监察点": "checkpoint",
    "羁押点": "detention", "审查会探员": "inquisitor", "入学仪式": "enrollment", "古怪脓疱": "strange_cyst",
    "蜂蜜甜酒": "honey_wine", "未完的雕像": "unfinished_statue", "善意的礼物": "kind_gift", "孕育之母": "mother_of_brood",
    "代行之仪": "proxy_rite", "纯白之帆": "white_sail", "虚无": "wall",
    "融痕": "meltmark", "定制造物融痕": "meltmark", "定制刻印融痕": "meltmark", "造物融痕": "meltmark", "刻印融痕": "meltmark",
    "夏里奇市集": "meltmark", "灰烬遗迹": "meltmark",
    "随机战斗": "battle", "随机事件": "event", "随机节点": "random",
}
NEIGH = ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1))


def load_gz(path):
    return json.loads(gzip.open(path).read().decode("utf-8"))


def dump(path, obj, indent=None):
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=indent, separators=None if indent else (",", ":")) + "\n"
    path.write_bytes(text.encode("utf-8"))


def read_source(src):
    cfg = src / "data" / "morimens" / "local-config"
    maps = load_gz(cfg / "maps.json.gz")
    nodes = load_gz(cfg / "nodes.json.gz")
    types = load_gz(cfg / "node-types.json.gz")
    index = json.loads((src / "data" / "morimens" / "maps" / "index.json").read_text(encoding="utf-8"))
    train = json.loads((src / "data" / "morimens" / "maps" / "train.json").read_text(encoding="utf-8"))
    return maps, nodes, types, index, train


def commit_of(src):
    try:
        return subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def our_type(type_id, names):
    name = names.get(type_id, "")
    if name in NAME_TO_OURS:
        return NAME_TO_OURS[name]
    return "event"          # resonance events: 银钥将你指引向此地…


def build_tables(maps, nodes, types, index):
    names = {t["id"]: t["name"] for t in types}
    node_types = []
    for t in sorted(types, key=lambda t: t["id"]):
        c = t.get("config", {})
        node_types.append({"id": t["id"], "name": t["name"], "desc": t["description"], "ours": our_type(t["id"], names),
                           "block": c.get("Block"), "trigger": c.get("Trigger"), "cn": c.get("CnID")})
    nb = {n["id"]: n for n in nodes}
    used = {v["nodeId"] for m in maps for c in m["cells"] for v in c["variants"]}
    node_table = {str(i): [nb[i]["typeId"], nb[i].get("battleConfigId") or 0] for i in sorted(used) if i in nb}
    cmaps = {}
    for m in sorted(maps, key=lambda m: m["id"]):
        width = max(c["x"] for c in m["cells"])
        cell = {(c["x"], c["y"]): sorted(c["variants"], key=lambda v: v["variant"]) for c in m["cells"]}
        grid = []
        for y in range(ROWS, 0, -1):
            row = []
            for x in range(1, width + 1):
                vs = cell.get((x, y))
                if vs is None:
                    row.append(None)
                else:
                    ids = [v["nodeId"] for v in vs]
                    types_ = [nb[i]["typeId"] if i in nb else 0 for i in ids]
                    if all(t == WALL_TYPE for t in types_):
                        row.append(0)
                    else:
                        row.append(ids[0] if len(ids) == 1 else ids)
            grid.append(row)
        cmaps[str(m["id"])] = {"stages": sorted(m.get("stageIds") or []), "cn": m.get("cnId"), "w": width, "g": grid}
    stages = {}
    for s in index["stages"]:
        if s.get("m") or s.get("q"):
            stages[str(s["id"])] = {k: v for k, v in (("n", s.get("n")), ("c", s.get("c")), ("s", s.get("s")), ("lv", s.get("lv")), ("cn", s.get("cn")),
                                                    ("m", s.get("m")), ("q", s.get("q"))) if v not in (None, [])}
    return node_types, node_table, cmaps, stages


def convert(cmaps, node_table, node_types, stages):
    """Client grid -> our lattice model. Walls are not tiles; plain floor is."""
    names = {t["id"]: t for t in node_types}
    out = {}
    for mid, m in cmaps.items():
        cells = {}
        for r, row in enumerate(m["g"]):
            y = ROWS - r
            for i, v in enumerate(row):
                x = i + 1
                if v == 0:
                    continue
                if v is None:
                    cells[(x, y)] = ("plain", None, [], 0)
                    continue
                ids = v if isinstance(v, list) else [v]
                tids = [node_table[str(n)][0] for n in ids]
                types_ = [names[t]["ours"] for t in tids]
                cells[(x, y)] = (types_[0], ids[0], [t for t in types_[1:] if t != types_[0]], tids[0])
        if not cells:
            continue
        lat = {xy: (-xy[1], 2 * xy[0] + (xy[1] & 1)) for xy in cells}
        r0, c0 = min(v[0] for v in lat.values()), min(v[1] for v in lat.values())
        lat = {xy: (r - r0, c - c0) for xy, (r, c) in lat.items()}
        pos = {v: xy for xy, v in lat.items()}
        island, comp = {}, 0
        for xy in sorted(lat, key=lambda k: lat[k]):
            if xy in island:
                continue
            stack, island[xy] = [xy], comp
            while stack:
                cur = stack.pop()
                r, c = lat[cur]
                for dr, dc in NEIGH:
                    nxt = pos.get((r + dr, c + dc))
                    if nxt is not None and nxt not in island:
                        island[nxt] = comp
                        stack.append(nxt)
            comp += 1
        tiles = []
        for xy in sorted(lat, key=lambda k: (island[k], lat[k])):
            ty, node, alts, tid = cells[xy]
            t = {"type": ty, "island": island[xy], "row": lat[xy][0], "col": lat[xy][1], "cx": xy[0], "cy": xy[1]}
            if node:
                t["node"], t["node_type"] = node, names[tid]["name"]
            if alts:
                t["alts"] = alts
            if ty == "checkpoint":
                t["hidden_event"] = "监察点"           # looks like plain floor on screen (8-2 live)
            tiles.append(t)
        stage_ids = m["stages"]
        out[mid] = {"id": mid, "stage_ids": stage_ids,
                    "stage_names": [stages[str(s)]["n"] for s in stage_ids if str(s) in stages and stages[str(s)].get("n")],
                    "cn": m["cn"], "tile_count": len(tiles), "counts": dict(sorted(Counter(t["type"] for t in tiles).items())), "tiles": tiles}
    return out


def build(src):
    maps, nodes, types, index, train = read_source(src)
    node_types, node_table, cmaps, stages = build_tables(maps, nodes, types, index)
    converted = convert(cmaps, node_table, node_types, stages)
    sha = commit_of(src)
    source = (f"# 游戏客户端地图数据（来自 Z769018860/qdby_chinese）\n\n提交：`{sha}`；导出时间 2026-10-12/13（Steam 客户端运行时已加载的 Lua 配置，只读导出，由仓库维护者提供）。\n\n"
              "由 `python tools/import_client_maps.py <qdby_chinese 路径>` 生成，原始表在该仓库 `data/morimens/local-config/`，说明见那里的 README。\n\n"
              "文件：\n- `node_types.json`：80 种节点类型 → 本项目的格子类型（`ours`）与客户端标志。\n- `nodes.json`：节点 id → [类型 id, 战斗配置 id]。\n"
              "- `maps.json`：每张地图的 8 行 × 13 列格子（0=墙/虚无，null=空地，整数=节点 id，列表=该格有多个随机变体）。\n"
              "- `stages.json`：关卡 id → 名称/分类/等级/地图 id/线性节点序列。\n- `train.json`：记忆回廊「疾驰的欢愉专列」路线。\n"
              "- 上一级 `maps_client.json`：转换成规划器使用的蜂窝格点（island/row/col）。\n\n"
              "坐标：行 y=1..8（y=8 在最下方），列 x=1..13，奇数行向右错半格；格点 col = 2*x + (y 为奇数)，row = -y。配置里没有的格子是空地，节点「虚无」是墙。"
              "该规律在 8-2 上与截图识别、实机结果逐格核对过。\n")
    files = {OUT / "node_types.json": (node_types, 1), OUT / "nodes.json": (node_table, None), OUT / "maps.json": (cmaps, None),
             OUT / "stages.json": (stages, None), OUT / "train.json": (train, None),
             CONVERTED: ({"schema": {"note": "由 tools/import_client_maps.py 从游戏客户端配置转换：墙不是格子，空地是 plain；cx/cy 是客户端网格坐标，"
                                             "node 是节点 id，alts 是该格其他随机变体的类型。row/col 同 maps.json（相邻 (0,±2)/(±1,±1)）。",
                                    "source": sha}, "maps": converted}, None)}
    return files, source


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files, source = build(args.source)
    OUT.mkdir(parents=True, exist_ok=True)
    texts = {p: json.dumps(o, ensure_ascii=False, sort_keys=True, indent=ind, separators=None if ind else (",", ":")) + "\n" for p, (o, ind) in files.items()}
    texts[OUT / "SOURCE.md"] = source
    if args.check:
        stale = [str(p) for p, t in texts.items() if not p.is_file() or p.read_text(encoding="utf-8") != t]
        if stale:
            sys.exit("out of date: " + ", ".join(stale))
        print("client map data is up to date")
        return
    for p, t in texts.items():
        p.write_bytes(t.encode("utf-8"))
    conv = files[CONVERTED][0]["maps"]
    print(f"{len(conv)} maps, {sum(m['tile_count'] for m in conv.values())} tiles; " +
          ", ".join(f"{p.name} {p.stat().st_size // 1024} KB" for p in texts))


if __name__ == "__main__":
    main()
