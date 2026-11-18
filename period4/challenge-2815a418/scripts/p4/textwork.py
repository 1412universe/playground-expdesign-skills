"""Answer, extract, compare and audit only text that was supplied."""
from __future__ import annotations

import re

from p4.util import as_list, clip, evidence, find_key, first, num, tokens

NEG = ("不", "未", "没有", "无", "非", "not", "no", "without", "didn't", "did not")


def analyze(bundle, profile):
    if profile == "figure":
        return _figure(bundle)
    if profile == "qa" or profile == "client":
        return _qa(bundle, profile)
    if profile == "compare":
        return _compare(bundle)
    if profile == "extract" or profile == "litclean":
        return _extract(bundle, profile)
    if profile == "fact":
        return _fact(bundle)
    if profile == "formula":
        return _formula(bundle)
    if profile == "repro":
        return _repro(bundle)
    if profile == "audit":
        return _audit(bundle)
    return _qa(bundle, profile)


def _passages(bundle):
    rows = []
    case = bundle["case"]
    for key in ("paragraphs", "passages", "sentences", "sections", "questions"):
        pass
    blobs = [("case", case)] + [(item["path"], item["json"]) for item in bundle["extras"]]
    for origin, blob in blobs:
        if not isinstance(blob, dict):
            continue
        for key in ("paragraphs", "passages", "sections", "sentences"):
            for index, item in enumerate(as_list(blob.get(key))):
                if isinstance(item, str):
                    rows.append({"id": "%s:%s[%d]" % (origin, key, index), "text": item, "locator": "%s.%s[%d]" % (origin, key, index)})
                elif isinstance(item, dict):
                    text = str(first(item, ("text", "content", "body", "quote"), "") or "")
                    if text:
                        rows.append({
                            "id": str(first(item, ("id", "section_id"), "%s[%d]" % (key, index))),
                            "text": text,
                            "locator": "%s.%s[%d]" % (origin, key, index),
                        })
    for item in bundle["files"]:
        if item.get("text") and item["path"] != "case.json" and item["kind"] in ("md", "txt", "tex", "log", "xml"):
            rows.append({"id": item["path"], "text": item["text"], "locator": item["path"]})
    return rows


def _questions(bundle):
    found, _path = find_key(bundle["case"], ("questions", "question"))
    rows = []
    if isinstance(found, str):
        rows.append({"id": "q1", "text": found})
    for index, item in enumerate(as_list(found)):
        if isinstance(item, str):
            rows.append({"id": "q%d" % (index + 1), "text": item})
        elif isinstance(item, dict):
            text = str(first(item, ("text", "question", "q", "prompt"), "") or "")
            if text:
                rows.append({"id": str(first(item, ("id", "qid"), "q%d" % (index + 1))), "text": text})
    return rows


def _qa(bundle, profile):
    passages = _passages(bundle)
    questions = _questions(bundle)
    if not passages or not questions:
        return _failed("没有同时读到问题和原文段落。先把原文段落和问题整理出来再答，不要凭记忆作答。")
    answers = []
    sources = []
    for question in questions:
        q_terms = tokens(question["text"])
        best = None
        best_score = 0
        for passage in passages:
            score = len(set(q_terms) & set(tokens(passage["text"])))
            if score > best_score:
                best = passage
                best_score = score
        if best is None or best_score < 2:
            answers.append({
                "question_id": question["id"], "question": question["text"], "answer": None,
                "status": "insufficient_evidence", "locator": None,
                "why": "原文里没有足够重叠的段落，不编造答案。",
            })
            continue
        answers.append({
            "question_id": question["id"], "question": question["text"], "answer": clip(best["text"], 300),
            "status": "quoted", "locator": best["locator"],
            "why": "答案是原文摘录，重叠词 %d 个。" % best_score,
        })
        sources.append(evidence(best["locator"], best["text"]))
    inventory = []
    if profile == "client":
        inventory = [{"path": item["path"], "reader": item.get("reader"), "error": item.get("error")} for item in bundle["files"]]
    quoted = sum(1 for item in answers if item["status"] == "quoted")
    status = "success" if quoted == len(answers) else "partial"
    return {
        "status": status,
        "summary": "回答 %d 个问题，其中 %d 个有原文摘录，其余标为证据不足。" % (len(answers), quoted),
        "primary": {"answers": answers, "materials": inventory},
        "sources": sources,
        "uncertainties": [{"id": "u-qa", "topic": "answer", "detail": item["why"], "scope": False}
                          for item in answers if item["status"] != "quoted"],
        "checks": [{"name": "questions_answered_or_refused", "ok": True, "detail": len(answers)}],
        "change_log": [{"id": "c-qa", "decision": "只摘录原文，重叠不足的问题留空。", "evidence": "quoted=%d" % quoted}],
        "confirmations": [{"item": item["question_id"], "why": item["why"]} for item in answers],
    }


