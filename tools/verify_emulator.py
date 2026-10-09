"""Run a bounded MaaFramework task against the selected ADB emulator."""

import argparse
import json
import time
from pathlib import Path

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adb", required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--entry", default="StoryEntryRouter")
    parser.add_argument("--task", help="interface.json task name")
    parser.add_argument("--case", action="append", default=[], metavar="OPTION=CASE")
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    override = {}
    if args.task:
        interface = json.loads((root / "interface.json").read_text(encoding="utf-8-sig"))
        task = next(t for t in interface["task"] if t["name"] == args.task)
        if args.entry == "StoryEntryRouter":
            args.entry = task["entry"]
        for node, fields in task.get("pipeline_override", {}).items():
            override.setdefault(node, {}).update(fields)
        selected = dict(item.split("=", 1) for item in args.case)
        for name in task.get("option", []):
            option = interface["option"][name]
            choice = selected.pop(name, option["default_case"])
            case = next(c for c in option["cases"] if c["name"] == choice)
            for node, fields in case.get("pipeline_override", {}).items():
                override.setdefault(node, {}).update(fields)
        if selected:
            raise ValueError(f"Unknown options: {', '.join(selected)}")
    controller = AdbController(args.adb, args.serial)
    resource = Resource()
    assert controller.post_connection().wait().succeeded, "ADB connection failed"
    assert resource.post_bundle(root / "resource").wait().succeeded, "resource load failed"
    tasker = Tasker()
    assert tasker.bind(resource, controller), "tasker bind failed"
    job = tasker.post_task(args.entry, override)
    deadline = time.monotonic() + args.seconds
    seen = set()
    while time.monotonic() < deadline and not job.done:
        detail = tasker.get_task_detail(job.job_id)
        if detail:
            for node in detail.nodes:
                if node.node_id not in seen:
                    seen.add(node.node_id)
                    event = {"node": node.name, "completed": node.completed,
                             "recognized": bool(node.recognition)}
                    if node.name == "DD_Pick" and node.recognition:
                        event["box"] = str(node.recognition.box)
                    print(json.dumps(event, ensure_ascii=False), flush=True)
        time.sleep(0.5)
    if not job.done:
        tasker.post_stop().wait()
    detail = tasker.get_task_detail(job.job_id)
    print(json.dumps({"task_status": str(detail.status) if detail else None,
                      "nodes": [node.name for node in detail.nodes] if detail else []}, ensure_ascii=False))


if __name__ == "__main__":
    main()
