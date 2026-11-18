#!/usr/bin/env python3
"""Run one locked period-4 skill.

    python3 scripts/run_case.py --input /input --output /app/output --work /app/work
    python3 scripts/run_case.py --selftest

Exit 0 when result.json was written. The scientific status is inside that file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p4.pipeline import run  # noqa: E402


def locked():
    path = os.path.join(ROOT, "resources", "mode.json")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data["mode"], data["profile"]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=os.environ.get("P4_INPUT", "/input"))
    parser.add_argument("--output", default=os.environ.get("P4_OUTPUT", "/app/output"))
    parser.add_argument("--work", default=os.environ.get("P4_WORK", "/app/work"))
    parser.add_argument("--mode", default=None)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        from selftest import main as selftest_main
        forwarded = []
        if args.mode or args.profile:
            mode = args.mode
            profile = args.profile
            if mode is None or profile is None:
                locked_mode, locked_profile = locked()
                mode = mode or locked_mode
                profile = profile or locked_profile
            forwarded = ["--mode", mode, "--profile", profile]
        return selftest_main(forwarded)
    if args.mode and args.profile:
        mode, profile = args.mode, args.profile
    else:
        mode, profile = locked()
        mode = args.mode or mode
        profile = args.profile or profile
    os.makedirs(args.work, exist_ok=True)
    started = time.time()
    result = run(args.input, args.output, mode, profile)
    result_path = os.path.join(args.output, "result.json")
    with open(result_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["runtime_seconds"] = round(time.time() - started, 6)
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print("status=%s case_id=%s result=%s" % (result.get("status"), result.get("case_id"), result_path))
    if args.verify:
        missing = [name for name in ("case_id", "status", "primary", "sources", "uncertainties", "change_log") if name not in payload]
        if missing:
            print("contract missing: %s" % ", ".join(missing))
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
