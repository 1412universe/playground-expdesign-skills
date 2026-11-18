"""Load one case, run the locked mode, write result.json and a Chinese review."""
from __future__ import annotations

import os

from ed import compare, feasibility, interpret, optimize
from ed.util import find_key, sane, write_json

MODES = {
    "feasibility": feasibility.analyze,
    "optimize": optimize.analyze,
    "compare": compare.analyze,
    "interpret": interpret.analyze,
}

FIELD_ALIAS = {
    "experiment_plan": "experiment_plan",
    "plan": "experiment_plan",
    "方案": "experiment_plan",
    "实验方案": "experiment_plan",
    "evidence_and_risks": "evidence_and_risks",
    "risks": "evidence_and_risks",
    "依据与风险": "evidence_and_risks",
    "依据": "evidence_and_risks",
    "confirmations": "confirmations",
    "确认项": "confirmations",
    "summary": "summary",
    "status": "status",
    "uncertainties": "uncertainties",
    "uncertainty": "uncertainties",
    "sources": "sources",
    "change_log": "change_log",
}


def run(input_dir, output_dir, mode):
    if mode not in MODES:
        raise SystemExit("unknown mode %s" % mode)
    from ed.ingest import load
    bundle = load(input_dir)
    body = MODES[mode](bundle)
    result = _envelope(bundle, body, mode)
    os.makedirs(output_dir, exist_ok=True)
    write_json(os.path.join(output_dir, "result.json"), result)
    write_json(os.path.join(output_dir, "checks.json"), {"checks": result["checks"]})
    write_json(os.path.join(output_dir, "sources.json"), {"sources": result["sources"]})
    write_json(os.path.join(output_dir, "change_log.json"), {"change_log": result["change_log"]})
    with open(os.path.join(output_dir, "review.md"), "w", encoding="utf-8") as handle:
        handle.write(_review(result))
    return result


def _envelope(bundle, body, mode):
    sources = [{
        "path": item["path"],
        "sha256": item["sha256"],
        "bytes": item["bytes"],
        "reader": item.get("reader"),
        "error": item.get("error"),
        "truncated": item.get("truncated"),
    } for item in bundle["files"]]
    unread = [item["path"] for item in sources if item.get("error")]
    uncertainties = list(body.get("uncertainties") or [])
    for path in unread:
        uncertainties.append({
            "id": "u-unread-%s" % path,
            "topic": "file",
            "detail": "文件 %s 没有被解析，结论没有使用它的内容。" % path,
        })
    status = body.get("status") or "partial"
    if status == "success" and unread:
        status = "partial"
    result = {
        "case_id": bundle["case"].get("case_id") or bundle["case"].get("id"),
        "status": status,
        "mode": mode,
        "summary": body.get("summary"),
        "experiment_plan": body.get("experiment_plan") or {},
        "evidence_and_risks": body.get("evidence_and_risks") or {},
        "confirmations": body.get("confirmations") or [],
        "uncertainties": uncertainties,
        "sources": sources,
        "change_log": list(body.get("change_log") or []),
        "checks": list(body.get("checks") or []),
        "runtime_seconds": None,
    }
    if bundle["case"].get("example_only") is True:
        result["example_banner"] = "示意输出，不是平台正式案例，不能当作正式答案。"
    contract, _path = find_key(bundle["case"], ("output_contract", "contract"))
    result["output_contract_echo"] = contract if isinstance(contract, (dict, list)) else None
    _fill_contract(result, contract)
    if unread and status != "failed":
        result["change_log"].append({
            "id": "c-unread",
            "decision": "未解析的文件不参与数值结论。",
            "evidence": ",".join(unread),
        })
    return sane(result)


def _fill_contract(result, contract):
    names = []
    if isinstance(contract, dict):
        names = [str(key) for key in contract.keys()]
    elif isinstance(contract, list):
        names = [str(item) for item in contract if isinstance(item, str)]
    missing = []
    for name in names:
        if name in result:
            continue
        alias = FIELD_ALIAS.get(name) or FIELD_ALIAS.get(name.lower())
        if alias and alias in result:
            result[name] = result[alias]
        else:
            result[name] = None
            missing.append(name)
    if missing:
        result["uncertainties"].append({
            "id": "u-contract",
            "topic": "output_contract",
            "detail": "这些合约字段没有对应的计算结果，保持为空：" + ", ".join(missing),
        })


def _review(result):
    lines = [
        "# 审查记录",
        "",
        "- case_id: %s" % result.get("case_id"),
        "- status: %s" % result.get("status"),
        "- mode: %s" % result.get("mode"),
        "",
        result.get("example_banner") or "",
        "",
        "## 结论",
        "",
        str(result.get("summary") or ""),
        "",
        "## 还不能当成事实的项",
        "",
    ]
    for item in result.get("confirmations") or []:
        lines.append("- %s：%s" % (item.get("item"), item.get("why")))
    if not result.get("confirmations"):
        lines.append("- 无")
    lines.extend(["", "## 不确定项", ""])
    for item in result.get("uncertainties") or []:
        lines.append("- %s" % item.get("detail"))
    if not result.get("uncertainties"):
        lines.append("- 无")
    lines.extend(["", "## 计算留痕", ""])
    for item in result.get("change_log") or []:
        lines.append("- %s（%s）" % (item.get("decision"), item.get("evidence")))
    lines.append("")
    return "\n".join(lines)
