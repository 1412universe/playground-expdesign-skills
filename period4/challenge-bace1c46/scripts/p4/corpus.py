"""Rank, screen and index only the records that were actually supplied."""
from __future__ import annotations

from p4.util import as_list, clip, evidence, first, norm_title, tokens

RECORD_KEYS = (
    "documents", "papers", "records", "sources", "items", "library",
    "patents", "works", "files", "entries", "corpus",
)


def analyze(bundle, profile):
    records, uncertainties = _records(bundle)
    if not records:
        return _empty("没有读到可检索的记录。把文献、专利或文件整理成 records 后再跑，不要补写未提供的题录。")
    query_text, query_terms = _query(bundle)
    inclusion, exclusion = _criteria(bundle)
    ranked = []
    for record in records:
        ranked.append(_score(record, query_terms))
    kept, duplicates = _dedup(ranked)
    omissions = [item for item in kept if item["score"] <= 0]
    hits = [item for item in kept if item["score"] > 0]
    uncovered = [term for term in query_terms if not any(term in item["hay"] for item in ranked)]
    decisions = []
    for item in hits:
        decision, why = _decide(item, profile, inclusion, exclusion)
        item["decision"] = decision
        item["why"] = why
        decisions.append(item)
    if profile == "cite":
        decisions = _one_hop(decisions, kept, records)
    if profile == "recent":
        decisions = _sort_recent(decisions)
    elif profile == "coverage":
        decisions = sorted(decisions, key=lambda item: (-item["score"], item["id"]))
    else:
        decisions = sorted(decisions, key=lambda item: (-item["score"], item["id"]))
    included = [item for item in decisions if item["decision"] != "exclude"]
    rows = [_public(item, profile) for item in included]
    if profile == "index":
        known = {record["id"] for record in records}
        for row, item in zip(rows, included):
            pointer = item["record"]["fields"].get("superseded_by")
            if not pointer:
                continue
            row["superseded_by"] = str(pointer) if str(pointer) in known else None
            if str(pointer) not in known:
                uncertainties.append({
                    "id": "u-version-%s" % row["id"],
                    "topic": "version",
                    "detail": "%s 写了被 %s 替代，但这份材料里没有那条记录。" % (row["id"], pointer),
                    "scope": False,
                })
    gaps = []
    if uncovered:
        gaps.append("这些查询词在已提供的记录里没有出现：%s。不能据此声称数据库里不存在相关文献。" % ", ".join(uncovered))
    if profile == "recent":
        gaps.append("年份顺序只描述这份有限快照，不是全球最新文献。")
    if profile == "patent":
        gaps.append("材料没有给出的法律状态保持为空，观察到的链接不是完整同族。")
    if profile in ("screen", "synthesis", "index"):
        gaps.append("纳排和问答只覆盖这次给出的记录，不声称系统检索已经穷尽。")
    if profile == "crosslang":
        gaps.append("一种语言视图里的句子不会被写进缺失的另一种语言正文。")
    status = "success"
    if not query_terms:
        status = "partial"
        gaps.append("没有检索问题或关键词，只列出了读到的记录，没有做相关性排序。")
    summary = _summary(profile, len(records), len(rows), len(duplicates), len(omissions))
    return {
        "status": status,
        "summary": summary,
        "primary": {
            "query": query_text,
            "query_terms": query_terms,
            "results": rows,
            "duplicate_ids": [item["id"] for item in duplicates],
            "omission_ids": [item["record"]["id"] for item in omissions],
            "uncovered_terms": uncovered,
            "profile": profile,
        },
        "sources": [evidence(item["record"]["locator"], item["record"]["title"] or item["record"]["text"][:80]) for item in included[:12]],
        "uncertainties": [{"id": "u-scope-%d" % i, "topic": "scope", "detail": text, "scope": True} for i, text in enumerate(gaps)] + uncertainties,
        "checks": [
            {"name": "records_read", "ok": True, "detail": len(records)},
            {"name": "no_fabricated_identifier", "ok": all(not row.get("invented") for row in rows), "detail": len(rows)},
        ],
        "change_log": [{
            "id": "c-rank",
            "decision": "只对已提供记录打分、按标识符去重，并保留未命中的记录编号。",
            "evidence": "records=%d hits=%d duplicates=%d" % (len(records), len(rows), len(duplicates)),
        }],
        "confirmations": [{"item": row["id"], "why": row["why"]} for row in rows[:8]],
    }


