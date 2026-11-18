"""Compare candidate plans on fields that were actually supplied, then choose."""
from __future__ import annotations

from ed.feasibility import analyze as review
from ed.util import as_list, evidence, first, num


def analyze(bundle):
    reviewed = review(bundle)
    reviews = reviewed.get("mode_result", {}).get("reviews") or []
    if len(reviews) < 2:
        body = dict(reviewed)
        body["status"] = "failed" if not reviews else "partial"
        body["summary"] = "可比的方案少于 2 个，不做选择。"
        body["experiment_plan"]["chosen_plan_id"] = None
        body["checks"] = list(body.get("checks") or []) + [
            {"name": "at_least_two_plans", "ok": False, "detail": len(reviews)}
        ]
        return body

    rows = []
    for item in reviews:
        cost = _cost(item)
        evidence_n = _evidence_count(item)
        rows.append({
            "plan_id": item["plan_id"],
            "verdict": item["verdict"],
            "hard_fails": item["hard_fails"],
            "conditions": item["conditions"],
            "cost": cost["total"],
            "cost_complete": cost["complete"],
            "cost_terms": cost["terms"],
            "cost_missing": cost["missing"],
            "occupied_hours": (item.get("time") or {}).get("occupied_hours"),
            "wait_days": (item.get("time") or {}).get("wait_days"),
            "evidence_n": evidence_n,
            "risk_gaps": sum(1 for check in item["items"] if check["category"] == "risk_exception" and check["status"] != "pass"),
        })
    feasible = [row for row in rows if row["verdict"] == "feasible" and row["cost_complete"]]
    winner = None
    reason = None
    sensitive = False
    if feasible:
        ordered = sorted(feasible, key=lambda row: (row["cost"], -row["evidence_n"], row["plan_id"]))
        winner = ordered[0]
        if len(ordered) > 1 and ordered[0]["cost"] == ordered[1]["cost"]:
            sensitive = True
            reason = "成本同为 %s，改按证据条数选择 %s（%d 条），不声称成本更优。" % (
                ordered[0]["cost"], winner["plan_id"], winner["evidence_n"],
            )
        else:
            reason = "在可行且成本完整的方案中，%s 的成本 %s 最低。" % (winner["plan_id"], winner["cost"])
    elif any(row["verdict"] == "feasible" for row in rows):
        reason = "有方案通过可行性审查，但成本缺项，不用残缺成本排名。"
    else:
        reason = "没有方案同时通过可行性审查，因此不选出可执行方案。"

    rejections = []
    for row in rows:
        if winner and row["plan_id"] == winner["plan_id"]:
            continue
        if row["verdict"] != "feasible":
            rejections.append({
                "plan_id": row["plan_id"],
                "reason": "可行性结论是 %s。%s" % (row["verdict"], "；".join(row["hard_fails"] or row["conditions"]) or "有未关闭的条件"),
                "evidence": row["hard_fails"][:3] or row["conditions"][:3],
            })
        elif not row["cost_complete"]:
            rejections.append({
                "plan_id": row["plan_id"],
                "reason": "成本不完整，缺少：" + ", ".join(row["cost_missing"]),
                "evidence": row["cost_missing"],
            })
        elif winner:
            rejections.append({
                "plan_id": row["plan_id"],
                "reason": "成本 %s 高于所选 %s。" % (row["cost"], winner["cost"]),
                "evidence": ["cost %s=%s" % (row["plan_id"], row["cost"]), "cost %s=%s" % (winner["plan_id"], winner["cost"])],
            })

    status = "success" if winner else "partial"
    chosen_id = winner["plan_id"] if winner else None
    chosen_review = next((item for item in reviews if item["plan_id"] == chosen_id), reviews[0])
    plan = dict(reviewed["experiment_plan"])
    plan["chosen_plan_id"] = chosen_id
    plan["comparison_table"] = rows
    plan["selection_reason"] = reason
    plan["sensitive_to_tied_cost"] = sensitive
    plan["hypothesis"] = chosen_review["source_fields"].get("hypothesis") if winner else None
    plan["variables"] = chosen_review["source_fields"].get("variables") if winner else []
    plan["controls"] = chosen_review["source_fields"].get("controls") if winner else []
    plan["steps"] = chosen_review["source_fields"].get("steps") if winner else []
    plan["parameters"] = chosen_review["source_fields"].get("parameters") if winner else []
    plan["conditions_before_execution"] = [] if winner else ["没有可执行的优选；先处理否决理由。"]
    summary = reason + " " + " ".join("%s=%s" % (row["plan_id"], row["verdict"]) for row in rows)
    checks = list(reviewed.get("checks") or [])
    checks.append({
        "name": "winner_is_feasible",
        "ok": winner is None or winner["verdict"] == "feasible",
        "detail": None if winner is None else winner["plan_id"],
    })
    checks.append({
        "name": "rejection_has_numbers_or_verdict",
        "ok": all(item["reason"] and item["evidence"] for item in rejections),
        "detail": [item["plan_id"] for item in rejections],
    })
    change = list(reviewed.get("change_log") or [])
    change.append({
        "id": "c-rank-rule",
        "decision": "只在“可行且成本每一项都有数字”的方案之间按成本升序选择；缺成本不按 0 比较。",
        "evidence": "comparison_table",
    })
    return {
        "status": status,
        "summary": summary,
        "experiment_plan": plan,
        "evidence_and_risks": {
            "reviews": reviewed["evidence_and_risks"]["reviews"],
            "rejections": rejections,
            "selection_reason": reason,
            "table_evidence": [evidence("comparison:%s" % row["plan_id"], "verdict=%s cost=%s" % (row["verdict"], row["cost"])) for row in rows],
        },
        "confirmations": reviewed["confirmations"],
        "uncertainties": reviewed["uncertainties"] + ([] if winner else [{
            "id": "u-no-winner",
            "topic": "selection",
            "detail": reason,
        }]),
        "change_log": change,
        "checks": checks,
        "mode_result": {"table": rows, "winner": chosen_id},
    }


