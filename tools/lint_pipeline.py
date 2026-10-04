"""Lint all pipelines: duplicate node names, dangling references, missing images, unreachable nodes, unused images.

    python tools/lint_pipeline.py          # warnings are informational; exit 1 only for errors
    python tools/lint_pipeline.py --strict # warnings fail too

Reachability roots: task entries, nodes named in option overrides (their `next` lists), on_error targets.
Nodes in tools/lint_allow.json ("unreachable", "unused_images") are expected to be unreachable/unused
(helpers used by tests or kept for old flows).
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def templates(rec):
    t = rec.get("template", [])
    out = [t] if isinstance(t, str) else list(t)
    for child in rec.get("all_of", []) + rec.get("any_of", []):
        out += templates(child)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    nodes, src, errors, warnings = {}, {}, [], []
    for f in sorted((ROOT / "resource" / "pipeline").glob("*.json")):
        for name, node in json.loads(f.read_text(encoding="utf-8-sig")).items():
            if name in nodes:
                errors.append(f"duplicate node {name}: {src[name]} and {f.name}")
            nodes[name], src[name] = node, f.name
    allow_path = Path(__file__).with_name("lint_allow.json")
    allow = json.loads(allow_path.read_text(encoding="utf-8")) if allow_path.is_file() else {}
    iface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8-sig"))
    default = json.loads((ROOT / "resource" / "default_pipeline.json").read_text(encoding="utf-8-sig")).get("Default", {})
    roots = {t["entry"] for t in iface["task"]} | set(default.get("on_error", []))
    for opt in iface.get("option", {}).values():
        for case in opt.get("cases", []):
            for node, ov in (case.get("pipeline_override") or {}).items():
                if node not in nodes:
                    errors.append(f"option override of unknown node {node}")
                roots.update(ov.get("next", []) if isinstance(ov, dict) else [])
    images = set()
    for name, node in nodes.items():
        for key in ("next", "on_error"):
            for target in node.get(key, []):
                if target not in nodes:
                    errors.append(f"{name}.{key} -> missing node {target}")
        for t in templates(node):
            images.add(t)
            if not (ROOT / "resource" / "image" / t).is_file():
                errors.append(f"{name}: missing image {t}")
        roots.update(node.get("on_error", []))
    seen, stack = set(), [r for r in roots if r in nodes]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack += [t for t in nodes[cur].get("next", []) + nodes[cur].get("on_error", []) if t in nodes]
    for name in sorted(set(nodes) - seen - set(allow.get("unreachable", []))):
        warnings.append(f"unreachable node {name} ({src[name]})")
    on_disk = {p.name for p in (ROOT / "resource" / "image").glob("*.png")}
    for img in sorted(on_disk - images - set(allow.get("unused_images", []))):
        warnings.append(f"unused image {img}")
    for e in errors:
        print("ERROR", e)
    for w in warnings:
        print("warn ", w)
    print(f"{len(nodes)} nodes, {len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors or (args.strict and warnings) else 0)


if __name__ == "__main__":
    main()
