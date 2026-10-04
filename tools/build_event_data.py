"""Extract factual event choices from a HuijiWiki wikitext cache.

Usage: python tools/build_event_data.py --wiki path/to/huiji-events.json
The cache is not bundled; output contains short labels and structured effects,
not the wiki's narrative text. Attribution is retained per event.
"""

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "resource/map_data/events.json"
EVENT_HEADING = re.compile(r"(?m)^===事件·([^=]+)===$")
MAP_FIELD = re.compile(r"(?m)^\|地图=([^\r\n}]+)")


def template_at(text: str, start: int) -> str:
    """Return one balanced MediaWiki template, including nested templates."""
    if text[start:start + 2] != "{{":
        return ""
    depth = 0
    i = start
    while i < len(text) - 1:
        if text[i:i + 2] == "{{":
            depth += 1
            i += 2
        elif text[i:i + 2] == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return text[start:i]
        else:
            i += 1
    return ""


def top_fields(template: str) -> list[str]:
    fields, current, depth, links, i = [], [], 0, 0, 0
    while i < len(template):
        pair = template[i:i + 2]
        if pair == "{{":
            depth += 1
            current.append(pair)
            i += 2
        elif pair == "}}":
            depth -= 1
            current.append(pair)
            i += 2
        elif pair == "[[":
            links += 1
            current.append(pair)
            i += 2
        elif pair == "]]":
            links -= 1
            current.append(pair)
            i += 2
        elif template[i] == "|" and depth == 1 and links == 0:
            fields.append("".join(current))
            current = []
            i += 1
        else:
            current.append(template[i])
            i += 1
    fields.append("".join(current))
    return fields


def effects(text: str) -> list[dict]:
    """Extract only explicit outcomes; unknown prose remains unclassified."""
    clean = re.sub(r"<[^>]+>|&nbsp;|'{2,}", "", text)
    clean = re.sub(r"\[\[File:[^]]+\]\]", "", clean)
    clean = re.sub(r"\[\[([^]|]+)\|([^]]+)\]\]", r"\2", clean)
    out = []
    patterns = [
        ("teleport", r"传送至([^，。；\s]+)"),
        ("gain_symptom", r"获得(\d+|x)张[^。]*?症状"),
        ("lose_health", r"失去(\d+|x)点生命"),
        ("heal", r"(?:回复|恢复)(\d+|x)点生命"),
        ("gain_blackseal", r"获得(\d+|x)个?黑印"),
        ("gain_card", r"获得(\d+|x)张[^。]*?卡"),
        ("gain_artifact", r"获得(?:一个|1个|一件|1件)?(?:[^，。]*?)造物"),
        ("gain_key", r"获得[^，。]*?锈蚀钥匙"),
        ("remove_threat", r"移除守卫威胁"),
    ]
    for kind, pattern in patterns:
        for match in re.finditer(pattern, clean):
            result = {"type": kind}
            if match.groups():
                result["value"] = match.group(1)
            out.append(result)
    return out


def parse_options(section: str) -> list[dict]:
    marker = section.find("|事件选项=")
    if marker < 0:
        return []
    start = section.find("{{", marker)
    if start < 0:
        return []
    outer = template_at(section, start)
    if not outer:
        return []
    choices = []
    for field in top_fields(outer)[1:]:
        match = re.match(r"\s*【([^】]+)】(.*)", field, re.S)
        if not match:
            continue
        label = match.group(1).strip()
        line = match.group(2).splitlines()[0]
        outcome = effects(line)
        choices.append({"label": label, "effects": outcome,
                        "effect_confidence": "explicit_wiki_text" if outcome else "unclassified"})
    return choices


def build(wiki: dict, known_maps: set[str]) -> dict:
    pages = {p["title"]: p["wikitext"] for p in wiki["pages"]}
    stage_map = {}
    prefix_votes = {}
    for title, text in pages.items():
        match = MAP_FIELD.search(text)
        if not match:
            continue
        asset = match.group(1).strip()
        main = re.fullmatch(r"忘却篇([1-9])-([0-9]+)", asset)
        if main:
            mid = f"{int(main[1])}-{int(main[2])}"
            if mid in known_maps:
                stage_map[title] = mid
                prefix = title.rsplit("-", 1)[0]
                prefix_votes.setdefault(prefix, Counter())[int(main[1])] += 1
        else:
            special = asset.replace("_map", "")
            if special in known_maps:
                stage_map[title] = special
    chapters = {k: votes.most_common(1)[0][0] for k, votes in prefix_votes.items()}
    records = []
    for title, text in pages.items():
        if not title.endswith("·剧情"):
            continue
        headings = list(EVENT_HEADING.finditer(text))
        if not headings:
            continue
        base = title[:-3]
        mid = stage_map.get(base)
        link_confidence = "wiki_map_field" if mid else "unlinked"
        if not mid:
            match = re.fullmatch(r"(.+)-0?([0-9]+)", base)
            if match:
                special = f"{match[1]}{int(match[2]):02d}"
                if special in known_maps:
                    mid = special
                    link_confidence = "stage_filename_match"
                elif match[1] in chapters:
                    candidate = f"{chapters[match[1]]}-{int(match[2])}"
                    if candidate in known_maps:
                        mid = candidate
                        link_confidence = "chapter_inferred"
        for index, heading in enumerate(headings):
            next_heading = re.search(r"(?m)^===[^=]", text[heading.end():])
            end = heading.end() + next_heading.start() if next_heading else len(text)
            section = text[heading.end():end]
            image = re.search(r"(?m)^\|事件图=([^\r\n}]+)", section)
            records.append({
                "map_id": mid, "map_link_confidence": link_confidence,
                "stage_page": base, "event": heading.group(1).strip(),
                "event_image": image.group(1).strip() if image else None,
                "options": parse_options(section),
                "source": "https://morimens.huijiwiki.com/wiki/" + quote(title),
                "source_kind": "wiki_story_transcript",
                "source_confidence": "documented_not_live_verified",
            })
    mapped = sum(r["map_id"] is not None for r in records)
    optioned = sum(bool(r["options"]) for r in records)
    return {"schema": 1, "attribution": wiki.get("source", {}),
            "note": "事件名和选项来自维基抄本；效果只保留明确可抽取的事实。地图格上的通用事件图标无法确定会触发哪一个事件。",
            "counts": {"events": len(records), "linked_to_map": mapped,
                       "with_options": optioned, "with_structured_effects": sum(any(o["effects"] for o in r["options"]) for r in records)},
            "events": records}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wiki", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=OUTPUT)
    args = ap.parse_args()
    wiki = json.loads(args.wiki.read_text(encoding="utf-8"))
    maps = set(json.loads((ROOT / "resource/map_data/maps.json").read_text(encoding="utf-8"))["maps"])
    data = build(wiki, maps)
    args.out.write_bytes(json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8"))
    print(data["counts"])


if __name__ == "__main__":
    main()
