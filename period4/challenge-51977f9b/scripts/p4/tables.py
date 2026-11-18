"""Clean, describe, plot and query only supplied tables."""
from __future__ import annotations

import math
import os
import re
import sqlite3
import statistics

from p4.util import MISSING_TOKENS, find_key, num, sane, write_json

SQL_BAD = re.compile(
    r"(?i)\b(attach|detach|pragma|load_extension|insert|update|delete|drop|alter|create|replace|vacuum)\b"
)


def analyze(bundle, profile, output_dir):
    if profile == "sql":
        return _sql(bundle)
    rows, path = _rows(bundle)
    if not rows:
        return _failed("没有读到数据表。不推断总体，也不填补缺失值。")
    if profile == "clean":
        return _clean(bundle, rows, path)
    if profile == "viz":
        return _viz(rows, path, output_dir)
    if profile == "code":
        return _code(bundle, rows, path, output_dir)
    return _stats(rows, path)


def _rows(bundle):
    for table in bundle["tables"]:
        if table.get("rows"):
            return table["rows"], table["path"]
    return [], None


def _is_missing(value):
    if value is None:
        return True
    text = str(value).strip().lower()
    return text in MISSING_TOKENS


def _clean(bundle, rows, path):
    dictionary = bundle["case"].get("dictionary") if isinstance(bundle["case"].get("dictionary"), dict) else {}
    missing_marks = {str(item).strip().lower() for item in dictionary.get("missing", [])}
    missing_marks.update(MISSING_TOKENS)
    factors = dictionary.get("conversions") if isinstance(dictionary.get("conversions"), list) else []
    cleaned = []
    missing_count = 0
    converted = []
    for index, row in enumerate(rows):
        out = {}
        for key, value in row.items():
            text = "" if value is None else str(value).strip()
            if text.lower() in missing_marks:
                out[key] = None
                missing_count += 1
                continue
            factor = _factor(key, text, factors)
            if factor is not None:
                converted.append({"row": index, "column": key, "from": text, "to": factor[0]})
                out[key] = factor[0]
            else:
                out[key] = value
        cleaned.append(out)
    seen = {}
    duplicate_groups = []
    kept = []
    for index, row in enumerate(cleaned):
        key = tuple(sorted((str(k), "" if v is None else str(v)) for k, v in row.items()))
        if key in seen:
            duplicate_groups.append({"keep": seen[key], "drop": index})
            continue
        seen[key] = index
        kept.append(row)
    report = {
        "rows_in": len(rows),
        "rows_out": len(kept),
        "missing_cells": missing_count,
        "duplicate_groups": len(duplicate_groups),
        "conversions": len(converted),
        "imputed_cells": 0,
    }
    return {
        "status": "success",
        "summary": "清洗 %d 行，保留 %d 行，缺失单元格 %d 个未填补，重复组 %d 个。" % (
            report["rows_in"], report["rows_out"], report["missing_cells"], report["duplicate_groups"]),
        "primary": {"rows": kept, "quality": report, "conversions": converted, "duplicates": duplicate_groups, "source": path},
        "sources": [{"locator": path, "quote": "rows=%d" % len(rows)}],
        "uncertainties": [{"id": "u-impute", "topic": "clean", "detail": "缺失和无效值保持为空，没有用均值或 0 填补。", "scope": True}],
        "checks": [
            {"name": "imputed_cells", "ok": report["imputed_cells"] == 0, "detail": 0},
            {"name": "report_matches_rows", "ok": report["rows_out"] == len(kept), "detail": len(kept)},
        ],
        "change_log": [{"id": "c-clean", "decision": "只标记缺失、去掉完全重复的行，并按字典中的换算系数转换。", "evidence": str(report)}],
        "confirmations": [{"item": "quality", "why": "报告数字等于结果表的行数和缺失计数。"}],
    }


def _factor(column, text, factors):
    value = num(text)
    if value is None:
        return None
    for item in factors:
        if not isinstance(item, dict):
            continue
        if str(item.get("column")) != str(column):
            continue
        multiplier = num(item.get("factor"))
        if multiplier is None:
            continue
        return (sane(value * multiplier), item.get("to"))
    return None


def _numeric_columns(rows):
    columns = []
    if not rows:
        return columns
    for key in rows[0].keys():
        values = []
        ok = True
        for row in rows:
            if _is_missing(row.get(key)):
                continue
            value = num(row.get(key))
            if value is None:
                ok = False
                break
            values.append(value)
        if ok and values:
            columns.append((key, values))
    return columns


