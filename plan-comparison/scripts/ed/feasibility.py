"""Review a versioned plan against the contracts that were actually supplied."""
from __future__ import annotations

from ed.util import as_list, canon_status, evidence, find_key, first, norm_name, num, strings_of, units_compatible

CATEGORIES = [
    "hypothesis_variables",
    "controls",
    "equipment_materials",
    "time_cost",
    "parameter_range",
    "risk_exception",
    "ethics_safety",
]

ETHICS_WORDS = (
    "人体", "患者", "血液", "动物", "小鼠", "大鼠", "人源",
    "human", "patient", "animal", "mouse", "blood", "hazard",
    "危险", "易燃", "剧毒", "个人信息", "personal data",
)


def analyze(bundle):
    case = bundle["case"]
    plans, plan_path = _plans(bundle)
    contracts, contract_path = _contracts(bundle)
    uncertainties = []
    if not plans:
        uncertainties.append({
            "id": "u-no-plans",
            "topic": "plans",
            "detail": "输入里没有候选方案列表，不能把任务说明当成已经设计好的方案。",
        })
        return _empty(uncertainties, plan_path, contract_path)

    inventory = _equipment(contracts)
    materials = _materials(contracts)
    samples = first(contracts, ("samples", "样本"), {}) or {}
    ethics = first(contracts, ("ethics", "伦理"), {}) or {}
    reviews = []
    for index, plan in enumerate(plans):
        if not isinstance(plan, dict):
            plan = {"id": "plan-%d" % (index + 1), "text": str(plan)}
        reviews.append(_review_one(
            plan, index, plan_path, contract_path, inventory, materials, samples, ethics
        ))
    feasible = [item for item in reviews if item["verdict"] == "feasible"]
    chosen = feasible[0] if feasible else _least_blocked(reviews)
    status = "success" if feasible else "partial"
    conditions = [] if feasible else list(chosen["conditions"])
    plan_body = {
        "chosen_plan_id": chosen["plan_id"] if feasible else None,
        "reviewed_plan_id": chosen["plan_id"],
        "hypothesis": chosen["source_fields"].get("hypothesis"),
        "variables": chosen["source_fields"].get("variables") or [],
        "controls": chosen["source_fields"].get("controls") or [],
        "steps": chosen["source_fields"].get("steps") or [],
        "parameters": chosen["source_fields"].get("parameters") or [],
        "resources": chosen["source_fields"].get("resources") or [],
        "readout": chosen["source_fields"].get("readout"),
        "time": chosen["time"],
        "verdict": chosen["verdict"] if feasible else "not_ready",
        "conditions_before_execution": conditions,
        "note": "字段均来自被点名的方案版本；没有写的步骤不会在这里补上。",
    }
    return {
        "status": status,
        "summary": _summary(reviews, feasible, chosen),
        "experiment_plan": plan_body,
        "evidence_and_risks": {
            "plan_path": plan_path,
            "contract_path": contract_path,
            "reviews": [{k: v for k, v in item.items() if k != "source_fields"} for item in reviews],
        },
        "confirmations": _confirmations(reviews),
        "uncertainties": uncertainties + [u for item in reviews for u in item["uncertainties"]],
        "change_log": [{
            "id": "c-silence",
            "decision": "方案没写的设备、参数、伦理和样本量记为缺口，不记为已满足。",
            "evidence": plan_path or "case",
        }],
        "checks": _checks(reviews),
        "mode_result": {"reviews": reviews, "feasible_ids": [item["plan_id"] for item in feasible]},
    }


def _empty(uncertainties, plan_path, contract_path):
    return {
        "status": "failed",
        "summary": "没有可读的候选方案，审查停止。",
        "experiment_plan": {
            "chosen_plan_id": None,
            "hypothesis": None,
            "variables": [],
            "controls": [],
            "steps": [],
            "parameters": [],
            "resources": [],
            "readout": None,
            "conditions_before_execution": ["需要提供至少一个带来源定位的方案版本。"],
        },
        "evidence_and_risks": {"plan_path": plan_path, "contract_path": contract_path, "reviews": []},
        "confirmations": [{"item": "提供方案版本", "why": "没有方案可审查", "blocking": True}],
        "uncertainties": uncertainties,
        "change_log": [{
            "id": "c-stop",
            "decision": "缺少方案时不生成一份看起来完整的通用流程。",
            "evidence": "input",
        }],
        "checks": [{"name": "plans_present", "ok": False, "detail": "no plans"}],
        "mode_result": {"reviews": [], "feasible_ids": []},
    }


