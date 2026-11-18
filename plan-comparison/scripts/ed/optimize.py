"""Recommend parameter values only inside a finite domain the source actually states."""
from __future__ import annotations

from ed.util import as_list, evidence, find_key, first, num, units_compatible


def analyze(bundle):
    case = bundle["case"]
    parameters, path = _parameters(bundle)
    objective = _objective(bundle)
    budget = _budget(bundle)
    history, history_path = _history(bundle)
    uncertainties = []
    if not parameters:
        return {
            "status": "failed",
            "summary": "没有读到带边界的参数，不能给建议值。",
            "experiment_plan": {
                "parameters": [],
                "recommended": [],
                "search": None,
                "cost": None,
                "conditions_before_execution": ["需要每个关键参数的有限区间。"],
            },
            "evidence_and_risks": {"parameter_path": path, "risks": []},
            "confirmations": [{"item": "参数可行域", "why": "输入没有参数区间", "blocking": True}],
            "uncertainties": [{"id": "u-no-params", "topic": "parameters", "detail": "no finite parameters"}],
            "change_log": [{"id": "c-stop", "decision": "没有区间时不编造一组经验取值。", "evidence": "input"}],
            "checks": [{"name": "parameters_present", "ok": False, "detail": "missing"}],
            "mode_result": {},
        }

    domains = []
    for index, param in enumerate(parameters):
        domains.append(_domain(param, index, path))
    conflicts = [item for item in domains if item["conflict"]]
    open_domains = [item for item in domains if not item["finite"]]
    direction = first(objective, ("direction", "goal", "方向"))
    direction = str(direction).lower() if direction else None
    if direction in ("maximize", "max", "higher", "越大越好"):
        direction = "max"
    elif direction in ("minimize", "min", "lower", "越小越好"):
        direction = "min"
    else:
        direction = None
        if history:
            uncertainties.append({
                "id": "u-direction",
                "topic": "objective",
                "detail": "没有写明响应是越大越好还是越小越好，历史点只列出、不排名。",
            })

    ranked = _rank_history(history, domains, direction, history_path)
    proposals = _proposals(domains, ranked, budget)
    cost = _cost(budget, proposals, history)
    risks = []
    if conflicts:
        risks.append({
            "trigger": "可行域为空",
            "consequence": "不存在同时满足设备、材料和安全界限的取值",
            "action": "停止推荐数值，列出互相冲突的界限，交给人决定放宽哪一条。",
            "evidence": [item["name"] for item in conflicts],
        })
    if direction is None:
        risks.append({
            "trigger": "优化方向未写明",
            "consequence": "不能声称某个历史点更优",
            "action": "只给出可行域内的候选点。",
            "evidence": [history_path or "objective"],
        })

    recommended = [item for item in ranked if item["feasible"]]
    if conflicts or open_domains:
        status = "partial"
    elif recommended or proposals["points"]:
        status = "success"
    else:
        status = "partial"
    summary = _summary(domains, recommended, proposals, direction)
    return {
        "status": status,
        "summary": summary,
        "experiment_plan": {
            "hypothesis": first(case, ("hypothesis", "objective", "目标")),
            "variables": [{"name": item["name"], "unit": item["unit"], "role": "independent"} for item in domains],
            "controls": as_list(first(case, ("controls", "对照"), [])),
            "steps": proposals["points"],
            "parameters": domains,
            "resources": [],
            "readout": objective,
            "recommended_observed": recommended[:1],
            "next_runs": proposals["points"],
            "search": proposals["strategy"],
            "cost": cost,
            "conditions_before_execution": [
                item["statement"] for item in domains if item["conflict"] or not item["finite"]
            ],
        },
        "evidence_and_risks": {
            "parameter_path": path,
            "history_path": history_path,
            "objective": objective,
            "rejected_history": [item for item in ranked if not item["feasible"]],
            "risks": risks,
        },
        "confirmations": _confirmations(domains, direction, cost),
        "uncertainties": uncertainties + [item for domain in domains for item in domain["uncertainties"]],
        "change_log": proposals["change_log"] + [{
            "id": "c-no-invented-response",
            "decision": "没有实测响应时不填写预测值。",
            "evidence": history_path or "history",
        }],
        "checks": [
            {"name": "recommendations_inside_domain", "ok": _inside(recommended, proposals, domains), "detail": "grid membership"},
            {"name": "no_response_invented", "ok": all("predicted_response" not in item for item in proposals["points"]), "detail": "points"},
            {"name": "conflicts_block_recommendation", "ok": (not conflicts) or (not recommended), "detail": [item["name"] for item in conflicts]},
        ],
        "mode_result": {"domains": domains, "ranked": ranked},
    }