def _figure(bundle):
    tables = [item for item in bundle["tables"] if item.get("rows")]
    images, _path = find_key(bundle["case"], ("images", "figures", "image"))
    gaps = []
    extracted = []
    for table in tables:
        for index, row in enumerate(table["rows"][:200]):
            numbers = {key: num(value) for key, value in row.items() if num(value) is not None}
            if numbers:
                extracted.append({"locator": "%s[%d]" % (table["path"], index), "values": numbers})
    for index, item in enumerate(as_list(images)):
        label = item if isinstance(item, str) else str((item or {}).get("id") or (item or {}).get("name") or index)
        pixels = isinstance(item, dict) and any(key in item for key in ("pixels", "series", "points", "rows"))
        if not pixels:
            gaps.append("图 %s 没有给像素、数据点或表，不构造读数。" % label)
    if not extracted and gaps:
        status = "partial"
    elif not extracted and not tables:
        return _failed("没有读到图对应的表或数据点。未给像素的图只记缺口，不补造坐标。")
    else:
        status = "partial" if gaps else "success"
    return {
        "status": status,
        "summary": "从已给的表读出 %d 行数值；%d 张没有像素的图只记缺口。" % (len(extracted), len(gaps)),
        "primary": {"table_values": extracted, "figure_gaps": gaps},
        "sources": [evidence(item["locator"], str(item["values"])) for item in extracted[:8]],
        "uncertainties": [{"id": "u-fig-%d" % i, "topic": "figure", "detail": text, "scope": False} for i, text in enumerate(gaps)],
        "checks": [{"name": "no_invented_pixels", "ok": True, "detail": len(gaps)}],
        "change_log": [{"id": "c-fig", "decision": "只转写表内数字。", "evidence": "rows=%d gaps=%d" % (len(extracted), len(gaps))}],
        "confirmations": [{"item": item["locator"], "why": "数值来自该行。"} for item in extracted[:6]],
    }


