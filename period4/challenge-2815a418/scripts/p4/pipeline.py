"""Load one case, run the locked mode, and write result.json."""
from __future__ import annotations

import os

from p4 import corpus, draft, tables, textwork
from p4.util import find_key, sane, write_json

FAMILIES = {
    "corpus": corpus.analyze,
    "text": textwork.analyze,
    "table": tables.analyze,
    "draft": draft.analyze,
}


def run(input_dir, output_dir, mode, profile):
    if mode not in FAMILIES:
        raise SystemExit("unknown mode %s" % mode)
    from p4.ingest import load
    bundle = load(input_dir)
    if mode == "corpus":
        body = corpus.analyze(bundle, profile)
    elif mode == "text":
        body = textwork.analyze(bundle, profile)
    elif mode == "table":
        body = tables.analyze(bundle, profile, output_dir)
    else:
        body = draft.analyze(bundle, profile, output_dir)
    result = _envelope(bundle, body, mode, profile)
    os.makedirs(output_dir, exist_ok=True)
    write_json(os.path.join(output_dir, "result.json"), result)
    write_json(os.path.join(output_dir, "checks.json"), {"checks": result["checks"]})
    write_json(os.path.join(output_dir, "sources.json"), {"sources": result["sources"]})
    write_json(os.path.join(output_dir, "change_log.json"), {"change_log": result["change_log"]})
    with open(os.path.join(output_dir, "review.md"), "w", encoding="utf-8") as handle:
        handle.write(_review(result))
    return result


def _envelope(bundle, body, mode, profile):
    sources = [{
        "path": item["path"],
        "sha256": item["sha256"],
        "bytes": item["bytes"],
        "reader": item.get("reader"),
        "error": item.get("error"),
        "truncated": item.get("truncated"),
    } for item in bundle["files"]]
    quote_sources = list(body.get("sources") or [])
    unread = [item["path"] for item in sources if item.get("error")]
    uncertainties = list(body.get("uncertainties") or [])
    for path in unread:
        uncertainties.append({
            "id": "u-unread-%s" % path,
            "topic": "file",
            "detail": "文件 %s 没有被解析，结论没有使用它的内容。" % path,
            "scope": False,
        })
    status = body.get("status") or "partial"
    if status == "success" and any(not item.get("scope") for item in uncertainties):
        status = "partial"
    result = {
        "case_id": bundle["case"].get("case_id") or bundle["case"].get("id"),
        "status": status,
        "mode": mode,
        "profile": profile,
        "summary": body.get("summary"),
        "primary": body.get("primary") or {},
        "confirmations": body.get("confirmations") or [],
        "uncertainties": uncertainties,
        "sources": sources + quote_sources,
        "change_log": list(body.get("change_log") or []),
        "checks": list(body.get("checks") or []),
        "runtime_seconds": None,
    }
    if bundle["case"].get("example_only") is True:
        result["example_banner"] = "示意输出，不是平台正式案例，不能当作正式答案。"
    contract, _path = find_key(bundle["case"], ("output_contract", "contract"))
    result["output_contract_echo"] = contract if isinstance(contract, (dict, list)) else None
    _fill_contract(result, contract)
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
        if name in (result.get("primary") or {}):
            result[name] = result["primary"][name]
        else:
            result[name] = None
            missing.append(name)
    if missing:
        result["uncertainties"].append({
            "id": "u-contract",
            "topic": "output_contract",
            "detail": "这些合约字段没有对应的计算结果，保持为空：" + ", ".join(missing),
            "scope": False,
        })
        if result["status"] == "success":
            result["status"] = "partial"


def _review(result):
    lines = [
        "# 记录",
        "",
        "- case_id: %s" % result.get("case_id"),
        "- status: %s" % result.get("status"),
        "- mode: %s/%s" % (result.get("mode"), result.get("profile")),
        "",
        result.get("example_banner") or "",
        "",
        "## 结论",
        "",
        str(result.get("summary") or ""),
        "",
        "## 不确定项",
        "",
    ]
    for item in result.get("uncertainties") or []:
        lines.append("- %s" % item.get("detail"))
    if not result.get("uncertainties"):
        lines.append("- 无")
    lines.extend(["", "## 留痕", ""])
    for item in result.get("change_log") or []:
        lines.append("- %s（%s）" % (item.get("decision"), item.get("evidence")))
    lines.append("")
    return "\n".join(lines)