def _plans(bundle):
    value, path = find_key(bundle["case"], (
        "plans", "candidates", "candidate_plans", "versions", "proposals", "方案", "候选方案",
    ))
    if isinstance(value, list) and value:
        return value, "case.json:%s" % path
    for extra in bundle["extras"]:
        value, path = find_key(extra["json"], (
            "plans", "candidates", "candidate_plans", "versions", "proposals",
        ))
        if isinstance(value, list) and value:
            return value, "%s:%s" % (extra["path"], path)
    return [], None


def _contracts(bundle):
    value, path = find_key(bundle["case"], (
        "contracts", "inventory", "resources", "lab", "constraints", "合同", "条件",
    ))
    if isinstance(value, dict):
        return value, "case.json:%s" % path
    for extra in bundle["extras"]:
        value, path = find_key(extra["json"], ("contracts", "inventory", "resources"))
        if isinstance(value, dict):
            return value, "%s:%s" % (extra["path"], path)
    return {}, None


def _equipment(contracts):
    raw = first(contracts, ("equipment", "devices", "instruments", "设备"), [])
    return [item if isinstance(item, dict) else {"name": str(item)} for item in as_list(raw)]


def _materials(contracts):
    raw = first(contracts, ("materials", "consumables", "材料", "耗材"), [])
    return [item if isinstance(item, dict) else {"name": str(item)} for item in as_list(raw)]


def _review_one(plan, index, plan_path, contract_path, inventory, materials, samples, ethics):
    plan_id = str(first(plan, ("id", "plan_id", "name", "version"), "plan-%d" % (index + 1)))
    locator = "%s[%d]" % (plan_path or "plans", index)
    items = []
    uncertainties = []
    items.append(_hypothesis(plan, locator))
    items.append(_controls(plan, locator))
    equip_item, used = _equipment_item(plan, locator, inventory, contract_path)
    items.append(equip_item)
    material_item, lead_days = _material_item(plan, locator, materials, contract_path)
    items.append(material_item)
    time_item, time_body = _time_item(plan, locator, used, lead_days)
    items.append(time_item)
    items.append(_parameter_item(plan, locator, used))
    items.append(_risk_item(plan, locator))
    items.append(_ethics_item(plan, locator, ethics, contract_path))
    items.append(_sample_item(plan, locator, samples, contract_path))
    # sample check is part of the seven-way review; keep the canonical seven plus sample
    # folded into ethics_safety if we already used that slot. It is its own item and
    # still blocks. The seven names stay present via the list above except sample is extra.
    hard = [item for item in items if item["hard"]]
    gaps = [item for item in items if item["status"] in ("gap", "conditional")]
    if hard:
        verdict = "infeasible"
    elif gaps:
        verdict = "conditional"
    else:
        verdict = "feasible"
    conditions = []
    for item in items:
        if item["status"] == "conditional":
            conditions.append(item["statement"])
        elif item["status"] == "gap":
            conditions.append("补上后再判：" + item["statement"])
    return {
        "plan_id": plan_id,
        "version": plan.get("version"),
        "verdict": verdict,
        "items": items,
        "hard_fails": [item["statement"] for item in hard],
        "conditions": conditions,
        "time": time_body,
        "uncertainties": uncertainties,
        "source_fields": _source_fields(plan),
    }


def _source_fields(plan):
    cited = as_list(first(plan, ("evidence", "sources", "citations", "依据"), []))
    return {
        "hypothesis": first(plan, ("hypothesis", "假设")),
        "variables": as_list(first(plan, ("variables", "变量"), [])),
        "controls": as_list(first(plan, ("controls", "control_groups", "对照"), [])),
        "steps": as_list(first(plan, ("steps", "步骤"), [])),
        "parameters": as_list(first(plan, ("parameters", "params", "参数"), [])),
        "resources": as_list(first(plan, ("equipment", "resources", "设备"), [])),
        "readout": first(plan, ("readout", "metric", "判读", "指标")),
        "cost": first(plan, ("cost", "costs", "成本")),
        "cited": cited,
    }


