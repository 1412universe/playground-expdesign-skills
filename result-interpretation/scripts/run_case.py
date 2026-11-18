#!/usr/bin/env python3
"""Run the locked experimental-design skill on one case directory.

    python3 scripts/run_case.py --input /input --output /app/output --work /app/work
    python3 scripts/run_case.py --selftest

Exit 0 when result.json was written. The scientific status is inside that file
(`success`, `partial`, or `failed`). Exit 2 only when the runner itself cannot
write a result.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ed.pipeline import run  # noqa: E402


def mode_from_disk():
    path = os.path.join(ROOT, "resources", "mode.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)["mode"]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.environ.get("ED_INPUT", "/input"))
    parser.add_argument("--output", default=os.environ.get("ED_OUTPUT", "/app/output"))
    parser.add_argument("--work", default=os.environ.get("ED_WORK", "/app/work"))
    parser.add_argument("--mode", default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        from selftest import main as selftest_main
        return selftest_main(["--mode", args.mode or mode_from_disk()])
    mode = args.mode or mode_from_disk()
    os.makedirs(args.work, exist_ok=True)
    started = time.time()
    result = run(args.input, args.output, mode)
    result_path = os.path.join(args.output, "result.json")
    with open(result_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["runtime_seconds"] = round(time.time() - started, 6)
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print("status=%s case_id=%s result=%s" % (result.get("status"), result.get("case_id"), result_path))
    if args.verify:
        required = ("case_id", "status", "experiment_plan", "evidence_and_risks", "confirmations", "sources", "uncertainties", "change_log")
        missing = [name for name in required if name not in payload]
        if missing:
            print("contract missing: %s" % ", ".join(missing))
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