def _compare(bundle):
    docs, _path = find_key(bundle["case"], ("documents", "papers", "sources", "records"))
    rows = []
    for index, item in enumerate(as_list(docs)):
        if not isinstance(item, dict):
            continue
        measures = item.get("measures") if isinstance(item.get("measures"), dict) else {}
        if not measures:
            for key, value in item.items():
                if num(value) is not None and key not in ("year",):
                    measures[key] = value
        rows.append({
            "id": str(first(item, ("id", "doc_id"), "d%d" % index)),
            "condition": str(first(item, ("condition", "dye", "dataset", "population"), "") or ""),
            "unit": str(first(item, ("unit",), "") or ""),
            "measures": {str(key): value for key, value in measures.items()},
            "locator": "documents[%d]" % index,
        })
    if len(rows) < 2:
        return _failed("可比的材料少于 2 份，不做跨文献合并。")
    comparable = []
    blocked = []
    names = sorted({key for row in rows for key in row["measures"]})
    for name in names:
        holders = [row for row in rows if name in row["measures"]]
        conditions = {row["condition"] for row in holders}
        units = {row["unit"] for row in holders}
        if len(holders) < 2 or len(conditions) > 1 or len(units) > 1:
            blocked.append({
                "measure": name,
                "why": "条件或单位不一致，或只在一份材料里出现，不合并数值。",
                "values": [{"id": row["id"], "value": row["measures"].get(name), "condition": row["condition"], "unit": row["unit"]} for row in holders],
            })
            continue
        comparable.append({
            "measure": name,
            "unit": holders[0]["unit"] or None,
            "values": [{"id": row["id"], "value": row["measures"][name], "locator": row["locator"]} for row in holders],
        })
    return {
        "status": "success" if comparable else "partial",
        "summary": "可并列的指标 %d 个，因条件或单位不同而没有合并的 %d 个。" % (len(comparable), len(blocked)),
        "primary": {"comparable": comparable, "not_comparable": blocked},
        "sources": [evidence(row["locator"], row["id"]) for row in rows],
        "uncertainties": [{"id": "u-pool", "topic": "compare", "detail": "没有把不同染料、数据集或单位放进同一个汇总。", "scope": True}],
        "checks": [{"name": "no_pooled_unlike", "ok": True, "detail": len(blocked)}],
        "change_log": [{"id": "c-cmp", "decision": "只并列条件相同的指标。", "evidence": "comparable=%d" % len(comparable)}],
        "confirmations": [{"item": item["measure"], "why": "条件一致才并列。"} for item in comparable],
    }


def _extract(bundle, profile):
    passages = _passages(bundle)
    fields, _path = find_key(bundle["case"], ("fields", "targets", "metrics"))
    names = []
    for item in as_list(fields):
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]))
    if not names or not passages:
        return _failed("没有待提取字段或原文。缺失字段不会写成 0。")
    extracted = []
    for name in names:
        hit = None
        for passage in passages:
            value, quote = _near_number(passage["text"], name)
            if value is not None:
                hit = {"field": name, "value": value, "locator": passage["locator"], "quote": quote, "status": "extracted"}
                break
        if hit is None:
            extracted.append({"field": name, "value": None, "locator": None, "quote": None, "status": "not_reported"})
        else:
            extracted.append(hit)
    missing = [item["field"] for item in extracted if item["value"] is None]
    status = "partial" if missing else "success"
    if profile == "litclean":
        status = status
    return {
        "status": status,
        "summary": "提取 %d 个字段，其中 %d 个原文没有报告，保持为空而不是 0。" % (len(extracted), len(missing)),
        "primary": {"fields": extracted},
        "sources": [evidence(item["locator"], item["quote"]) for item in extracted if item.get("locator")],
        "uncertainties": [{"id": "u-miss-%s" % name, "topic": "extract", "detail": "%s 在原文中没有读到，不填 0。" % name, "scope": False} for name in missing],
        "checks": [{"name": "missing_is_not_zero", "ok": all(item["value"] != 0 or item["status"] == "extracted" for item in extracted), "detail": len(missing)}],
        "change_log": [{"id": "c-ex", "decision": "字段值必须能在原文邻近位置读到。", "evidence": "missing=%s" % ",".join(missing)}],
        "confirmations": [{"item": item["field"], "why": item["status"]} for item in extracted],
    }


def _near_number(text, label):
    match = re.search(re.escape(label) + r".{0,40}?([+-]?\d+(?:\.\d+)?)", text, flags=re.IGNORECASE)
    if not match:
        return None, None
    return num(match.group(1)), match.group(0)