def _item(category, status, statement, evidence_list, hard=False, numbers=None):
    if status == "pass" and not evidence_list:
        status = "gap"
        statement = statement + "（没有定位，不能记为通过）"
        hard = False
    return {
        "category": category,
        "status": status,
        "hard": bool(hard) and status == "fail",
        "statement": statement,
        "evidence": evidence_list,
        "numbers": numbers or {},
    }


def _hypothesis(plan, locator):
    hypothesis = first(plan, ("hypothesis", "假设", "objective", "目标"))
    variables = as_list(first(plan, ("variables", "变量"), []))
    named = []
    for variable in variables:
        if isinstance(variable, dict) and first(variable, ("name", "名称")):
            named.append(variable)
        elif isinstance(variable, str) and variable.strip():
            named.append({"name": variable})
    if hypothesis and named:
        unit_ok = any(isinstance(item, dict) and first(item, ("unit", "单位", "measure", "测量")) for item in named)
        status = "pass" if unit_ok else "conditional"
        text = "假设和变量都有原文。" if unit_ok else "有假设和变量名，但没有单位或测量方式。"
        return _item(
            "hypothesis_variables", status, text,
            [evidence(locator + ".hypothesis", hypothesis)],
        )
    return _item(
        "hypothesis_variables", "gap",
        "假设或可操作变量缺失；不能把研究目标的复述当成可检验假设。",
        [evidence(locator, "hypothesis/variables missing")] if True else [],
    )


def _controls(plan, locator):
    controls = as_list(first(plan, ("controls", "control_groups", "对照"), []))
    usable = []
    for control in controls:
        if isinstance(control, dict) and (first(control, ("blocks", "excludes", "排除", "purpose")) or first(control, ("name", "名称"))):
            if first(control, ("blocks", "excludes", "排除", "purpose")):
                usable.append(control)
        elif isinstance(control, str) and len(control.strip()) > 8:
            usable.append(control)
    if usable:
        return _item(
            "controls", "pass", "对照写明了它要排除什么，或给出了可核对的对照说明。",
            [evidence(locator + ".controls", str(usable[0])[:180])],
        )
    return _item("controls", "gap", "没有能对应到混杂因素的对照。", [evidence(locator, "controls missing")])


def _equipment_item(plan, locator, inventory, contract_path):
    requested = []
    for raw in as_list(first(plan, ("equipment", "instruments", "devices", "设备"), [])):
        if isinstance(raw, dict):
            name = first(raw, ("name", "model", "名称", "型号"))
        else:
            name = str(raw)
        if name:
            requested.append(str(name))
    if not requested:
        return _item(
            "equipment_materials", "gap",
            "方案没有点名设备；清单里有设备也不能当成这个方案已经具备。",
            [evidence(locator, "equipment list missing")],
        ), []
    if not inventory:
        return _item(
            "equipment_materials", "gap",
            "方案点了设备，但输入里没有设备清单，无法判断是否具备。",
            [evidence(locator + ".equipment", ", ".join(requested))],
        ), []
    used = []
    fails = []
    conditional = []
    evidence_list = []
    for name in requested:
        match = _match_named(name, inventory)
        if match is None:
            fails.append(name)
            evidence_list.append(evidence(locator + ".equipment", name + " 不在清单中"))
            continue
        status = canon_status(first(match, ("status", "状态"), "unspecified"))
        evidence_list.append(evidence(
            (contract_path or "contracts") + ".equipment",
            "%s status=%s" % (match.get("name") or name, status),
        ))
        used.append(match)
        if status == "unavailable":
            fails.append(name)
        elif status in ("purchase", "outsource", "unspecified"):
            conditional.append("%s=%s" % (name, status))
        elif status != "on_hand":
            conditional.append("%s=%s" % (name, status))
    if fails:
        return _item(
            "equipment_materials", "fail",
            "设备不可用或不在清单中：" + ", ".join(fails),
            evidence_list, hard=True,
        ), used
    if conditional:
        return _item(
            "equipment_materials", "conditional",
            "设备还不能直接开工：" + ", ".join(conditional),
            evidence_list,
        ), used
    return _item("equipment_materials", "pass", "点名的设备都在清单中且状态为已具备。", evidence_list), used


