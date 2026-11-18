#!/usr/bin/env python3
"""Synthetic fixtures. These are not the platform's three official cases."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ed.pipeline import run  # noqa: E402
from ed.util import dump  # noqa: E402


CHECKS = []


def ck(name, ok, detail=""):
    CHECKS.append((bool(ok), name))
    if not ok:
        print("FAIL", name, detail)


def write_case(directory, payload, extra_files=None):
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, "case.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    with open(os.path.join(directory, "task.md"), "w", encoding="utf-8") as handle:
        handle.write("示意任务，不是平台正式案例。\n")
    for name, text in (extra_files or {}).items():
        path = os.path.join(directory, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)


def stable(result):
    body = dict(result)
    body.pop("runtime_seconds", None)
    return dump(body)


def test_feasibility():
    root = tempfile.mkdtemp(prefix="ed-feas-")
    try:
        case = {
            "case_id": "selftest-feas",
            "example_only": True,
            "objective": "measure yield",
            "output_contract": {"experiment_plan": "required", "custom_field_zzz": "required"},
            "plans": [
                {
                    "id": "A", "version": 1,
                    "hypothesis": "yield increases with temperature",
                    "variables": [{"name": "temperature", "unit": "C", "role": "independent"}],
                    "controls": [{"name": "blank", "blocks": "reagent background"}],
                    "equipment": ["oven-X"],
                    "materials": [{"name": "reagent-a", "qty": 10, "unit": "g"}],
                    "steps": [{"id": "s1", "hours": 1.5}, {"id": "s2", "hours": 2.0}],
                    "parameters": [{"name": "temperature", "value": 90, "unit": "C"}],
                    "risks": [{"trigger": "oven fault", "consequence": "no run", "mitigation": "stop and reschedule"}],
                    "samples": {"n_required": 8},
                    "cost": {"machine": 20, "material": 80},
                    "evidence": ["manual oven-X"],
                },
                {
                    "id": "B", "version": 2,
                    "hypothesis": "yield increases with temperature below the oven limit",
                    "variables": [{"name": "temperature", "unit": "C"}],
                    "controls": [{"name": "blank", "blocks": "reagent background"}],
                    "equipment": ["oven-X"],
                    "materials": [{"name": "reagent-a", "qty": 2, "unit": "g"}],
                    "steps": [{"id": "s1", "hours": 1.5}, {"id": "s2", "hours": 2.0}],
                    "parameters": [{"name": "temperature", "value": 60, "unit": "C"}],
                    "risks": [{"trigger": "oven fault", "mitigation": "switch off and stop"}],
                    "samples": {"n_required": 8},
                    "cost": {"machine": 20, "material": 30},
                    "evidence": ["manual oven-X", "stock card"],
                },
                {
                    "id": "C", "version": 3,
                    "hypothesis": "a missing oven still runs",
                    "variables": [{"name": "temperature", "unit": "C"}],
                    "controls": [{"name": "blank", "blocks": "reagent background"}],
                    "equipment": ["oven-missing"],
                    "materials": [{"name": "reagent-a", "qty": 1, "unit": "g"}],
                    "steps": [{"id": "s1", "hours": 1.0}],
                    "parameters": [{"name": "temperature", "value": 60, "unit": "C"}],
                    "risks": [{"trigger": "no oven", "mitigation": "do not start"}],
                    "samples": {"n_required": 100},
                    "cost": {"machine": 5, "material": 5},
                    "evidence": ["wish"],
                },
                {"id": "D", "version": 4, "note": "objective only"},
            ],
            "contracts": {
                "equipment": [{"name": "oven-X", "status": "on_hand", "measures": "temperature", "min": 20, "max": 80, "unit": "C", "booking_days": 2}],
                "materials": [{"name": "reagent-a", "qty_on_hand": 5, "unit": "g", "lead_time_days": 5, "status": "on_hand"}],
                "samples": {"n_available": 20, "source": "synthetic stock"},
                "ethics": {"approval_status": "not_required"},
            },
        }
        src = os.path.join(root, "in")
        out1 = os.path.join(root, "out1")
        out2 = os.path.join(root, "out2")
        write_case(src, case)
        first = run(src, out1, "feasibility")
        second = run(src, out2, "feasibility")
        by_id = {item["plan_id"]: item for item in first["evidence_and_risks"]["reviews"]}
        ck("B feasible", by_id["B"]["verdict"] == "feasible", by_id["B"]["verdict"])
        ck("A infeasible on 90 C", by_id["A"]["verdict"] == "infeasible" and any("90" in text for text in by_id["A"]["hard_fails"]), by_id["A"]["hard_fails"])
        ck("C missing oven", by_id["C"]["verdict"] == "infeasible")
        ck("D is not a silent pass", by_id["D"]["verdict"] != "feasible", by_id["D"]["verdict"])
        ck("chosen is B", first["experiment_plan"]["chosen_plan_id"] == "B")
        time_b = by_id["B"]["time"]
        ck("hours add to 3.5", time_b["occupied_hours"] == 3.5, time_b)
        ck("wait is booking only", time_b["wait_days"] == 2, time_b)
        ck("formula keeps the terms", "1.5" in (time_b.get("occupied_hours_formula") or ""))
        time_a = by_id["A"]["time"]
        ck("short material puts lead time on the path", time_a["wait_days"] == 5, time_a)
        ck("contract extra field stays empty", first.get("custom_field_zzz") is None)
        ck("known contract field filled", isinstance(first.get("experiment_plan"), dict) and first["experiment_plan"])
        ck("deterministic", stable(first) == stable(second))
        empty = run(os.path.join(root, "empty"), os.path.join(root, "empty-out"), "feasibility")
        os.makedirs(os.path.join(root, "empty"), exist_ok=True)
        empty = run(os.path.join(root, "empty"), os.path.join(root, "empty-out"), "feasibility")
        ck("empty input fails closed", empty["status"] == "failed" and empty["experiment_plan"]["chosen_plan_id"] is None)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_optimize():
    root = tempfile.mkdtemp(prefix="ed-opt-")
    try:
        case = {
            "case_id": "selftest-opt",
            "example_only": True,
            "objective": {"metric": "yield", "direction": "max", "unit": "fraction"},
            "budget": {"max_runs": 4, "hours_per_run": 2, "machine_hour_cost": 10, "consumable_cost": 3},
            "parameters": [{
                "name": "temperature",
                "unit": "C",
                "min": 40,
                "max": 120,
                "step": 10,
                "limits": [
                    {"source": "equipment", "min": 20, "max": 80, "unit": "C"},
                    {"source": "safety", "max": 75, "unit": "C"},
                    {"source": "material", "max": 90, "unit": "C"},
                ],
            }],
            "history": [
                {"parameters": {"temperature": 60}, "response": 0.4},
                {"parameters": {"temperature": 90}, "response": 0.9},
            ],
            "controls": [{"name": "blank", "blocks": "background"}],
        }
        src = os.path.join(root, "in")
        write_case(src, case)
        result = run(src, os.path.join(root, "out"), "optimize")
        domain = result["experiment_plan"]["parameters"][0]
        ck("domain hi is safety 75", domain["max"] == 75, domain)
        ck("grid stops at 70", domain["grid"] == [40, 50, 60, 70], domain["grid"])
        best = result["experiment_plan"]["recommended_observed"][0]
        ck("best observed is 60 not 90", best["parameters"]["temperature"] == 60 and best["response"] == 0.4, best)
        nxt = [item["parameters"]["temperature"] for item in result["experiment_plan"]["next_runs"]]
        ck("next points are unused neighbours", nxt == [50, 70], nxt)
        cost = result["experiment_plan"]["cost"]
        ck("per run cost 23", cost["per_run"] == 23, cost)
        ck("proposed cost is 46", cost["proposed_cost"] == 46, cost)
        ck("no invented response", all(item["response"] is None for item in result["experiment_plan"]["next_runs"]))
        conflict = dict(case)
        conflict["case_id"] = "selftest-opt-conflict"
        conflict["parameters"] = [{
            "name": "temperature", "unit": "C", "min": 40, "max": 120, "step": 10,
            "limits": [{"source": "equipment", "max": 30, "unit": "C"}],
        }]
        conflict["history"] = []
        write_case(os.path.join(root, "bad"), conflict)
        blocked = run(os.path.join(root, "bad"), os.path.join(root, "bad-out"), "optimize")
        ck("empty domain recommends nothing", blocked["status"] == "partial" and blocked["experiment_plan"]["recommended_observed"] == [], blocked["summary"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_compare():
    root = tempfile.mkdtemp(prefix="ed-cmp-")
    try:
        def plan(pid, cost, equipment, evidence):
            return {
                "id": pid,
                "hypothesis": "yield depends on temperature",
                "variables": [{"name": "temperature", "unit": "C"}],
                "controls": [{"name": "blank", "blocks": "background"}],
                "equipment": [equipment],
                "materials": [{"name": "reagent-a", "qty": 1}],
                "steps": [{"id": "s1", "hours": 1}],
                "parameters": [{"name": "temperature", "value": 60, "unit": "C"}],
                "risks": [{"trigger": "oven fault", "mitigation": "stop"}],
                "samples": {"n_required": 4},
                "cost": cost,
                "evidence": evidence,
            }
        case = {
            "case_id": "selftest-compare",
            "example_only": True,
            "plans": [
                plan("expensive", {"machine": 80, "material": 20}, "oven-X", ["one"]),
                plan("cheap", {"machine": 40, "material": 10}, "oven-X", ["one", "two"]),
                plan("blocked", {"machine": 1, "material": 1}, "oven-missing", ["one"]),
            ],
            "contracts": {
                "equipment": [{"name": "oven-X", "status": "on_hand", "measures": "temperature", "min": 20, "max": 80, "unit": "C", "booking_days": 1}],
                "materials": [{"name": "reagent-a", "qty_on_hand": 5, "status": "on_hand"}],
                "samples": {"n_available": 10},
                "ethics": {"approval_status": "not_required"},
            },
        }
        src = os.path.join(root, "in")
        write_case(src, case)
        result = run(src, os.path.join(root, "out"), "compare")
        ck("winner is the feasible cheaper plan", result["experiment_plan"]["chosen_plan_id"] == "cheap", result["summary"])
        rejected = {item["plan_id"]: item["reason"] for item in result["evidence_and_risks"]["rejections"]}
        ck("expensive cites both costs", "100" in rejected["expensive"] and "50" in rejected["expensive"], rejected.get("expensive"))
        ck("blocked is not chosen for being cheap", "blocked" in rejected and "1" not in result["summary"][:0])
        ck("blocked reason is feasibility", "infeasible" in rejected["blocked"] or "不可" in rejected["blocked"] or "oven" in rejected["blocked"].lower() or "缺失" in rejected["blocked"] or "不在" in rejected["blocked"], rejected.get("blocked"))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_interpret():
    root = tempfile.mkdtemp(prefix="ed-int-")
    try:
        src = os.path.join(root, "in")
        write_case(src, {"case_id": "selftest-interpret", "example_only": True})
        with open(os.path.join(src, "measurements.csv"), "w", encoding="utf-8") as handle:
            handle.write("time_h,signal,batch\n0,1,A\n1,1,A\n2,1,A\n3,1,A\n4,10,B\n5,10,B\n")
        result = run(src, os.path.join(root, "out"), "interpret")
        series = result["evidence_and_risks"]["series"][0]
        ck("positive pooled slope", series["trend"]["slope"] > 0, series["trend"])
        ck("aliased with batch", series["aliased_with"] == "batch")
        rows = [item["row"] for item in series["anomalies"]]
        ck("anomaly rows are the two high points", rows == [5, 6], rows)
        causes = result["evidence_and_risks"]["causes"]
        ck("batch B is association only", causes and causes[0]["level"] == "B" and causes[0]["mechanism"] is None, causes)
        ck("exclusion group is A", "A" in causes[0]["exclusion_levels"])
        short = os.path.join(root, "short")
        write_case(short, {"case_id": "selftest-interpret-short", "example_only": True})
        with open(os.path.join(short, "measurements.csv"), "w", encoding="utf-8") as handle:
            handle.write("time_h,signal\n0,1\n1,2\n")
        small = run(short, os.path.join(root, "short-out"), "interpret")
        ck("n<5 withholds anomalies", small["evidence_and_risks"]["anomalies"] == [], small["summary"])
        ck("n<5 is partial", small["status"] == "partial", small["status"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="all")
    args = parser.parse_args(argv)
    CHECKS.clear()
    modes = ["feasibility", "optimize", "compare", "interpret"] if args.mode == "all" else [args.mode]
    dispatch = {
        "feasibility": test_feasibility,
        "optimize": test_optimize,
        "compare": test_compare,
        "interpret": test_interpret,
    }
    for name in modes:
        dispatch[name]()
    failed = [name for ok, name in CHECKS if not ok]
    print("selftest assertions %d failed %d" % (len(CHECKS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