def _describe(values):
    count = len(values)
    mean = sum(values) / count
    std = statistics.stdev(values) if count >= 2 else None
    ordered = sorted(values)
    mid = ordered[count // 2] if count % 2 else (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    return {
        "n": count,
        "mean": sane(mean),
        "stdev_sample": None if std is None else sane(std),
        "median": sane(mid),
        "min": sane(ordered[0]),
        "max": sane(ordered[-1]),
        "p_value": None,
    }


def _stats(rows, path):
    columns = _numeric_columns(rows)
    if not columns:
        return _failed("表里没有可计算的数值列。")
    described = {name: _describe(values) for name, values in columns}
    return {
        "status": "success",
        "summary": "描述 %d 个数值列。没有做假设检验，p 值保持为空。" % len(described),
        "primary": {"columns": described, "source": path, "test": None},
        "sources": [{"locator": path, "quote": "n=%d" % len(rows)}],
        "uncertainties": [{"id": "u-test", "topic": "stats", "detail": "材料没有指定检验方法，不报告 p 值。", "scope": True}],
        "checks": [{"name": "p_value_null", "ok": all(item["p_value"] is None for item in described.values()), "detail": len(described)}],
        "change_log": [{"id": "c-stats", "decision": "只计算样本量、均值、样本标准差、中位数和极值。", "evidence": path or ""}],
        "confirmations": [{"item": name, "why": "n=%s mean=%s" % (item["n"], item["mean"])} for name, item in described.items()],
    }


def _viz(rows, path, output_dir):
    columns = _numeric_columns(rows)
    if not columns:
        return _failed("没有数值列，不画图。")
    name, values = columns[0]
    svg, note = _svg(name, values)
    os.makedirs(output_dir, exist_ok=True)
    svg_path = os.path.join(output_dir, "chart.svg")
    with open(svg_path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    described = _describe(values)
    return {
        "status": "success",
        "summary": "用列 %s 的 %d 个非缺失值画了可编辑 SVG，没有把图当成新的统计结论。" % (name, len(values)),
        "primary": {"chart": "chart.svg", "column": name, "summary": described, "note": note, "source": path},
        "sources": [{"locator": path or "table", "quote": "%s n=%d" % (name, len(values))}],
        "uncertainties": [{"id": "u-viz", "topic": "viz", "detail": note, "scope": True}],
        "checks": [{"name": "svg_written", "ok": os.path.exists(svg_path), "detail": svg_path}],
        "change_log": [{"id": "c-viz", "decision": "图形只编码已读到的数值。", "evidence": name}],
        "confirmations": [{"item": name, "why": note}],
    }


def _svg(name, values):
    if len(values) > 40:
        lo, hi = min(values), max(values)
        bins = [0] * 10
        if hi == lo:
            bins[0] = len(values)
            labels = ["%s" % sane(lo)]
        else:
            width = (hi - lo) / 10
            for value in values:
                index = min(9, int((value - lo) / width))
                bins[index] += 1
            labels = ["%s-%s" % (sane(lo + i * width), sane(lo + (i + 1) * width)) for i in range(10)]
        body, note = _bars(labels, bins, name + " 计数")
        return body, "行数超过 40，图中是 10 个等宽计数箱，不是逐点原值。%s" % note
    labels = [str(i + 1) for i in range(len(values))]
    return _bars(labels, values, name)


def _bars(labels, values, title):
    peak = max(values) if values else 1
    peak = peak or 1
    width = 36
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="220">' % (60 + width * len(values)),
        '<text x="8" y="18" font-size="12">%s</text>' % _xml(title),
    ]
    for index, value in enumerate(values):
        height = 150 * (value / peak)
        x = 40 + index * width
        y = 180 - height
        parts.append('<rect x="%d" y="%s" width="24" height="%s" fill="#2f6f4e"/>' % (x, sane(y), sane(height)))
        parts.append('<text x="%d" y="198" font-size="9">%s</text>' % (x, _xml(labels[index][:8])))
        parts.append('<text x="%d" y="%s" font-size="9">%s</text>' % (x, sane(y - 2), _xml(sane(value))))
    parts.append("</svg>")
    return "\n".join(parts), "柱高按该列最大值归一，数字标在柱上。"


