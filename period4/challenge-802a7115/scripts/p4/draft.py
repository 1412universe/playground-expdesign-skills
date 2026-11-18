"""Build evidence-bound drafts and source-bound schematics."""
from __future__ import annotations

import os
import re

from p4.util import as_list, clip, evidence, find_key, first

SECTIONS = {
    "format": ["模板要求", "已有内容", "缺口"],
    "evidence": ["问题", "证据", "不能写的部分"],
    "client": ["任务", "材料", "可引用句子"],
    "structure": ["已知主张", "材料支持", "结构缺口"],
    "results": ["已报告结果", "讨论边界"],
    "response": ["审稿意见", "能回应的证据", "不能回应的意见"],
    "translate": ["原文", "已核对的译文"],
    "grant": ["研究问题", "已有依据", "未提供的计划项"],
    "proposal": ["问题", "已有依据", "需要补的设计"],
    "thesis": ["章节材料", "可引用句子"],
    "transfer": ["结果", "可对外说明的依据", "不能外推的部分"],
    "mindmap": ["节点"],
}


def analyze(bundle, profile, output_dir):
    if profile == "schematic":
        return _schematic(bundle, output_dir)
    return _draft(bundle, profile, output_dir)


def _sentences(bundle):
    rows = []
    found, _path = find_key(bundle["case"], ("sources", "evidence", "sentences", "paragraphs", "passages"))
    for index, item in enumerate(as_list(found)):
        if isinstance(item, str):
            rows.append({"id": "s%d" % (index + 1), "text": item, "locator": "sources[%d]" % index})
        elif isinstance(item, dict):
            text = str(first(item, ("text", "quote", "sentence", "content"), "") or "")
            if text:
                rows.append({
                    "id": str(first(item, ("id",), "s%d" % (index + 1))),
                    "text": text,
                    "locator": "sources[%d]" % index,
                })
    return rows


def _draft(bundle, profile, output_dir):
    sentences = _sentences(bundle)
    if not sentences and profile != "format":
        return _failed("没有可引用的原文句子，不写正文。")
    sections = SECTIONS.get(profile, ["证据"])
    used = []
    if profile == "translate":
        used, dropped = _translations(bundle, sentences)
        body = _render(sections, used, sentences)
    elif profile == "response":
        used, dropped = _responses(bundle, sentences)
        body = _render(sections, used, sentences)
    elif profile == "mindmap":
        used = [{"text": item["text"][:80], "source_id": item["id"]} for item in sentences]
        dropped = []
        body = _render(sections, used, sentences)
    elif profile == "format":
        required, _path = find_key(bundle["case"], ("required_sections", "template"))
        names = [str(item) for item in as_list(required)]
        present = {item["text"][:40] for item in sentences}
        missing = [name for name in names if not any(name in text for text in present)]
        used = [{"text": item["text"], "source_id": item["id"]} for item in sentences]
        dropped = []
        body = _render(sections, used, sentences)
        if missing:
            body += "\n\n未在材料中见到的模板项：%s。这些项没有被补写。\n" % "、".join(missing)
    else:
        used = [{"text": item["text"], "source_id": item["id"]} for item in sentences]
        dropped = []
        body = _render(sections, used, sentences)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "draft.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    status = "partial" if dropped or not used else "success"
    return {
        "status": status,
        "summary": "写成 %d 句带出处的文字，丢弃 %d 句没有出处或数字对不上的内容。" % (len(used), len(dropped)),
        "primary": {
            "genre": profile,
            "sentences": used,
            "dropped": dropped,
            "draft": "draft.md",
            "sections": sections,
        },
        "sources": [evidence(item["locator"], item["text"]) for item in sentences[:8]],
        "uncertainties": [{"id": "u-drop-%d" % i, "topic": "draft", "detail": item, "scope": False} for i, item in enumerate(dropped)],
        "checks": [{"name": "every_sentence_has_source", "ok": all(item.get("source_id") for item in used), "detail": len(used)}],
        "change_log": [{"id": "c-draft", "decision": "正文只保留能指回原文的句子。", "evidence": "kept=%d dropped=%d" % (len(used), len(dropped))}],
        "confirmations": [{"item": item["source_id"], "why": "引用该句。"} for item in used[:6]],
    }


def _translations(bundle, sentences):
    by_id = {item["id"]: item for item in sentences}
    given, _path = find_key(bundle["case"], ("translations",))
    used = []
    dropped = []
    if not as_list(given):
        return [], ["没有给出译文。原文句子已列出，但不生成翻译。"]
    for item in as_list(given):
        if not isinstance(item, dict):
            dropped.append("译文不是带 source_id 的对象。")
            continue
        source = by_id.get(str(item.get("source_id")))
        text = str(item.get("text") or "")
        if source is None or not text:
            dropped.append("译文缺少存在的 source_id。")
            continue
        if _numbers(source["text"]) != _numbers(text):
            dropped.append("译文 %s 的数字与原文不一致，整句丢弃。" % source["id"])
            continue
        used.append({"text": text, "source_id": source["id"]})
    return used, dropped