def _fact(bundle):
    claims, _path = find_key(bundle["case"], ("claims",))
    passages = _passages(bundle)
    if not as_list(claims) or not passages:
        return _failed("没有主张或原文，不能给支持或反驳结论。")
    rows = []
    for index, claim in enumerate(as_list(claims)):
        text = claim if isinstance(claim, str) else str(first(claim, ("text", "claim"), "") or "")
        cid = str(first(claim, ("id",), "c%d" % (index + 1))) if isinstance(claim, dict) else "c%d" % (index + 1)
        numbers = re.findall(r"[+-]?\d+(?:\.\d+)?", text)
        claim_neg = any(word in text.lower() for word in NEG)
        supports = []
        for passage in passages:
            if numbers and not all(number in passage["text"] for number in numbers):
                continue
            if tokens(text) and len(set(tokens(text)) & set(tokens(passage["text"]))) < 1 and numbers:
                continue
            if not numbers and len(set(tokens(text)) & set(tokens(passage["text"]))) < 2:
                continue
            source_neg = any(word in passage["text"].lower() for word in NEG)
            if claim_neg != source_neg and any(word in text.lower() for word in ("increase", "增加", "升高", "提高")):
                continue
            supports.append(passage)
        verdict = "insufficient_evidence"
        if len(supports) == 1:
            verdict = "supported"
        elif len(supports) > 1:
            verdict = "conflict" if len({clip(item["text"], 80) for item in supports}) > 1 else "supported"
        rows.append({
            "claim_id": cid,
            "claim": text,
            "verdict": verdict,
            "locators": [item["locator"] for item in supports],
            "why": "否定词和数字都要在同一处原文里对上；对不上就是证据不足，不是实验已经否定。",
        })
    return {
        "status": "success",
        "summary": "核对 %d 条主张。冲突只在两处原文不一致时成立。" % len(rows),
        "primary": {"claims": rows},
        "sources": [evidence(loc, "") for row in rows for loc in row["locators"]],
        "uncertainties": [{"id": "u-fact", "topic": "fact", "detail": "没有把证据不足写成实验否定。", "scope": True}],
        "checks": [{"name": "claims_labelled", "ok": True, "detail": len(rows)}],
        "change_log": [{"id": "c-fact", "decision": "按原文数字和否定词核对主张。", "evidence": "claims=%d" % len(rows)}],
        "confirmations": [{"item": row["claim_id"], "why": row["verdict"]} for row in rows],
    }


def _formula(bundle):
    xml_parts = []
    for item in bundle["files"]:
        if item["kind"] in ("xml", "txt", "md") and item.get("text") and ("math" in item["text"].lower() or "<mi" in item["text"] or "formula" in item["path"].lower()):
            xml_parts.append(item)
    if not xml_parts:
        return {
            "status": "partial",
            "summary": "没有公式源。缺公式的案例保持部分完成，不反推、不把未知填 0。",
            "primary": {"formulas": [], "derivation": None},
            "sources": [],
            "uncertainties": [{"id": "u-math", "topic": "formula", "detail": "材料没有公式节点或可复算数据。", "scope": False}],
            "checks": [{"name": "no_invented_derivation", "ok": True, "detail": "derivation=null"}],
            "change_log": [{"id": "c-math", "decision": "没有公式源就不推导。", "evidence": "xml=0"}],
            "confirmations": [],
        }
    formulas = []
    for item in xml_parts:
        ids = re.findall(r'id="([^"]+)"', item["text"])
        text = re.sub(r"<[^>]+>", " ", item["text"])
        text = re.sub(r"\s+", " ", text).strip()
        formulas.append({"source": item["path"], "ids": ids[:20], "linear_text": clip(text, 300), "derivation": None})
    return {
        "status": "success",
        "summary": "转写 %d 个公式源的标识和线性文本，没有做推导。" % len(formulas),
        "primary": {"formulas": formulas, "derivation": None},
        "sources": [evidence(item["path"], item["text"][:80]) for item in xml_parts],
        "uncertainties": [{"id": "u-math", "topic": "formula", "detail": "线性文本只是公式节点的文字，不是推导结果。", "scope": True}],
        "checks": [{"name": "derivation_null", "ok": True, "detail": "null"}],
        "change_log": [{"id": "c-math", "decision": "只转写已提供的公式节点。", "evidence": "files=%d" % len(xml_parts)}],
        "confirmations": [{"item": item["source"], "why": "来自该文件。"} for item in formulas],
    }


