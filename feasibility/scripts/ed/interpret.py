"""Explain a measurement table: trend, anomalies, associated factors, next check."""
from __future__ import annotations

from ed.util import evidence, find_key, first, num

X_NAMES = {"time", "time_h", "t", "day", "hour", "x", "dose", "concentration", "时间", "浓度"}
Y_NAMES = {"signal", "value", "y", "response", "reading", "yield", "od", "intensity", "读数", "响应"}
ID_NAMES = {"sample", "sample_id", "id", "well", "样品", "孔"}
BATCH_NAMES = {"batch", "lot", "batch_id", "批次"}
CHANNEL_NAMES = {"channel", "ch", "通道"}


def analyze(bundle):
    tables = _tables(bundle)
    if not tables:
        return {
            "status": "failed",
            "summary": "没有读到数值表，不能解释趋势或异常。",
            "experiment_plan": {
                "hypothesis": None,
                "variables": [],
                "controls": [],
                "steps": [],
                "parameters": [],
                "resources": [],
                "readout": None,
                "conditions_before_execution": ["需要带表头的读数表。"],
            },
            "evidence_and_risks": {"series": [], "anomalies": [], "causes": []},
            "confirmations": [{"item": "读数表", "why": "没有可计算的列", "blocking": True}],
            "uncertainties": [{"id": "u-no-table", "topic": "data", "detail": "no numeric table"}],
            "change_log": [{"id": "c-stop", "decision": "没有读数时不编写趋势结论。", "evidence": "input"}],
            "checks": [{"name": "table_present", "ok": False, "detail": "missing"}],
            "mode_result": {},
        }

    series_reports = []
    for table in tables:
        report = _series(table)
        if report:
            series_reports.append(report)
    if not series_reports:
        return {
            "status": "partial",
            "summary": "找到了表，但没有足够的数值列可计算。",
            "experiment_plan": _plan([], [], "没有可计算的序列。"),
            "evidence_and_risks": {"series": [], "anomalies": [], "causes": []},
            "confirmations": [{"item": "数值列", "why": "表头对不上读数", "blocking": True}],
            "uncertainties": [{"id": "u-no-numeric", "topic": "columns", "detail": "no y column"}],
            "change_log": [{"id": "c-no-numeric", "decision": "不对非数值列做趋势拟合。", "evidence": tables[0]["path"]}],
            "checks": [{"name": "numeric_series", "ok": False, "detail": "none"}],
            "mode_result": {},
        }

    primary = series_reports[0]
    status = "success" if primary["n"] >= 3 and primary["anomalies_called"] else "partial"
    if primary["n"] >= 3 and primary["trend"]["slope"] is not None:
        status = "success" if primary["n"] >= 5 or not primary["anomaly_withheld"] else "partial"
    causes = primary["causes"]
    next_steps = _next_steps(primary)
    summary = _summary(primary)
    return {
        "status": status,
        "summary": summary,
        "experiment_plan": _plan(primary, next_steps, summary),
        "evidence_and_risks": {
            "series": series_reports,
            "anomalies": primary["anomalies"],
            "causes": causes,
            "non_claims": primary["non_claims"],
            "risks": [{
                "trigger": "把相关写成机理",
                "consequence": "批次或通道差异会被误当成反应机理",
                "action": "原因栏只保留与分组共变的因子，并写明排除组。",
            }],
        },
        "confirmations": _confirmations(primary),
        "uncertainties": primary["uncertainties"],
        "change_log": [{
            "id": "c-no-mechanism",
            "decision": "没有在表里共变的因子时，不补充化学或生物机理。",
            "evidence": primary["path"],
        }],
        "checks": [
            {"name": "anomaly_rows_exist", "ok": all(1 <= item["row"] <= primary["n"] for item in primary["anomalies"]), "detail": primary["n"]},
            {"name": "cause_has_exclusion", "ok": all(item.get("exclusion_levels") for item in causes), "detail": len(causes)},
            {"name": "slope_recomputed_from_rows", "ok": primary["trend"]["n"] == primary["n"], "detail": primary["trend"]["formula"]},
        ],
        "mode_result": {"primary": primary["path"]},
    }


def _plan(primary, next_steps, summary):
    if not primary:
        return {
            "hypothesis": None, "variables": [], "controls": [], "steps": [],
            "parameters": [], "resources": [], "readout": None,
            "conditions_before_execution": [summary],
        }
    return {
        "hypothesis": "读数相对 %s 的变化可以用表内斜率描述，不外推机理。" % (primary["x_name"] or "行序"),
        "variables": [
            {"name": primary["y_name"], "role": "dependent"},
            {"name": primary["x_name"] or "row", "role": "independent"},
        ],
        "controls": [{"name": level, "role": "exclusion group"} for level in _exclusion_levels(primary)],
        "steps": next_steps,
        "parameters": [],
        "resources": [{"table": primary["path"], "rows": primary["n"]}],
        "readout": primary["y_name"],
        "conditions_before_execution": [item["detail"] for item in primary["uncertainties"]],
    }