def _parameters(bundle):
    value, path = find_key(bundle["case"], ("parameters", "params", "参数", "factors"))
    if isinstance(value, list) and value:
        return [item for item in value if isinstance(item, dict)], "case.json:%s" % path
    if isinstance(value, dict) and value:
        rows = []
        for key, item in value.items():
            if isinstance(item, dict):
                row = dict(item)
                row.setdefault("name", key)
                rows.append(row)
        if rows:
            return rows, "case.json:%s" % path
    for extra in bundle["extras"]:
        value, path = find_key(extra["json"], ("parameters", "params", "factors"))
        if isinstance(value, list) and value:
            return value, "%s:%s" % (extra["path"], path)
    return [], None


def _objective(bundle):
    value, _path = find_key(bundle["case"], ("objective", "response", "目标", "metric"))
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"metric": value}
    return {}


def _budget(bundle):
    value, _path = find_key(bundle["case"], ("budget", "cost", "预算"))
    return value if isinstance(value, dict) else {}


def _history(bundle):
    value, path = find_key(bundle["case"], ("history", "observations", "runs", "历史"))
    if isinstance(value, list):
        return value, "case.json:%s" % path
    for extra in bundle["files"]:
        name = extra["path"].lower()
        if extra.get("rows") and any(token in name for token in ("history", "observation", "runs")):
            return extra["rows"], extra["path"]
    return [], None


def _domain(param, index, path):
    name = str(first(param, ("name", "名称"), "p%d" % (index + 1)))
    unit = first(param, ("unit", "单位"))
    bounds = []
    if num(param.get("min")) is not None or num(param.get("max")) is not None:
        bounds.append({"source": "stated", "min": num(param.get("min")), "max": num(param.get("max")), "unit": unit})
    for prefix, source in (("equipment", "equipment"), ("safety", "safety"), ("material", "material")):
        lo = num(param.get(prefix + "_min"))
        hi = num(param.get(prefix + "_max"))
        if lo is None and hi is None:
            continue
        bounds.append({
            "source": source,
            "min": lo,
            "max": hi,
            "unit": param.get(prefix + "_unit") or unit,
        })
    for limit in as_list(param.get("limits")):
        if isinstance(limit, dict):
            bounds.append({
                "source": first(limit, ("source", "name"), "limit"),
                "min": num(limit.get("min")),
                "max": num(limit.get("max")),
                "unit": limit.get("unit") or unit,
                "locator": limit.get("locator"),
            })
    usable = []
    uncertainties = []
    for bound in bounds:
        compatible = units_compatible(unit, bound.get("unit"))
        if compatible is False:
            uncertainties.append({
                "id": "u-unit-%s-%s" % (name, bound["source"]),
                "topic": "unit",
                "detail": "%s 的 %s 界限单位与参数单位不一致，这条界限没有参与求交。" % (name, bound["source"]),
            })
            continue
        usable.append(bound)
    los = [item["min"] for item in usable if item.get("min") is not None]
    his = [item["max"] for item in usable if item.get("max") is not None]
    lo = max(los) if los else None
    hi = min(his) if his else None
    conflict = lo is not None and hi is not None and lo > hi + 1e-9
    step = num(param.get("step"))
    finite = lo is not None and hi is not None and not conflict
    grid = _grid(lo, hi, step) if finite else []
    statement = "%s ∈ [%s, %s] %s" % (name, lo, hi, unit or "")
    if conflict:
        statement = "%s 的下界 %s 高于上界 %s，可行域为空。" % (name, lo, hi)
    elif not finite:
        statement = "%s 没有同时给出有限的下界和上界。" % name
    return {
        "name": name,
        "unit": unit,
        "bounds": usable,
        "min": lo,
        "max": hi,
        "step": step,
        "grid": grid,
        "finite": finite,
        "conflict": conflict,
        "statement": statement,
        "uncertainties": uncertainties,
        "evidence": [evidence((path or "parameters") + "[%d]" % index, statement)],
    }