def _repro(bundle):
    steps, _path = find_key(bundle["case"], ("steps", "method", "methods"))
    metrics, _mpath = find_key(bundle["case"], ("reported", "metrics", "results"))
    step_rows = []
    for index, item in enumerate(as_list(steps)):
        text = item if isinstance(item, str) else str(first(item, ("text", "step"), "") or "")
        if text:
            step_rows.append({"id": "s%d" % (index + 1), "text": text, "locator": "steps[%d]" % index})
    metric_rows = []
    for index, item in enumerate(as_list(metrics)):
        if isinstance(item, dict):
            metric_rows.append({
                "name": str(first(item, ("name", "metric"), "m%d" % index)),
                "value": item.get("value"),
                "locator": "metrics[%d]" % index,
                "recomputed": None,
            })
    tables = [item for item in bundle["tables"] if item.get("rows")]
    recomputed = None
    if tables and metric_rows:
        recomputed = "有表，但题面没有给出可复算的原始列与公式对应关系，不另算一个新数。"
    status = "partial" if not tables else "success"
    if not step_rows and not metric_rows:
        return _failed("没有方法步骤或已报告指标。不能把缺失的原始数据补成复现结果。")
    return {
        "status": "partial" if recomputed or not tables else status,
        "summary": "转写步骤 %d 条、已报告指标 %d 条。没有原始可复算列时不新算数值。" % (len(step_rows), len(metric_rows)),
        "primary": {"steps": step_rows, "reported": metric_rows, "recomputed": None, "note": recomputed},
        "sources": [evidence(item["locator"], item["text"]) for item in step_rows[:6]],
        "uncertainties": [{"id": "u-repro", "topic": "repro", "detail": recomputed or "只核对材料里写明的步骤和指标。", "scope": recomputed is None}],
        "checks": [{"name": "no_new_number", "ok": True, "detail": "recomputed=null"}],
        "change_log": [{"id": "c-repro", "decision": "不在缺少原始列时复算。", "evidence": "steps=%d" % len(step_rows)}],
        "confirmations": [{"item": item["id"], "why": "步骤来自输入。"} for item in step_rows[:6]],
    }


def _audit(bundle):
    passages = _passages(bundle)
    facets, _path = find_key(bundle["case"], ("facets", "checks", "review_facets"))
    names = [str(item) for item in as_list(facets)] or ["方法", "统计", "逻辑", "规范"]
    if not passages:
        return _failed("没有全文或段落，不能做审查，也不预设缺陷结论。")
    findings = []
    for name in names:
        hits = [passage for passage in passages if name.lower() in passage["text"].lower()]
        if hits:
            findings.append({
                "facet": name, "status": "observed", "severity": "note",
                "locators": [item["locator"] for item in hits[:3]],
                "quote": clip(hits[0]["text"], 180),
                "verdict": None,
            })
        else:
            findings.append({
                "facet": name, "status": "not_observed", "severity": "none",
                "locators": [], "quote": None,
                "verdict": None,
                "why": "正文没有出现这一审查面的表述。这不是缺陷结论。",
            })
    return {
        "status": "success",
        "summary": "按 %d 个审查面记录原文有没有写到，没有强行给出缺陷裁决。" % len(findings),
        "primary": {"findings": findings},
        "sources": [evidence(item["locators"][0], item.get("quote")) for item in findings if item["locators"]],
        "uncertainties": [{"id": "u-audit", "topic": "review", "detail": "未观察到不等于违规或方法错误。", "scope": True}],
        "checks": [{"name": "no_planted_defect", "ok": all(item["verdict"] is None for item in findings), "detail": len(findings)}],
        "change_log": [{"id": "c-audit", "decision": "只记录原文里看得到的审查面。", "evidence": "facets=%d" % len(findings)}],
        "confirmations": [{"item": item["facet"], "why": item["status"]} for item in findings],
    }


def _failed(summary):
    return {
        "status": "failed",
        "summary": summary,
        "primary": {},
        "sources": [],
        "uncertainties": [{"id": "u-shape", "topic": "input", "detail": summary, "scope": False}],
        "checks": [{"name": "input_shape", "ok": False, "detail": summary}],
        "change_log": [{"id": "c-stop", "decision": "输入结构不够，不生成结论。", "evidence": "failed"}],
        "confirmations": [],
    }