def _material_item(plan, locator, inventory, contract_path):
    requested = []
    for raw in as_list(first(plan, ("materials", "consumables", "材料", "耗材"), [])):
        if isinstance(raw, dict):
            requested.append(raw)
        else:
            requested.append({"name": str(raw)})
    if not requested:
        return _item(
            "equipment_materials", "gap",
            "方案没有材料用量；不把库存默认为够用。这一项与设备分开记录。",
            [evidence(locator, "materials missing")],
        ), []
    # The equipment category is separate. Materials get their own item; pipeline
    # still requires both. Category name stays equipment_materials for the device
    # check. Use a distinct category so a pass on devices cannot hide a material gap.
    leads = []
    fails = []
    conditional = []
    evidence_list = []
    for raw in requested:
        name = str(first(raw, ("name", "名称"), ""))
        need = num(first(raw, ("qty", "quantity", "amount", "用量")))
        match = _match_named(name, inventory) if name else None
        if match is None:
            fails.append(name or "(unnamed)")
            evidence_list.append(evidence(locator + ".materials", "未在库存中找到 " + (name or "?")))
            continue
        on_hand = num(first(match, ("qty_on_hand", "quantity", "on_hand", "库存")))
        status = canon_status(first(match, ("status", "状态"), "unspecified"))
        lead = num(first(match, ("lead_time_days", "lead_days", "货期")))
        evidence_list.append(evidence(
            (contract_path or "contracts") + ".materials",
            "%s on_hand=%s need=%s status=%s lead=%s" % (name, on_hand, need, status, lead),
        ))
        if status == "unavailable":
            fails.append(name)
            continue
        if need is not None and on_hand is not None and need > on_hand + 1e-9:
            conditional.append("%s 缺少 %s" % (name, need - on_hand))
            if lead is not None:
                leads.append(lead)
            continue
        if status in ("purchase", "outsource", "unspecified"):
            conditional.append("%s=%s" % (name, status))
            if lead is not None:
                leads.append(lead)
        elif status != "on_hand":
            conditional.append("%s=%s" % (name, status))
    category = "materials"
    if fails:
        return _item(category, "fail", "材料不具备：" + ", ".join(fails), evidence_list, hard=True), leads
    if conditional:
        return _item(category, "conditional", "材料需要补齐：" + ", ".join(conditional), evidence_list), leads
    return _item(category, "pass", "点名材料的库存覆盖方案用量。", evidence_list), leads


def _time_item(plan, locator, used_equipment, lead_days):
    terms = []
    total = 0.0
    seen = False
    for index, step in enumerate(as_list(first(plan, ("steps", "步骤"), []))):
        if not isinstance(step, dict):
            continue
        hours = num(first(step, ("hours", "duration_h", "工时")))
        if hours is None:
            continue
        seen = True
        total += hours
        terms.append({"step": first(step, ("id", "name"), "step-%d" % (index + 1)), "hours": hours})
    bookings = []
    for equip in used_equipment:
        booking = num(first(equip, ("booking_days", "queue_days", "排期")))
        if booking is not None and canon_status(first(equip, ("status", "状态"), "")) == "on_hand":
            bookings.append(booking)
    wait_parts = []
    if bookings:
        wait_parts.append(max(bookings))
    if lead_days:
        wait_parts.append(max(lead_days))
    wait = max(wait_parts) if wait_parts else None
    formula_hours = " + ".join(str(item["hours"]) for item in terms) if terms else None
    numbers = {
        "occupied_hours": total if seen else None,
        "occupied_hours_terms": terms,
        "occupied_hours_formula": ("occupied_hours = %s = %s" % (formula_hours, total)) if seen else None,
        "wait_days": wait,
        "wait_days_formula": ("wait_days = max(%s) = %s" % (", ".join(str(part) for part in wait_parts), wait)) if wait is not None else None,
        "person_hours": None,
    }
    if not seen and wait is None:
        return _item(
            "time_cost", "gap",
            "步骤里没有工时，设备清单里也没有排期，不能给一个估计天数。",
            [evidence(locator + ".steps", "no hours")],
            numbers=numbers,
        ), numbers
    statement = "工时只加了写明小时数的步骤。"
    if numbers["occupied_hours_formula"]:
        statement += " " + numbers["occupied_hours_formula"] + "。"
    if numbers["wait_days_formula"]:
        statement += " " + numbers["wait_days_formula"] + "。"
    return _item(
        "time_cost", "pass", statement,
        [evidence(locator + ".steps", numbers["occupied_hours_formula"] or numbers["wait_days_formula"] or "time")],
        numbers=numbers,
    ), numbers