def _grid(lo, hi, step):
    if lo is None or hi is None:
        return []
    if step is None or step <= 0:
        return [lo, hi] if lo != hi else [lo]
    values = []
    # Integer number of steps avoids accumulating binary error past the top.
    count = int(round((hi - lo) / step))
    for index in range(count + 1):
        value = lo + index * step
        if value <= hi + 1e-8:
            values.append(value)
    return values


def _rank_history(history, domains, direction, history_path):
    by_name = {item["name"]: item for item in domains}
    ranked = []
    for index, row in enumerate(history):
        if not isinstance(row, dict):
            continue
        params = row.get("parameters") if isinstance(row.get("parameters"), dict) else {
            key: value for key, value in row.items()
            if key not in ("response", "y", "value", "objective", "id")
        }
        response = num(first(row, ("response", "y", "value", "objective")))
        feasible = True
        reasons = []
        snapped = {}
        for name, domain in by_name.items():
            if name not in params:
                feasible = False
                reasons.append("%s 缺失" % name)
                continue
            value = num(params.get(name))
            if value is None or not domain["finite"]:
                feasible = False
                reasons.append("%s 不在有限域" % name)
                continue
            if domain["grid"]:
                nearest = min(domain["grid"], key=lambda item: abs(item - value))
                if abs(nearest - value) > 1e-8:
                    reasons.append("%s=%s 不在步进网格上，最近可执行点是 %s" % (name, value, nearest))
                    feasible = False
                snapped[name] = nearest
            elif domain["min"] - 1e-9 <= value <= domain["max"] + 1e-9:
                snapped[name] = value
            else:
                feasible = False
                reasons.append("%s=%s 超出 [%s, %s]" % (name, value, domain["min"], domain["max"]))
        ranked.append({
            "index": index,
            "parameters": snapped or params,
            "observed": params,
            "response": response,
            "feasible": feasible and response is not None and direction is not None,
            "in_domain": feasible,
            "reasons": reasons,
            "locator": "%s[%d]" % (history_path or "history", index),
        })
    if direction == "max":
        ranked.sort(key=lambda item: (not item["feasible"], -(item["response"] if item["response"] is not None else -1e99), item["index"]))
    elif direction == "min":
        ranked.sort(key=lambda item: (not item["feasible"], (item["response"] if item["response"] is not None else 1e99), item["index"]))
    return ranked


def _proposals(domains, ranked, budget):
    change_log = []
    if any(item["conflict"] or not item["finite"] for item in domains):
        return {"strategy": "infeasible_domain", "points": [], "change_log": [{
            "id": "c-empty-domain",
            "decision": "可行域为空或不是有限区间，不给出建议值。",
            "evidence": ",".join(item["name"] for item in domains),
        }]}
    max_runs = num(budget.get("max_runs")) if isinstance(budget, dict) else None
    spent = len(ranked)
    remaining = None if max_runs is None else max(0, int(max_runs) - spent)
    feasible_obs = [item for item in ranked if item["feasible"]]
    points = []
    if feasible_obs:
        best = feasible_obs[0]
        # Explore unused grid neighbours, deterministically by ascending value.
        names = [item["name"] for item in domains]
        if len(names) == 1:
            domain = domains[0]
            used = set()
            for row in ranked:
                value = num((row.get("observed") or {}).get(domain["name"]))
                if value is not None:
                    used.add(round(value, 10))
            candidates = [value for value in domain["grid"] if round(value, 10) not in used]
            best_value = num(best["parameters"].get(domain["name"]))
            candidates.sort(key=lambda value: (abs(value - (best_value if best_value is not None else value)), value))
            take = candidates if remaining is None else candidates[:int(remaining)]
            for value in take:
                points.append({
                    "parameters": {domain["name"]: value},
                    "unit": domain["unit"],
                    "why": "可行域网格上尚未跑过、离当前最好观测最近的点",
                    "response": None,
                })
        strategy = "grid_constrained_best_observed"
        change_log.append({
            "id": "c-best-observed",
            "decision": "当前可执行建议取可行域内响应最好的已观测点，不外推到域外。",
            "evidence": best["locator"],
        })
    else:
        strategy = "initial_grid_no_response"
        take_n = int(remaining) if remaining is not None else 9
        seeds = _initial_points(domains, take_n)
        for seed in seeds:
            points.append({"parameters": seed, "why": "尚无可用响应，这是可行域内的初始网格点", "response": None})
        change_log.append({
            "id": "c-initial-grid",
            "decision": "没有落在域内的历史响应，只安排初始网格，不报告最优值。",
            "evidence": "history",
        })
    if remaining == 0:
        points = []
        change_log.append({
            "id": "c-budget",
            "decision": "已用完 max_runs，不再追加实验点。",
            "evidence": "budget.max_runs",
        })
    return {"strategy": strategy, "points": points, "change_log": change_log}


