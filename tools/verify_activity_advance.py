"""Run one bounded live check of an activity stage or all nine stages.

Example: python tools/verify_activity_advance.py --stage 1 --seconds 900
"""

import argparse
import json
import shutil
import time
from pathlib import Path

from maa.controller import AdbController
from maa.resource import Resource
from maa.tasker import Tasker

ROOT = Path(__file__).resolve().parents[1]


def merge_override(*overrides):
    merged = {}
    for override in overrides:
        for node, fields in override.items():
            merged.setdefault(node, {}).update(fields)
    return merged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--stage", type=int, choices=range(1, 10))
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--adb", default=shutil.which("adb") or
                        r"D:\软件所\morimens\android-toolchain\sdk\platform-tools\adb.exe")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--seconds", type=int, default=900)
    parser.add_argument("--entry", help="Resume from a pipeline node on the current screen")
    parser.add_argument("--revive", choices=("use", "skip"), default="use")
    args = parser.parse_args()
    interface = json.loads((ROOT / "interface.json").read_text(encoding="utf-8"))
    task = next(t for t in interface["task"] if t["name"] == "自动活动推进")
    scope = interface["option"]["活动推进范围"]
    scope_case = next(c for c in scope["cases"] if c["name"] == ("all" if args.all else f"stage{args.stage}"))
    option = interface["option"]["活动应急灵知体"]
    case = next(c for c in option["cases"] if c["name"] == args.revive)
    override = merge_override(task["pipeline_override"], scope_case.get("pipeline_override", {}), case.get("pipeline_override", {}))

    resource = Resource()
    controller = AdbController(args.adb, args.serial)
    assert resource.post_bundle(str(ROOT / "resource")).wait().succeeded, "resource load failed"
    assert controller.post_connection().wait().succeeded, "ADB connection failed"
    runner = Tasker()
    assert runner.bind(resource, controller), "tasker bind failed"
    job = runner.post_task(args.entry or task["entry"], override)
    deadline = time.monotonic() + args.seconds
    seen = set()
    while not job.done and time.monotonic() < deadline:
        detail = runner.get_task_detail(job.job_id)
        if detail:
            for node in detail.nodes or []:
                if node.node_id not in seen:
                    seen.add(node.node_id)
                    print(node.name, "completed=" + str(node.completed), flush=True)
        time.sleep(1)
    timed_out = not job.done
    if timed_out:
        runner.post_stop().wait()
    detail = runner.get_task_detail(job.job_id)
    names = [n.name for n in detail.nodes] if detail else []
    target = 9 if args.all else args.stage
    passed = f"AA_Completed{target}" in names and "AA_BattleFailed" not in names and not timed_out
    print(json.dumps({"passed": passed, "timed_out": timed_out, "last_nodes": names[-12:]},
                     ensure_ascii=False), flush=True)
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