def _cost(review):
    """Cost lives on the original plan fields copied into source_fields only as parameters.

    The numeric cost terms are read back from the review by looking at the plan id's
    source via items is not enough. They are attached in source_fields when present
    on the plan under a side channel stored in the review time dict? No.

    Feasibility does not currently copy a cost object. Read it from source_fields if
    the plan put cost onto a known key that _source_fields kept. It does not.
    So compare reads cost from the review item if feasibility stashed it.

    To avoid a second parse, feasibility's source_fields is extended by the caller
    below using the plan echo stored in mode_result... source_fields has no cost.

    The plan objects are not retained. Re-read from the statements is wrong.
    Stash happens here by inspecting nothing.

    Fix path: feasibility source_fields includes the raw plan cost if we add it.
    Until that field exists, look at review['source_fields']['cost'] after we add
    it in feasibility. This function accepts that optional field.
    """
    raw = (review.get("source_fields") or {}).get("cost")
    return _sum_cost(raw)


def _sum_cost(raw):
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return {"total": num(raw), "complete": True, "terms": [{"name": "cost", "value": num(raw)}], "missing": []}
    if isinstance(raw, dict):
        terms = []
        missing = []
        for key, value in raw.items():
            if key in ("currency", "unit", "单位"):
                continue
            value_n = num(value)
            if value_n is None:
                missing.append(str(key))
            else:
                terms.append({"name": str(key), "value": value_n})
        if missing or not terms:
            return {"total": None, "complete": False, "terms": terms, "missing": missing or ["cost"]}
        total = sum(item["value"] for item in terms)
        return {"total": total, "complete": True, "terms": terms, "missing": []}
    return {"total": None, "complete": False, "terms": [], "missing": ["cost"]}


def _evidence_count(review):
    cited = (review.get("source_fields") or {}).get("cited") or []
    return len(as_list(cited))
