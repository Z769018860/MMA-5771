import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "resource" / "pipeline"
TEMPLATES = ROOT / "resource" / "image"


def main() -> None:
    errors: list[str] = []
    for path in sorted(PIPELINE.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        names = set(data)
        for name, node in data.items():
            for edge_key in ("next", "on_error"):
                for target in node.get(edge_key, []):
                    if target not in names:
                        errors.append(f"{path.name}:{name}.{edge_key} -> missing {target}")
            templates = node.get("template", [])
            if isinstance(templates, str):
                templates = [templates]
            for template in templates:
                if not (TEMPLATES / template).is_file():
                    errors.append(f"{path.name}:{name} -> missing template {template}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("resource validation passed")


if __name__ == "__main__":
    main()