def _tables(bundle):
    found = []
    value, path = find_key(bundle["case"], ("measurements", "observations", "data", "rows", "读数"))
    if isinstance(value, list) and value and isinstance(value[0], dict):
        found.append({"path": "case.json:%s" % path, "rows": value})
    for info in bundle["files"]:
        rows = info.get("rows")
        if rows and info["path"] != "case.json":
            found.append({"path": info["path"], "rows": rows})
    return found


def _series(table):
    rows = [row for row in table["rows"] if isinstance(row, dict)]
    if not rows:
        return None
    roles = {name: _role(name) for name in rows[0].keys()}
    y_name = _pick(roles, "y") or _first_numeric(rows, roles, skip={"x", "id"})
    if not y_name:
        return None
    x_name = _pick(roles, "x")
    batch_name = _pick(roles, "batch")
    channel_name = _pick(roles, "channel")
    parsed = []
    for index, row in enumerate(rows):
        parsed.append({
            "row": index + 1,
            "x": num(row.get(x_name)) if x_name else float(index),
            "y": num(row.get(y_name)),
            "batch": row.get(batch_name) if batch_name else None,
            "channel": row.get(channel_name) if channel_name else None,
            "x_was_index": x_name is None,
        })
    usable = [item for item in parsed if item["y"] is not None and item["x"] is not None]
    trend = _trend(usable)
    anomalies, withheld, cutoff = _anomalies(usable)
    causes = []
    non_claims = ["不从读数本身推断未出现在列名中的反应机理。"]
    uncertainties = []
    if len(usable) < 5:
        withheld = True
        anomalies = []
        uncertainties.append({
            "id": "u-n",
            "topic": "replicates",
            "detail": "有效行数 %d，少于 5，不调用稳健异常阈值。" % len(usable),
        })
    else:
        causes = _causes(usable, anomalies, "batch") + _causes(usable, anomalies, "channel")
    aliased = _aliased(usable, "batch")
    if aliased:
        uncertainties.append({
            "id": "u-alias",
            "topic": "alias",
            "detail": "批次的 %s 区间没有重叠，合并斜率与批次差异混在一起。" % (x_name or "行序"),
        })
    return {
        "path": table["path"],
        "x_name": x_name,
        "y_name": y_name,
        "n": len(usable),
        "trend": trend,
        "aliased_with": "batch" if aliased else None,
        "group_means": _group_means(usable, "batch"),
        "anomalies": anomalies,
        "anomalies_called": not withheld,
        "anomaly_withheld": withheld,
        "cutoff": cutoff,
        "causes": causes,
        "non_claims": non_claims,
        "uncertainties": uncertainties,
    }


def _role(name):
    key = str(name).strip().lower()
    if key in X_NAMES:
        return "x"
    if key in Y_NAMES:
        return "y"
    if key in BATCH_NAMES:
        return "batch"
    if key in CHANNEL_NAMES:
        return "channel"
    if key in ID_NAMES:
        return "id"
    return None


def _pick(roles, role):
    for name, assigned in roles.items():
        if assigned == role:
            return name
    return None


def _first_numeric(rows, roles, skip):
    for name, role in roles.items():
        if role in skip:
            continue
        if any(num(row.get(name)) is not None for row in rows):
            return name
    return None


def _trend(rows):
    n = len(rows)
    if n < 2:
        return {"n": n, "slope": None, "intercept": None, "formula": "n<2"}
    xs = [item["x"] for item in rows]
    ys = [item["y"] for item in rows]
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 1e-15:
        return {"n": n, "slope": None, "intercept": my, "formula": "sxx=0"}
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    intercept = my - slope * mx
    return {
        "n": n,
        "slope": slope,
        "intercept": intercept,
        "mean_x": mx,
        "mean_y": my,
        "formula": "slope = Σ((x-mean_x)*(y-mean_y)) / Σ((x-mean_x)^2)",
    }


def _anomalies(rows):
    values = [item["y"] for item in rows]
    if len(values) < 5:
        return [], True, None
    ordered = sorted(values)
    median = _median(ordered)
    deviations = sorted(abs(value - median) for value in values)
    mad = _median(deviations)
    sigma = 1.4826 * mad
    flagged = []
    if sigma <= 1e-12:
        for item in rows:
            if abs(item["y"] - median) > 1e-9:
                flagged.append(_flag(item, median, "mad=0; value differs from median"))
        return flagged, False, {"rule": "different_from_median", "median": median, "sigma": 0}
    limit = 3 * sigma
    for item in rows:
        if abs(item["y"] - median) > limit + 1e-9:
            flagged.append(_flag(item, median, "abs(y-median) > 3*1.4826*MAD"))
    return flagged, False, {"rule": "mad", "median": median, "sigma": sigma, "limit": limit}