def _initial_points(domains, take_n):
    grids = []
    for domain in domains[:3]:
        grid = domain["grid"] or [domain["min"], domain["max"]]
        if len(grid) > 3:
            mid = grid[len(grid) // 2]
            grid = [grid[0], mid, grid[-1]]
        grids.append((domain["name"], grid))
    points = [{}]
    for name, grid in grids:
        grown = []
        for point in points:
            for value in grid:
                nxt = dict(point)
                nxt[name] = value
                grown.append(nxt)
        points = grown
    points.sort(key=lambda item: tuple(item[name] for name, _grid in grids))
    return points[:take_n]


def _cost(budget, proposals, history):
    if not isinstance(budget, dict):
        return {"status": "unknown", "reason": "没有预算口径"}
    hours = num(budget.get("hours_per_run"))
    rate = num(budget.get("machine_hour_cost"))
    consumable = num(budget.get("consumable_cost"))
    if hours is None or rate is None or consumable is None:
        return {
            "status": "unknown",
            "reason": "机时、单价或耗材有缺项，缺项不按 0 计入。",
            "hours_per_run": hours,
            "machine_hour_cost": rate,
            "consumable_cost": consumable,
        }
    per_run = hours * rate + consumable
    proposed_n = len(proposals["points"])
    return {
        "status": "computed",
        "per_run": per_run,
        "formula": "per_run = %s * %s + %s = %s" % (hours, rate, consumable, per_run),
        "proposed_runs": proposed_n,
        "proposed_cost": proposed_n * per_run,
        "history_runs": len(history),
        "history_cost": len(history) * per_run,
    }


def _inside(recommended, proposals, domains):
    grids = {item["name"]: set(round(value, 10) for value in item["grid"]) for item in domains if item["grid"]}
    for row in recommended:
        for name, value in row["parameters"].items():
            if name in grids and round(float(value), 10) not in grids[name]:
                return False
    for point in proposals["points"]:
        for name, value in point["parameters"].items():
            if name in grids and round(float(value), 10) not in grids[name]:
                return False
    return True


def _confirmations(domains, direction, cost):
    rows = []
    for domain in domains:
        if domain["conflict"] or not domain["finite"]:
            rows.append({"item": domain["name"], "why": domain["statement"], "blocking": True})
    if direction is None:
        rows.append({"item": "优化方向", "why": "没有 max/min，不能宣布最优。", "blocking": True})
    if cost.get("status") != "computed":
        rows.append({"item": "成本", "why": cost.get("reason"), "blocking": False})
    return rows


def _summary(domains, recommended, proposals, direction):
    bits = []
    for domain in domains:
        bits.append(domain["statement"])
    if recommended:
        best = recommended[0]
        bits.append("域内已观测最好点是 %s，响应 %s（方向 %s）。" % (best["parameters"], best["response"], direction))
    else:
        bits.append("没有可排名的域内观测。")
    bits.append("下一步策略 %s，追加 %d 个点。" % (proposals["strategy"], len(proposals["points"])))
    bits.append("这些点没有预测响应。")
    return "".join(bits)