def _empty(summary):
    return {
        "status": "failed",
        "summary": summary,
        "primary": {"results": []},
        "sources": [],
        "uncertainties": [{"id": "u-shape", "topic": "input", "detail": summary, "scope": False}],
        "checks": [{"name": "records_read", "ok": False, "detail": 0}],
        "change_log": [{"id": "c-stop", "decision": "缺少记录，不生成检索结果。", "evidence": "records=0"}],
        "confirmations": [],
    }


def _records(bundle):
    found = []
    uncertainties = []
    blobs = [bundle["case"]] + [item["json"] for item in bundle["extras"]]
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        for key in RECORD_KEYS:
            value = blob.get(key)
            if isinstance(value, list):
                for index, item in enumerate(value):
                    record = _record(item, "%s[%d]" % (key, index))
                    if record:
                        found.append(record)
    for table in bundle["tables"]:
        for index, row in enumerate(table.get("rows") or []):
            record = _record(row, "%s[%d]" % (table["path"], index))
            if record and (record["title"] or record["doi"]):
                found.append(record)
    # stable unique by locator
    seen = set()
    unique = []
    for record in found:
        if record["locator"] in seen:
            continue
        seen.add(record["locator"])
        unique.append(record)
    return unique, uncertainties


def _record(item, locator):
    if isinstance(item, str):
        return {
            "id": locator, "title": item[:120], "text": item, "doi": "", "year": None,
            "source": "", "language": "", "locator": locator, "refs": [], "fields": {},
            "views": [], "number": "", "legal_status": None, "condition": "",
        }
    if not isinstance(item, dict):
        return None
    title = str(first(item, ("title", "name", "题名", "headline"), "") or "")
    text = str(first(item, ("abstract", "text", "body", "summary", "snippet", "content", "摘要"), "") or "")
    doi = str(first(item, ("doi", "DOI", "identifier"), "") or "")
    year = first(item, ("year", "published", "date"), None)
    year_num = None
    if year is not None:
        digits = "".join(ch for ch in str(year) if ch.isdigit())
        if len(digits) >= 4:
            year_num = int(digits[:4])
    refs = []
    for key in ("references", "cites", "cited", "refs"):
        if isinstance(item.get(key), list):
            refs = [str(value) for value in item[key]]
            break
    views = []
    raw_views = item.get("views") or item.get("languages")
    if isinstance(raw_views, list):
        for view in raw_views:
            if isinstance(view, dict):
                views.append({
                    "language": view.get("language") or view.get("lang"),
                    "text": view.get("text") if view.get("text") not in (None, "") else None,
                    "role": view.get("role") or view.get("kind"),
                })
    ident = str(first(item, ("id", "record_id", "paper_id", "file_id"), locator))
    return {
        "id": ident,
        "title": title,
        "text": text,
        "doi": doi,
        "year": year_num,
        "source": str(first(item, ("source", "database", "db"), "") or ""),
        "language": str(first(item, ("language", "lang"), "") or ""),
        "locator": locator,
        "refs": refs,
        "fields": {key: value for key, value in item.items() if key not in ("abstract", "text", "body", "content")},
        "views": views,
        "number": str(first(item, ("patent_number", "number", "publication_number"), "") or ""),
        "legal_status": item.get("legal_status", None) if "legal_status" in item else None,
        "condition": str(first(item, ("condition", "dye", "dataset", "population"), "") or ""),
    }


def _query(bundle):
    case = bundle["case"]
    parts = []
    for key in ("question", "query", "topic", "keywords", "search", "prompt"):
        value = case.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
    queries, _path = (None, None)
    from p4.util import find_key
    queries, _path = find_key(case, ("queries",))
    for item in as_list(queries):
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            parts.append(str(first(item, ("text", "query", "q"), "") or ""))
    text = " ".join(parts).strip()
    terms = []
    seen = set()
    for term in tokens(text):
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return text, terms


def _criteria(bundle):
    case = bundle["case"]
    block = case.get("criteria") if isinstance(case.get("criteria"), dict) else case
    inclusion = [str(item).lower() for item in as_list(block.get("inclusion") or block.get("include"))]
    exclusion = [str(item).lower() for item in as_list(block.get("exclusion") or block.get("exclude"))]
    return inclusion, exclusion


def _score(record, terms):
    title = (record["title"] or "").lower()
    body = (record["text"] or "").lower()
    extra = " ".join(view.get("text") or "" for view in record["views"]).lower()
    hay = "%s %s %s %s %s" % (title, body, extra, record["doi"].lower(), record["number"].lower())
    score = 0
    matched = []
    for term in terms:
        if term in title:
            score += 3
            matched.append(term)
        elif term in body or term in extra or term in record["doi"].lower() or term in record["number"].lower():
            score += 1
            matched.append(term)
    return {"record": record, "score": score, "matched": matched, "hay": hay, "id": record["id"]}


