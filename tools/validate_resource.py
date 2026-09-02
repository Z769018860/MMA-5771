import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "resource" / "pipeline"
IMAGE = ROOT / "resource" / "image"


def main():
    errors = []
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
            templates = node.get("template", [])
            if isinstance(templates, str):
                templates = [templates]
            for template in templates:
                if not (IMAGE / template).is_file():
                    errors.append(f"{path.name}:{name} -> missing image {template}")
    interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8-sig"))
    for task in interface.get("task", []):
        if task.get("entry") not in all_nodes:
            errors.append(f"interface task {task.get('name')} -> missing entry {task.get('entry')}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"validation passed: {len(parsed)} pipelines, {len(all_nodes)} nodes")


if __name__ == "__main__":
    main()