def _xml(value):
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _code(bundle, rows, path, output_dir):
    ops, _where = find_key(bundle["case"], ("operations",))
    current = list(rows)
    log = []
    if isinstance(ops, list) and ops:
        for index, op in enumerate(ops):
            if not isinstance(op, dict):
                log.append({"step": index, "ok": False, "detail": "操作不是对象，跳过。"})
                continue
            kind = str(op.get("op") or "")
            column = str(op.get("column") or "")
            if kind == "filter":
                expected = str(op.get("equals"))
                current = [row for row in current if str(row.get(column)) == expected]
                log.append({"step": index, "op": "filter", "rows": len(current)})
            elif kind == "mean":
                values = [num(row.get(column)) for row in current]
                values = [value for value in values if value is not None]
                log.append({"step": index, "op": "mean", "column": column, "n": len(values), "mean": None if not values else sane(sum(values) / len(values))})
            elif kind == "count":
                log.append({"step": index, "op": "count", "rows": len(current)})
            else:
                log.append({"step": index, "ok": False, "detail": "不执行未列出的操作 %s。" % kind})
    else:
        described = {name: _describe(values) for name, values in _numeric_columns(current)}
        log.append({"step": 0, "op": "describe", "columns": described})
    script = _script(log)
    os.makedirs(output_dir, exist_ok=True)
    write_json(os.path.join(output_dir, "code_result.json"), {"steps": log, "rows_out": current})
    with open(os.path.join(output_dir, "operations.py"), "w", encoding="utf-8") as handle:
        handle.write(script)
    return {
        "status": "success",
        "summary": "按列出的过滤、计数和均值操作处理了表，没有执行任意代码。",
        "primary": {"steps": log, "rows_out": len(current), "source": path, "script": "operations.py"},
        "sources": [{"locator": path or "table", "quote": "rows=%d" % len(rows)}],
        "uncertainties": [{"id": "u-code", "topic": "code", "detail": "只运行 filter、count、mean 或列描述。", "scope": True}],
        "checks": [{"name": "restricted_ops", "ok": True, "detail": len(log)}],
        "change_log": [{"id": "c-code", "decision": "操作序列写进 operations.py，并与结果同时留下。", "evidence": "steps=%d" % len(log)}],
        "confirmations": [{"item": "steps", "why": str(log)[:180]}],
    }


def _script(log):
    return (
        "# Generated from the operations that this run actually applied.\n"
        "# It is a record of those steps, not a general code executor.\n"
        "STEPS = %r\n" % log
    )


def _sql(bundle):
    target = None
    for table in bundle["tables"]:
        if table.get("sqlite"):
            target = table
            break
    if target is None:
        return _failed("没有 SQLite 数据库，不编造查询结果。")
    query, _path = find_key(bundle["case"], ("query", "sql"))
    query = query.strip() if isinstance(query, str) else ""
    if not _safe_sql(query):
        return {
            "status": "partial",
            "summary": "没有一条可执行的只读查询。下面只列出表名和行数。",
            "primary": {"tables": target.get("sql_tables") or [], "rows": None, "query": query or None},
            "sources": [{"locator": target["path"], "quote": "schema only"}],
            "uncertainties": [{"id": "u-sql", "topic": "sql", "detail": "拒绝执行非单条 SELECT/WITH，或含写入关键字的语句。", "scope": False}],
            "checks": [{"name": "readonly", "ok": True, "detail": "rejected"}],
            "change_log": [{"id": "c-sql", "decision": "不安全或缺失的查询不执行。", "evidence": target["path"]}],
            "confirmations": [],
        }
    uri = "file:%s?mode=ro" % target["sqlite"]
    conn = sqlite3.connect(uri, uri=True)
    try:
        cursor = conn.execute(query)
        header = [item[0] for item in cursor.description or []]
        fetched = cursor.fetchmany(200)
    finally:
        conn.close()
    rows = [dict(zip(header, row)) for row in fetched]
    return {
        "status": "success",
        "summary": "只读查询返回 %d 行。" % len(rows),
        "primary": {"tables": target.get("sql_tables") or [], "query": query, "columns": header, "rows": rows},
        "sources": [{"locator": target["path"], "quote": query[:180]}],
        "uncertainties": [{"id": "u-sql", "topic": "sql", "detail": "最多返回 200 行。", "scope": True}],
        "checks": [{"name": "readonly", "ok": True, "detail": len(rows)}],
        "change_log": [{"id": "c-sql", "decision": "在只读连接上执行了这一条查询。", "evidence": query[:180]}],
        "confirmations": [{"item": "query", "why": "rows=%d" % len(rows)}],
    }


def _safe_sql(query):
    if not query:
        return False
    text = query.strip().rstrip(";").strip()
    if not text or ";" in text:
        return False
    if not re.match(r"(?is)^(select|with)\b", text):
        return False
    if SQL_BAD.search(text):
        return False
    return True


def _failed(summary):
    return {
        "status": "failed",
        "summary": summary,
        "primary": {},
        "sources": [],
        "uncertainties": [{"id": "u-shape", "topic": "input", "detail": summary, "scope": False}],
        "checks": [{"name": "input_shape", "ok": False, "detail": summary}],
        "change_log": [{"id": "c-stop", "decision": "没有表，不产生分析结果。", "evidence": "failed"}],
        "confirmations": [],
    }