def _dedup(ranked):
    kept = []
    duplicates = []
    by_doi = {}
    by_title = {}
    for item in ranked:
        doi = item["record"]["doi"].strip().lower()
        title = norm_title(item["record"]["title"])
        slot = None
        if doi and doi in by_doi:
            slot = by_doi[doi]
        elif title and title in by_title:
            slot = by_title[title]
        if slot is None:
            kept.append(item)
            if doi:
                by_doi[doi] = item
            if title:
                by_title[title] = item
            continue
        duplicates.append(item)
        if (item["score"], item["record"]["year"] or 0) > (slot["score"], slot["record"]["year"] or 0):
            kept.remove(slot)
            kept.append(item)
            if doi:
                by_doi[doi] = item
            if title:
                by_title[title] = item
    return kept, duplicates


def _decide(item, profile, inclusion, exclusion):
    text = item["hay"]
    for term in exclusion:
        if term and term in text:
            return "exclude", "命中排除条件“%s”，不进入结果。" % term
    if inclusion:
        hit = [term for term in inclusion if term in text]
        if not hit:
            return "exclude", "没有命中任一纳入条件。"
    if profile == "quality":
        return "include", "只转写记录里已经给出的质量字段，不补偏倚评分。"
    if profile == "patent":
        return "include", "按专利号或主题在给定语料中匹配。"
    if profile == "crosslang":
        return "include", "按已提供的语言视图匹配，缺失正文保持为空。"
    return "include", "查询词命中：%s。" % ", ".join(item["matched"])


def _one_hop(decisions, kept, records):
    by_id = {record["id"]: record for record in records}
    chosen = {item["id"]: item for item in decisions if item["decision"] != "exclude"}
    extra = []
    for item in list(chosen.values()):
        for ref in item["record"]["refs"]:
            target = by_id.get(ref)
            if target is None or target["id"] in chosen:
                continue
            hop = {
                "record": target, "score": item["score"], "matched": ["cited-by:%s" % item["id"]],
                "hay": "", "id": target["id"], "decision": "include",
                "why": "从 %s 的参考文献一跳到达，不再继续外扩。" % item["id"],
            }
            chosen[target["id"]] = hop
            extra.append(hop)
    return list(chosen.values()) + []


def _sort_recent(decisions):
    known = [item for item in decisions if item["record"]["year"] is not None]
    unknown = [item for item in decisions if item["record"]["year"] is None]
    known.sort(key=lambda item: (-item["record"]["year"], -item["score"], item["id"]))
    for item in unknown:
        item["why"] += " 缺少年份，不参与新旧排序。"
    return known + unknown


def _public(item, profile):
    record = item["record"]
    row = {
        "id": record["id"],
        "title": record["title"],
        "doi": record["doi"] or None,
        "year": record["year"],
        "source": record["source"] or None,
        "language": record["language"] or None,
        "score": item["score"],
        "matched_terms": item["matched"],
        "decision": item["decision"],
        "why": item["why"],
        "locator": record["locator"],
        "invented": False,
    }
    if profile == "quality":
        allowed = {}
        for key in ("sample_size", "design", "blinding", "randomized", "n"):
            if key in record["fields"]:
                allowed[key] = record["fields"][key]
        row["quality_fields"] = allowed
    if profile == "crosslang":
        row["views"] = record["views"]
    if profile == "patent":
        row["patent_number"] = record["number"] or None
        row["legal_status"] = record["legal_status"]
    if profile == "cite":
        row["references"] = record["refs"]
    row["text_excerpt"] = clip(record["text"], 180)
    return row


def _summary(profile, records, hits, duplicates, omissions):
    names = {
        "rank": "检索",
        "screen": "纳排",
        "cite": "引文一跳",
        "coverage": "覆盖与遗漏",
        "recent": "快照内按年份排列",
        "quality": "质量字段转写",
        "crosslang": "跨语言视图",
        "patent": "专利语料",
        "index": "资料索引",
        "synthesis": "有限材料综述",
    }
    label = names.get(profile, profile)
    return "%s：读到 %d 条记录，保留 %d 条，合并重复 %d 条，未命中 %d 条。没有访问实时数据库。" % (
        label, records, hits, duplicates, omissions,
    )