def _flag(item, median, rule):
    return {
        "row": item["row"],
        "y": item["y"],
        "x": item["x"],
        "batch": item["batch"],
        "channel": item["channel"],
        "median": median,
        "deviation": item["y"] - median,
        "rule": rule,
    }


def _median(values):
    n = len(values)
    if n == 0:
        return None
    mid = n // 2
    if n % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def _causes(rows, anomalies, factor):
    if not anomalies:
        return []
    if any(item.get(factor) in (None, "") for item in rows):
        return []
    anom_rows = {item["row"] for item in anomalies}
    groups = {}
    for item in rows:
        level = item[factor]
        bucket = groups.setdefault(level, {"n": 0, "anom": 0, "rows": []})
        bucket["n"] += 1
        bucket["rows"].append(item["row"])
        if item["row"] in anom_rows:
            bucket["anom"] += 1
    total = len(anom_rows)
    found = []
    for level, info in groups.items():
        if info["anom"] == 0:
            continue
        if info["anom"] / total < 0.8:
            continue
        clean = [other for other, other_info in groups.items()
                 if other != level and other_info["anom"] == 0 and other_info["n"] >= 2]
        if not clean:
            continue
        found.append({
            "factor": factor,
            "level": level,
            "support_rows": [item["row"] for item in rows if item[factor] == level and item["row"] in anom_rows],
            "exclusion_levels": clean,
            "claim": "association",
            "mechanism": None,
            "statement": "%s=%s 覆盖了异常行，%s 没有异常行。这只说明共变，不是机理。" % (
                factor, level, ",".join(str(item) for item in clean),
            ),
        })
    return found


def _aliased(rows, factor):
    grouped = {}
    for item in rows:
        if item.get(factor) in (None, ""):
            return False
        grouped.setdefault(item[factor], []).append(item["x"])
    if len(grouped) < 2:
        return False
    spans = []
    for values in grouped.values():
        spans.append((min(values), max(values)))
    spans.sort()
    for earlier, later in zip(spans, spans[1:]):
        if earlier[1] >= later[0] - 1e-9:
            return False
    return True


def _group_means(rows, factor):
    grouped = {}
    for item in rows:
        if item.get(factor) in (None, ""):
            continue
        grouped.setdefault(item[factor], []).append(item["y"])
    means = []
    for level, values in grouped.items():
        means.append({"level": level, "n": len(values), "mean": sum(values) / len(values)})
    means.sort(key=lambda item: str(item["level"]))
    return means


def _exclusion_levels(primary):
    levels = []
    for cause in primary["causes"]:
        for level in cause.get("exclusion_levels") or []:
            if level not in levels:
                levels.append(level)
    return levels


def _next_steps(primary):
    steps = []
    if primary["anomalies"]:
        rows = ", ".join(str(item["row"]) for item in primary["anomalies"])
        steps.append({
            "action": "回算异常行",
            "detail": "按 %s 的列 %s 重算中位数和阈值，核对行 %s。" % (primary["path"], primary["y_name"], rows),
        })
    for cause in primary["causes"]:
        steps.append({
            "action": "分开因子",
            "detail": "用与排除组相同的 %s 取值重复 %s=%s，避免和批次绑在一起。" % (
                primary["x_name"] or "行序", cause["factor"], cause["level"],
            ),
        })
    if primary["n"] < 5:
        steps.append({"action": "增加重复", "detail": "有效行数不足 5，先补重复再谈异常点。"})
    if not steps:
        steps.append({"action": "保留原表", "detail": "当前表没有触发复核动作。"})
    return steps


def _confirmations(primary):
    rows = []
    if primary["anomaly_withheld"]:
        rows.append({"item": "异常阈值", "why": "行数不足，阈值没有启用。", "blocking": True})
    if primary["aliased_with"]:
        rows.append({"item": "时间与批次", "why": "二者在这张表里没有交叉，不能单独解释斜率。", "blocking": False})
    if not primary["causes"] and primary["anomalies"]:
        rows.append({"item": "原因", "why": "异常行没有集中在某个有干净对照的批次或通道上。", "blocking": False})
    return rows


def _summary(primary):
    slope = primary["trend"]["slope"]
    text = "表 %s 的 %s 对 %s，n=%d，斜率=%s。" % (
        primary["path"], primary["y_name"], primary["x_name"] or "行序", primary["n"], slope,
    )
    if primary["aliased_with"]:
        text += "该斜率与 %s 混杂。" % primary["aliased_with"]
    if primary["anomalies"]:
        text += "异常行：" + ",".join(str(item["row"]) for item in primary["anomalies"]) + "。"
    else:
        text += "没有调用异常点。" if primary["anomaly_withheld"] else "没有点超过阈值。"
    if primary["causes"]:
        text += "共变因子：" + "; ".join(item["statement"] for item in primary["causes"])
    else:
        text += "没有写出机理。"
    return text