def _parameter_item(plan, locator, used_equipment):
    raw = first(plan, ("parameters", "params", "参数"), None)
    params = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("name", key)
                params.append(item)
            else:
                params.append({"name": key, "value": value})
    else:
        for item in as_list(raw):
            if isinstance(item, dict):
                params.append(item)
    if not params:
        return _item("parameter_range", "gap", "方案没有参数取值，不能视为落在设备量程内。", [evidence(locator, "parameters missing")])
    fails = []
    unknown = []
    evidence_list = []
    for param in params:
        name = str(first(param, ("name", "名称"), "parameter"))
        value = num(first(param, ("value", "取值")))
        unit = first(param, ("unit", "单位"))
        linked = _link_range(name, unit, param, used_equipment)
        if value is None or linked is None:
            unknown.append(name)
            evidence_list.append(evidence(locator + ".parameters", "%s 无法与量程比较" % name))
            continue
        lo, hi, source = linked
        if lo is not None and value < lo - 1e-9 or hi is not None and value > hi + 1e-9:
            fails.append("%s=%s 超出 [%s, %s]（%s）" % (name, value, lo, hi, source))
        evidence_list.append(evidence(locator + ".parameters", "%s=%s range %s..%s via %s" % (name, value, lo, hi, source)))
    if fails:
        return _item("parameter_range", "fail", "参数越界：" + "; ".join(fails), evidence_list, hard=True)
    if unknown:
        return _item("parameter_range", "conditional", "有参数没能连到量程：" + ", ".join(unknown), evidence_list)
    return _item("parameter_range", "pass", "写出的参数值都落在已关联的量程内。", evidence_list)


def _link_range(name, unit, param, equipment):
    explicit_lo = num(first(param, ("min", "low")))
    explicit_hi = num(first(param, ("max", "high")))
    if explicit_lo is not None or explicit_hi is not None:
        # A self-declared range is not a pass by itself; equipment still wins when linked.
        pass
    matches = []
    for equip in equipment:
        measures = first(equip, ("measures", "parameter", "quantity", "量"))
        if measures and norm_name(measures) == norm_name(name):
            matches.append(equip)
    if not matches:
        return None
    if len(matches) > 1:
        return None
    equip = matches[0]
    bounds = equip.get("range") if isinstance(equip.get("range"), dict) else {}
    lo = num(first(equip, ("min", "low"), first(bounds, ("min", "low"))))
    hi = num(first(equip, ("max", "high"), first(bounds, ("max", "high"))))
    equip_unit = first(equip, ("unit", "单位"), first(bounds, ("unit", "单位")))
    compatible = units_compatible(unit, equip_unit)
    if compatible is False:
        return None
    if lo is None and hi is None:
        return None
    return lo, hi, str(equip.get("name") or measures)


def _risk_item(plan, locator):
    risks = as_list(first(plan, ("risks", "风险", "exceptions"), []))
    specified = []
    for risk in risks:
        if not isinstance(risk, dict):
            continue
        trigger = first(risk, ("trigger", "condition", "触发"))
        action = first(risk, ("mitigation", "fallback", "处置", "action"))
        if trigger and action:
            specified.append(risk)
    if specified:
        return _item(
            "risk_exception", "pass",
            "至少一条风险同时写了触发条件和处置。",
            [evidence(locator + ".risks", str(specified[0])[:180])],
        )
    return _item(
        "risk_exception", "gap",
        "风险没有触发条件和处置；“注意安全”不算一条可执行的异常路径。",
        [evidence(locator, "risks underspecified")],
    )


def _ethics_item(plan, locator, ethics, contract_path):
    text = "\n".join(strings_of(plan))
    hits = [word for word in ETHICS_WORDS if word.lower() in text.lower()]
    status = canon_status(first(ethics, ("approval_status", "status", "审批状态"), None))
    # canon_status does not know approved/pending/not_required. Keep the raw token.
    raw = str(first(ethics, ("approval_status", "status", "审批状态"), "") or "").strip().lower()
    approved = raw in ("approved", "exempt", "not_required", "已批", "豁免", "不涉及")
    pending = raw in ("pending", "submitted", "审批中", "待批")
    rejected = raw in ("rejected", "denied", "未批", "驳回")
    if not hits and (not raw or approved):
        return _item(
            "ethics_safety", "not_indicated",
            "方案原文没有人体、动物、危险试剂或个人数据的触发词。审批状态：%s。" % (raw or "未单列"),
            [evidence(locator, "ethics keywords absent")],
        )
    if hits and approved:
        return _item(
            "ethics_safety", "pass",
            "文本触发了伦理/安全词，审批状态为已覆盖：" + raw,
            [evidence((contract_path or "contracts") + ".ethics", raw)],
        )
    if rejected:
        return _item(
            "ethics_safety", "fail",
            "伦理或安全审批状态是拒绝，不能开工。",
            [evidence((contract_path or "contracts") + ".ethics", raw)],
            hard=True,
        )
    if pending or hits:
        return _item(
            "ethics_safety", "conditional",
            "涉及伦理或安全（%s），当前审批状态不足以开工：%s。" % (", ".join(hits) or "合同", raw or "未写"),
            [evidence(locator, ", ".join(hits) or raw)],
        )
    return _item("ethics_safety", "gap", "审批状态无法解释。", [evidence(locator, raw or "ethics")])


