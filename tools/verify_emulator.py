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
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    controller = AdbController(args.adb, args.serial)
    resource = Resource()
    assert controller.post_connection().wait().succeeded, "ADB connection failed"
    assert resource.post_bundle(root / "resource").wait().succeeded, "resource load failed"
    tasker = Tasker()
    assert tasker.bind(resource, controller), "tasker bind failed"
    job = tasker.post_task(args.entry)
    deadline = time.monotonic() + args.seconds
    seen = set()
    while time.monotonic() < deadline and not job.done:
        detail = tasker.get_task_detail(job.job_id)
        if detail:
            for node in detail.nodes:
                if node.node_id not in seen:
                    seen.add(node.node_id)
                    print(json.dumps({"node": node.name, "completed": node.completed,
                                      "recognized": bool(node.recognition)}, ensure_ascii=False), flush=True)
        time.sleep(0.5)
    if not job.done:
        tasker.post_stop().wait()
    detail = tasker.get_task_detail(job.job_id)
    print(json.dumps({"task_status": str(detail.status) if detail else None,
                      "nodes": [node.name for node in detail.nodes] if detail else []}, ensure_ascii=False))


if __name__ == "__main__":
    main()
