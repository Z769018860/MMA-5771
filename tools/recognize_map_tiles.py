"""Recognise the hex tiles of a Morimens 忘却篇/特遣记录/意识潜游 exploration map.

Input : a map picture (the Huiji wiki *_map.jpg at 3508x1974, or a screenshot scaled
        to the same tile size, see --scale).
Output: JSON list of tiles {type, island, row, col, x, y, score}.

    python tools/recognize_map_tiles.py map.jpg --out tiles.json --debug overlay.jpg

Method
  1. Icon tiles (battle, event, ...): gradient-magnitude template matching against the
     templates in resource/map_data/templates (file name = <type>_<n>.png), then
     non-maximum suppression.
  2. Tiles are grouped into islands and snapped to a hex lattice (row, col; col is in
     half-tile steps, so neighbours differ by (0,+-2) or (+-1,+-1)).
  3. Icon-less tiles (plain, cracked_rock, purple_rift, red_flesh) are found by walking
     the lattice outwards from the icon tiles and classifying the colour/texture.
Tile functions are documented in resource/map_data/tile_types.json.
"""

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "resource" / "map_data" / "templates"
RENAME = {"watcher": "inquisitor"}
DX2, DY, YOFF = 104.0, 182.0, 22  # half tile width, row spacing, icon-bbox -> tile-centre offset (px at 3508 wide)


def feat(gray):
    g = cv2.GaussianBlur(gray, (0, 0), 1.5).astype(np.float32)
    mag = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))
    return np.minimum(mag, 150)


def load_templates(folder=TEMPLATE_DIR):
    out = []
    for path in sorted(folder.glob("*.png")):
        key = RENAME.get(path.stem.rsplit("_", 1)[0], path.stem.rsplit("_", 1)[0])
        img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
        out.append((key, feat(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))[20:170, 25:125]))
    return out