def _sample_item(plan, locator, samples, contract_path):
    required = num(first(plan.get("samples") if isinstance(plan.get("samples"), dict) else {}, ("n_required", "n", "数量"), None))
    if required is None:
        required = num(first(plan, ("n_samples", "sample_size"), None))
    available = num(first(samples if isinstance(samples, dict) else {}, ("n_available", "n", "可用")))
    if required is None and available is None:
        return _item("samples", "gap", "样本需求量和可用量都没有写。", [evidence(locator, "samples missing")])
    if required is None or available is None:
        return _item(
            "samples", "conditional",
            "样本量只有一侧：需要 %s，可用 %s。" % (required, available),
            [evidence(locator + ".samples", "required=%s available=%s" % (required, available))],
        )
    if required > available + 1e-9:
        return _item(
            "samples", "fail",
            "需要样本 %s，可用 %s，数量不够。" % (required, available),
            [evidence((contract_path or "contracts") + ".samples", "n_available=%s" % available)],
            hard=True, numbers={"n_required": required, "n_available": available},
        )
    return _item(
        "samples", "pass",
        "可用样本 %s 覆盖需求 %s。" % (available, required),
        [evidence((contract_path or "contracts") + ".samples", "n_available=%s" % available)],
        numbers={"n_required": required, "n_available": available},
    )


def _match_named(name, rows):
    target = norm_name(name)
    if len(target) < 2:
        return None
    hits = []
    for row in rows:
        label = norm_name(first(row, ("name", "model", "名称", "型号"), ""))
        if label and label == target:
            hits.append(row)
    if len(hits) == 1:
        return hits[0]
    return None


def _least_blocked(reviews):
    def rank(item):
        hard = len(item["hard_fails"])
        gaps = sum(1 for check in item["items"] if check["status"] in ("gap", "conditional", "fail"))
        return (hard, gaps, item["plan_id"])
    return sorted(reviews, key=rank)[0]


def _summary(reviews, feasible, chosen):
    parts = ["共审查 %d 个方案版本。" % len(reviews)]
    for item in reviews:
        parts.append("%s = %s" % (item["plan_id"], item["verdict"]))
    if feasible:
        parts.append("可以开工的版本是 %s。" % feasible[0]["plan_id"])
    else:
        parts.append("没有无条件可开工的版本。阻塞最少的是 %s，仍需先满足列出的条件。" % chosen["plan_id"])
    return "".join(parts)


def _confirmations(reviews):
    rows = []
    for review in reviews:
        for item in review["items"]:
            if item["hard"] or item["status"] in ("gap", "conditional"):
                rows.append({
                    "plan_id": review["plan_id"],
                    "item": item["category"],
                    "why": item["statement"],
                    "blocking": bool(item["hard"] or item["status"] == "gap"),
                })
    return rows


def _checks(reviews):
    silent = []
    for review in reviews:
        for item in review["items"]:
            if item["status"] == "pass" and not item["evidence"]:
                silent.append(review["plan_id"] + ":" + item["category"])
    covered = set()
    for review in reviews:
        covered.update(item["category"] for item in review["items"])
    needed = set(CATEGORIES + ["samples", "materials"])
    return [
        {"name": "no_silent_pass", "ok": not silent, "detail": silent},
        {"name": "categories_present", "ok": needed <= covered or not reviews, "detail": sorted(needed - covered)},
        {"name": "verdicts_closed", "ok": all(item["verdict"] in ("feasible", "conditional", "infeasible") for item in reviews), "detail": [item["verdict"] for item in reviews]},
    ]