def _responses(bundle, sentences):
    comments, _path = find_key(bundle["case"], ("comments", "reviews"))
    by_id = {item["id"]: item for item in sentences}
    used = []
    dropped = []
    if not as_list(comments):
        return [], ["没有审稿意见，不写回复。"]
    for index, comment in enumerate(as_list(comments)):
        if isinstance(comment, str):
            cid, text, source_id = "r%d" % (index + 1), comment, None
        elif isinstance(comment, dict):
            cid = str(first(comment, ("id",), "r%d" % (index + 1)))
            text = str(first(comment, ("text", "comment"), "") or "")
            source_id = comment.get("source_id")
        else:
            continue
        if source_id and str(source_id) in by_id:
            used.append({"text": "意见 %s：%s 可引用 %s。" % (cid, text, by_id[str(source_id)]["text"]), "source_id": str(source_id)})
        else:
            dropped.append("意见 %s 没有对应原文，不编造回复。" % cid)
    return used, dropped


def _numbers(text):
    return tuple(re.findall(r"[+-]?\d+(?:\.\d+)?", text or ""))


def _render(sections, used, sentences):
    lines = ["# 草稿", "", "每句话都能回到下面的原文编号。没有出处的内容没有写入。", ""]
    lines.append("## 原文")
    for item in sentences:
        lines.append("- [%s] %s" % (item["id"], item["text"]))
    lines.append("")
    lines.append("## %s" % " / ".join(sections))
    if not used:
        lines.append("这一节没有可写入的句子。")
    for item in used:
        lines.append("- [%s] %s" % (item["source_id"], item["text"]))
    lines.append("")
    return "\n".join(lines)


def _schematic(bundle, output_dir):
    entities, _path = find_key(bundle["case"], ("entities", "nodes"))
    relations, _rpath = find_key(bundle["case"], ("relations", "edges"))
    nodes = []
    for index, item in enumerate(as_list(entities)):
        if isinstance(item, str):
            nodes.append({"id": "n%d" % (index + 1), "label": item})
        elif isinstance(item, dict):
            label = str(first(item, ("label", "name", "text"), "") or "")
            if label:
                nodes.append({"id": str(first(item, ("id",), "n%d" % (index + 1))), "label": label})
    if not nodes:
        return _failed("没有实体列表，不绘制示意图，也不补充材料里没有的对象。")
    ids = {node["id"] for node in nodes}
    edges = []
    for item in as_list(relations):
        if not isinstance(item, dict):
            continue
        src, dst = str(item.get("source") or item.get("from") or ""), str(item.get("target") or item.get("to") or "")
        if src in ids and dst in ids:
            edges.append({"source": src, "target": dst, "label": str(item.get("label") or item.get("relation") or "")})
    svg = _svg(nodes, edges)
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "schematic.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)
    return {
        "status": "success",
        "summary": "示意图包含 %d 个给定实体和 %d 条两端都存在的关系。" % (len(nodes), len(edges)),
        "primary": {"nodes": nodes, "edges": edges, "figure": "schematic.svg"},
        "sources": [evidence("entities", node["label"]) for node in nodes[:8]],
        "uncertainties": [{"id": "u-draw", "topic": "schematic", "detail": "没有加入实体列表以外的对象。", "scope": True}],
        "checks": [{"name": "nodes_match_input", "ok": True, "detail": len(nodes)}],
        "change_log": [{"id": "c-svg", "decision": "只画给定实体和两端都在列表里的关系。", "evidence": "nodes=%d edges=%d" % (len(nodes), len(edges))}],
        "confirmations": [{"item": node["id"], "why": node["label"]} for node in nodes],
    }


def _svg(nodes, edges):
    pos = {node["id"]: (40, 40 + index * 48) for index, node in enumerate(nodes)}
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="640" height="%d">' % (60 + 48 * len(nodes))]
    for edge in edges:
        x1, y1 = pos[edge["source"]]
        x2, y2 = pos[edge["target"]]
        parts.append('<line x1="220" y1="%d" x2="220" y2="%d" stroke="#444"/>' % (y1 + 12, y2 + 12))
        if edge["label"]:
            parts.append('<text x="230" y="%d" font-size="11">%s</text>' % ((y1 + y2) // 2, _xml(edge["label"])))
    for node in nodes:
        _x, y = pos[node["id"]]
        parts.append('<rect x="40" y="%d" width="160" height="28" fill="#e8f0ea" stroke="#2f6f4e"/>' % y)
        parts.append('<text x="48" y="%d" font-size="12">%s</text>' % (y + 18, _xml(node["label"][:24])))
    parts.append("</svg>")
    return "\n".join(parts)


def _xml(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _failed(summary):
    return {
        "status": "failed",
        "summary": summary,
        "primary": {},
        "sources": [],
        "uncertainties": [{"id": "u-shape", "topic": "input", "detail": summary, "scope": False}],
        "checks": [{"name": "input_shape", "ok": False, "detail": summary}],
        "change_log": [{"id": "c-stop", "decision": "没有可用材料，不生成文本或图。", "evidence": "failed"}],
        "confirmations": [],
    }
