"""Read-only preprocessing of a Morimens map screenshot and wiki event cache.

Usage: python tools/preprocess_map.py screenshot.png --wiki ../huiji-events.json --stage 终末交响曲-02
"""

import argparse
import json
import re
from pathlib import Path

import cv2
import numpy as np


def event_catalog(wiki: Path, stage: str) -> list[dict]:
    pages = json.loads(wiki.read_text(encoding="utf-8"))["pages"]
    page = next((p for p in pages if p["title"] == stage + "·剧情"), None)
    if page is None:
        return []
    result = []
    for section in re.split(r"(?=^===事件·)", page["wikitext"], flags=re.M):
        match = re.match(r"===事件·([^=]+)===", section)
        if not match:
            continue
        options = []
        # Only parse the initial options field; nested result tabs contain follow-up choices.
        field = section.split("|事件选项=", 1)
        if len(field) == 2:
            initial = field[1].split("|\n<br>", 1)[0]
            for label, effect in re.findall(r"【([^】]+)】([^|\n]*)", initial):
                effect = re.sub(r"<[^>]+>|&nbsp;|'{2,}", "", effect).strip()
                options.append({"label": label, "effect": effect})
        result.append({"name": match.group(1).strip(), "options": options})
    return result


def candidates(image_path: Path) -> list[dict]:
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError(f"Cannot read {image_path}")
    height, width = image.shape[:2]
    scaled = cv2.resize(image, (1280, 720))
    hsv = cv2.cvtColor(scaled, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (40, 90, 40), (90, 255, 255))
    mask[:120] = 0
    mask[640:] = 0
    n, _, stats, centers = cv2.connectedComponentsWithStats(mask)
    found = []
    for i in range(1, n):
        x, y, w, h, area = map(int, stats[i])
        if area < 500 or w < 35 or h < 25 or not 250 < x < 1100:
            continue
        # A green outlined hex may split into fragments; use its box center.
        cx, cy = x + w / 2, y + h / 2
        found.append({"box": [x, y, w, h], "tap": [round(cx * width / 1280), round(cy * height / 720)], "area": area, "state": "unvisited_candidate"})
    return sorted(found, key=lambda c: -c["area"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("--wiki", type=Path)
    parser.add_argument("--stage", default="终末交响曲-02")
    args = parser.parse_args()
    print(json.dumps({"stage": args.stage, "tiles": candidates(args.screenshot), "events": event_catalog(args.wiki, args.stage) if args.wiki else []}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
