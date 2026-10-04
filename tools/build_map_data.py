"""Rebuild resource/map_data/maps.json from the map pictures (slow: ~20 min for all maps).

    python tools/build_map_data.py --dir tools/resource/reference_maps/images \
        --dir resource/reference_maps_special/images --out resource/map_data/maps.json

File names: main chapters '<chapter>-<stage>.jpg'; event maps '<activity><NN>_map.jpg'.
After this the images are no longer needed at runtime: maps.json + templates are enough.
"""
import argparse
import collections
import json
import re
from pathlib import Path

import cv2
import numpy as np

import recognize_map_tiles as R

KIND = {**{n: "意识潜游" for n in ["骑士的愿望", "如歌的雕琢", "血与沙", "扭曲核心", "苍白后裔", "一步之遥", "诸事如常", "燃烧的群宴"]},
        **{n: "特遣记录" for n in ["蔷薇礼赞", "狩猎愉快！"]}}


MANUAL = json.loads((Path(__file__).resolve().parent.parent / "resource/map_data/manual_fixes.json").read_text(encoding="utf-8"))


def meta(name):
    m = re.fullmatch(r"(\d)-(\d+)", name)
    if m:
        return {"series": "忘却篇", "chapter": int(m[1]), "stage": int(m[2])}
    m = re.fullmatch(r"(.+?)(\d+)", name)
    return {"series": KIND.get(m[1], "特殊活动"), "activity": m[1], "stage": int(m[2])}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", action="append", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("resource/map_data/maps.json"))
    args = ap.parse_args()
    templates, maps = R.load_templates(), {}
    for folder in args.dir:
        for path in sorted(folder.glob("*.[jp][pn]g")):
            name = path.stem.replace("_map", "")
            image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
            tiles = [t for t in R.build_tiles(image, R.detect_icons(image, templates))]
            fixes = [f for f in MANUAL["remove"] if f["map"] == name]
            tiles = [t for t in tiles if not any(t["row"] == f["row"] and t["col"] == f["col"] and t["type"] == f["type"] for f in fixes)]
            for a in (x for x in MANUAL.get("annotate", []) if x["map"] == name):
                for t in tiles:
                    if t["row"] == a["row"] and t["col"] == a["col"]:
                        t["hidden_event"] = a["hidden_event"]
            maps[name] = {"id": name, **meta(name), "image_size": [image.shape[1], image.shape[0]],
                          "tile_count": len(tiles), "counts": dict(collections.Counter(t["type"] for t in tiles)),
                          "tiles": [{k: t[k] for k in ("type", "island", "row", "col", "x", "y", "hidden_event") if k in t} for t in tiles]}
            print(name, len(tiles), flush=True)
    args.out.write_text(json.dumps({"maps": maps}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


if __name__ == "__main__":
    main()
