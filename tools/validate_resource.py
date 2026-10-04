import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "resource" / "pipeline"
IMAGE = ROOT / "resource" / "image"


def png_size(path):
    with path.open("rb") as stream:
        header = stream.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", header[16:24])


def png_intact(path):
    """True when the PNG chunk lengths/CRCs are consistent and it ends with IEND (a truncated or text-mangled copy is not)."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return False
    i, seen_end = 8, False
    while i + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        end = i + 12 + length
        if end > len(data) or zlib.crc32(data[i + 4:i + 8 + length]) != struct.unpack(">I", data[end - 4:end])[0]:
            return False
        seen_end = kind == b"IEND"
        i = end
    return seen_end and i == len(data)


def validate_recognition(path, name, recognition, errors):
    templates = recognition.get("template", [])
    if isinstance(templates, str):
        templates = [templates]
    roi = recognition.get("roi")
    for template in templates:
        template_path = IMAGE / template
        if not template_path.is_file():
            errors.append(f"{path.name}:{name} -> missing image {template}")
            continue
        size = png_size(template_path)
        if size and isinstance(roi, list) and len(roi) == 4:
            width, height = size
            if width > roi[2] or height > roi[3]:
                errors.append(
                    f"{path.name}:{name} -> template {template} is {width}x{height}, "
                    f"larger than roi {roi[2]}x{roi[3]}"
                )
    for key in ("all_of", "any_of"):
        for index, child in enumerate(recognition.get(key, [])):
            validate_recognition(path, f"{name}.{key}[{index}]", child, errors)


def main():
    errors = []
    known_bad = set(json.loads((ROOT / "tools" / "lint_allow.json").read_text(encoding="utf-8")).get("corrupt_images", []))
    for image in sorted(IMAGE.glob("*.png")):
        if not png_intact(image):
            if image.name in known_bad:
                print(f"WARNING corrupt image (known, must be re-uploaded as a binary file): {image.name}")
            else:
                errors.append(f"corrupt image {image.name}")
    all_nodes = {}
    parsed = {}
    for path in sorted(PIPELINE.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        parsed[path] = data
        all_nodes.update({name: path for name in data})
    defaults = json.loads((ROOT / "resource" / "default_pipeline.json").read_text(encoding="utf-8-sig"))
    for path, data in parsed.items():
        for name, node in data.items():
            for key in ("next", "on_error"):
                inherited = defaults.get("Default", {}).get(key, []) if key not in node else []
                for target in node.get(key, inherited):
                    if target not in all_nodes:
                        errors.append(f"{path.name}:{name}.{key} -> missing node {target}")
            validate_recognition(path, name, node, errors)
    interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8-sig"))
    for task in interface.get("task", []):
        if task.get("entry") not in all_nodes:
            errors.append(f"interface task {task.get('name')} -> missing entry {task.get('entry')}")
    for task in interface.get("task", []):
        for node, override in (task.get("pipeline_override") or {}).items():
            if node not in all_nodes:
                errors.append(f"task {task.get('name')} overrides missing node {node}")
            for target in override.get("next", []):
                if target not in all_nodes:
                    errors.append(f"task {task.get('name')} override {node} -> missing node {target}")
    for opt_name, opt in interface.get("option", {}).items():
        for case in opt.get("cases", []):
            for node, override in (case.get("pipeline_override") or {}).items():
                if node not in all_nodes:
                    errors.append(f"option {opt_name}/{case.get('name')} overrides missing node {node}")
                for target in override.get("next", []) if isinstance(override, dict) else []:
                    if target not in all_nodes:
                        errors.append(f"option {opt_name}/{case.get('name')} -> missing node {target}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"validation passed: {len(parsed)} pipelines, {len(all_nodes)} nodes")


if __name__ == "__main__":
    main()