def detect_icons(image, templates, thr=0.64, nms=105):
    f = feat(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    cands = []
    for key, tpl in templates:
        res = cv2.matchTemplate(f, tpl, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(res >= thr)
        cands += [(float(res[y, x]), key, x + tpl.shape[1] // 2, y + tpl.shape[0] // 2) for y, x in zip(ys, xs)]
    integ = cv2.integral(f)

    def energy(x, y, w=50, h=70):  # reject flat regions, where NCC is degenerate
        x0, y0, x1, y1 = max(0, x - w), max(0, y - h), min(f.shape[1] - 1, x + w), min(f.shape[0] - 1, y + h)
        return (integ[y1, x1] - integ[y0, x1] - integ[y1, x0] + integ[y0, x0]) / max(1, (x1 - x0) * (y1 - y0))

    cands = sorted((c for c in cands if energy(c[2], c[3]) > 18), reverse=True)
    out = []
    for score, key, x, y in cands:
        if all((x - o["x"]) ** 2 + (y - o["y"]) ** 2 > nms ** 2 for o in out):
            out.append({"type": key, "score": round(score, 3), "x": int(x), "y": int(y)})
    return out


def classify_site(hsv, gray, cx, cy):
    """Classify an icon-less lattice site: plain / cracked_rock / purple_rift / red_flesh / unknown_icon / None."""
    h, w = gray.shape
    if not (135 < cx < w - 135 and 135 < cy < h - 135):
        return None
    yy, xx = np.ogrid[-60:61, -60:61]
    disc = (xx ** 2 + yy ** 2) <= 60 ** 2
    gp = gray[int(cy) - 60:int(cy) + 61, int(cx) - 60:int(cx) + 61][disc]
    hp = hsv[int(cy) - 60:int(cy) + 61, int(cx) - 60:int(cx) + 61][disc]
    mean, dark = gp.mean(), (gp < 45).mean()
    if dark > 0.6 or mean < 45:
        return None
    ay, ax = np.ogrid[-135:136, -135:136]
    ring = ((ax ** 2 + ay ** 2) >= 100 ** 2) & ((ax ** 2 + ay ** 2) <= 135 ** 2)
    if (gray[int(cy) - 135:int(cy) + 136, int(cx) - 135:int(cx) + 136][ring] < 35).mean() < 0.08:
        return None  # tiles sit inside the black fog
    hue, sat, val = hp[:, 0], hp[:, 1], hp[:, 2]
    if (((hue < 10) | (hue > 165)) & (sat > 120) & (val > 110)).mean() > 0.45:
        return "red_flesh"
    if ((hue >= 100) & (hue <= 132) & (sat >= 72) & (sat <= 160) & (val > 70)).mean() > 0.45:
        return "purple_rift"
    m_sat, m_hue, m_val, lines = np.median(sat), np.median(hue), np.median(val), (gp < 70).mean()
    if (gp > np.median(gp) + 45).mean() > 0.06 and m_sat >= 15 and lines < 0.15 and mean > 85:
        return "unknown_icon"  # an icon exists but no template matched
    if 0.15 < lines < 0.5 and 85 < m_val < 165 and gp.std() > 30 and m_sat < 50:
        return "cracked_rock"
    if lines < 0.12 and m_sat >= 22 and 20 <= m_hue <= 75 and mean > 85:
        return "plain"
    return None


def build_tiles(image, icons):
    hsv, gray = cv2.cvtColor(image, cv2.COLOR_BGR2HSV), cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    n = len(icons)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in range(i + 1, n):
            if (icons[i]["x"] - icons[j]["x"]) ** 2 + (icons[i]["y"] - icons[j]["y"]) ** 2 < (2.3 * DY) ** 2:
                parent[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    tiles = []
    for island, (_, idx) in enumerate(sorted(groups.items(), key=lambda g: min(icons[i]["x"] for i in g[1]))):
        xa, ya = icons[idx[0]]["x"], icons[idx[0]]["y"]
        occupied = {}
        for i in idx:
            col, row = int(round((icons[i]["x"] - xa) / DX2)), int(round((icons[i]["y"] - ya) / DY))
            if (col + row) % 2:
                col += 1 if (icons[i]["x"] - xa) / DX2 > col else -1
            occupied[(row, col)] = icons[i]
        ox = xa + np.median([p["x"] - (xa + c * DX2) for (r, c), p in occupied.items()])
        oy = ya + np.median([p["y"] - (ya + r * DY) for (r, c), p in occupied.items()])
        found, frontier, seen = {}, list(occupied), set(occupied)
        for _ in range(400):
            if not frontier:
                break
            r, c = frontier.pop()
            for dr, dc in ((0, 2), (0, -2), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                key = (r + dr, c + dc)
                if key in seen:
                    continue
                seen.add(key)
                cx, cy = ox + key[1] * DX2, oy + key[0] * DY + YOFF
                kind = classify_site(hsv, gray, cx, cy)
                if kind:
                    found[key] = (kind, cx, cy)
                    frontier.append(key)
        r0 = min(k[0] for k in list(occupied) + list(found))
        c0 = min(k[1] for k in list(occupied) + list(found))
        for (r, c), p in occupied.items():
            tiles.append({"type": RENAME.get(p["type"], p["type"]), "island": island, "row": r - r0, "col": c - c0,
                          "x": int(ox + c * DX2), "y": int(oy + r * DY + YOFF), "score": p["score"]})
        for (r, c), (kind, cx, cy) in found.items():
            tiles.append({"type": kind, "island": island, "row": r - r0, "col": c - c0,
                          "x": int(cx), "y": int(cy), "score": None})
    keep = []  # islands may both claim the same gap tile
    for t in sorted(tiles, key=lambda t: t["score"] is None):
        if all((t["x"] - k["x"]) ** 2 + (t["y"] - k["y"]) ** 2 > 90 ** 2 for k in keep):
            keep.append(t)
    return sorted(keep, key=lambda t: (t["island"], t["row"], t["col"]))


def recognize(image, templates=None, scale=1.0):
    if scale != 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return build_tiles(image, detect_icons(image, templates or load_templates()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--debug", type=Path, help="write an overlay picture")
    ap.add_argument("--scale", type=float, default=1.0, help="resize factor so a tile is ~208 px wide")
    args = ap.parse_args()
    image = cv2.imdecode(np.fromfile(str(args.image), np.uint8), cv2.IMREAD_COLOR)
    if args.scale != 1.0:
        image = cv2.resize(image, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_CUBIC)
    tiles = build_tiles(image, detect_icons(image, load_templates()))
    text = json.dumps(tiles, ensure_ascii=False, indent=1)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.debug:
        for t in tiles:
            cv2.circle(image, (t["x"], t["y"]), 70, (0, 255, 0), 6)
            cv2.putText(image, t["type"][:8], (t["x"] - 70, t["y"] + 100), 0, 1.6, (0, 0, 255), 4)
        cv2.imwrite(str(args.debug), cv2.resize(image, None, fx=0.4, fy=0.4))


if __name__ == "__main__":
    main()
