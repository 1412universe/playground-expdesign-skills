#!/usr/bin/env python3
"""Synthetic cases for every locked profile. Not the organizer's official cases."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from p4.pipeline import run  # noqa: E402


def write_case(root, case, extra_files=None):
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "case.json"), "w", encoding="utf-8") as handle:
        json.dump(case, handle, ensure_ascii=False, indent=2)
    for name, content in (extra_files or {}).items():
        path = os.path.join(root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if isinstance(content, bytes):
            with open(path, "wb") as handle:
                handle.write(content)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)


def go(mode, profile, case, extra=None):
    root = tempfile.mkdtemp(prefix="p4self-")
    out = os.path.join(root, "out")
    try:
        write_case(os.path.join(root, "in"), case, extra)
        result = run(os.path.join(root, "in"), out, mode, profile)
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


def check(name, cond, failures):
    if not cond:
        failures.append(name)


def test_rank(failures):
    result = go("corpus", "rank", {
        "case_id": "ex-rank",
        "query": "perovskite solar stability",
        "output_contract": {"not_a_real_field": "keep empty"},
        "documents": [
            {"id": "a", "title": "Perovskite solar cell stability", "abstract": "humidity", "doi": "10.1/a", "year": 2020, "source": "crossref"},
            {"id": "b", "title": "Perovskite solar cell stability", "abstract": "duplicate export", "doi": "10.1/a", "year": 2021, "source": "europepmc"},
            {"id": "c", "title": "Unrelated catalysis", "abstract": "zeolite", "doi": "10.1/c", "year": 2022},
        ],
    })
    ids = [row["id"] for row in result["primary"]["results"]]
    check("rank keeps newer duplicate", ids == ["b"], failures)
    check("rank drops unrelated", "c" not in ids, failures)
    check("rank contract stays empty", result.get("not_a_real_field") is None, failures)
    check("rank no invented doi", all(row["doi"] in ("10.1/a", None) for row in result["primary"]["results"]), failures)


def test_screen(failures):
    result = go("corpus", "screen", {
        "case_id": "ex-screen",
        "query": "perovskite",
        "criteria": {"inclusion": ["perovskite"], "exclusion": ["review"]},
        "documents": [
            {"id": "a", "title": "Perovskite devices", "abstract": "cells"},
            {"id": "d", "title": "Perovskite review", "abstract": "survey"},
        ],
    })
    ids = {row["id"]: row["decision"] for row in result["primary"]["results"]}
    check("screen keeps study", ids.get("a") == "include", failures)
    check("screen excludes review", "d" not in ids, failures)


def test_cite(failures):
    result = go("corpus", "cite", {
        "case_id": "ex-cite",
        "query": "stability",
        "documents": [
            {"id": "a", "title": "Stability study", "abstract": "cells", "references": ["b"]},
            {"id": "b", "title": "Cited method", "abstract": "protocol", "references": ["c"]},
            {"id": "c", "title": "Second hop", "abstract": "far"},
        ],
    })
    ids = {row["id"] for row in result["primary"]["results"]}
    check("cite one hop", ids == {"a", "b"}, failures)


def test_coverage(failures):
    result = go("corpus", "coverage", {
        "case_id": "ex-cov",
        "query": "perovskite quantum",
        "documents": [
            {"id": "a", "title": "Perovskite cells", "abstract": "film"},
            {"id": "c", "title": "Zeolite", "abstract": "acid"},
        ],
    })
    check("coverage lists miss", "c" in result["primary"]["omission_ids"], failures)
    check("coverage lists absent term", "quantum" in result["primary"]["uncovered_terms"], failures)


def test_recent(failures):
    result = go("corpus", "recent", {
        "case_id": "ex-recent",
        "query": "oxide",
        "documents": [
            {"id": "old", "title": "Oxide film", "year": 2018},
            {"id": "new", "title": "Oxide film study", "year": 2024},
            {"id": "na", "title": "Oxide note"},
        ],
    })
    ids = [row["id"] for row in result["primary"]["results"]]
    check("recent orders year", ids[0] == "new" and ids[-1] == "na", failures)


def test_quality(failures):
    result = go("corpus", "quality", {
        "case_id": "ex-q",
        "query": "trial",
        "documents": [{"id": "a", "title": "Clinical trial", "sample_size": 12}],
    })
    fields = result["primary"]["results"][0]["quality_fields"]
    check("quality keeps sample size", fields.get("sample_size") == 12, failures)
    check("quality does not invent blinding", "blinding" not in fields, failures)


def test_cross_patent(failures):
    cross = go("corpus", "crosslang", {
        "case_id": "ex-xl",
        "query": "catalysis",
        "documents": [{
            "id": "w",
            "title": "Catalysis note",
            "views": [
                {"language": "en", "text": "catalysis abstract", "role": "abstract"},
                {"language": "pt", "text": None, "role": "body"},
            ],
        }],
    })
    views = cross["primary"]["results"][0]["views"]
    check("crosslang keeps empty body", views[1]["text"] is None, failures)
    patent = go("corpus", "patent", {
        "case_id": "ex-pat",
        "query": "US123",
        "patents": [{"id": "p", "title": "Catalyst", "patent_number": "US123"}],
    })
    check("patent status empty", patent["primary"]["results"][0]["legal_status"] is None, failures)


def test_empty(failures):
    result = go("corpus", "rank", {"case_id": "ex-empty", "query": "anything"})
    check("empty corpus fails", result["status"] == "failed", failures)


def test_qa(failures):
    result = go("text", "qa", {
        "case_id": "ex-qa",
        "questions": [
            {"id": "q1", "text": "What humidity test was reported?"},
            {"id": "q2", "text": "quantum dot synthesis route"},
        ],
        "paragraphs": [{"id": "p1", "text": "The humidity test lasted 100 hours."}],
    })
    answers = {item["question_id"]: item for item in result["primary"]["answers"]}
    check("qa quotes", answers["q1"]["status"] == "quoted" and "100 hours" in answers["q1"]["answer"], failures)
    check("qa refuses", answers["q2"]["answer"] is None, failures)


def test_figure_compare_extract(failures):
    figure = go("text", "figure", {
        "case_id": "ex-fig",
        "images": [{"id": "fig2"}],
    }, {"table.csv": "y\n1.5\n"})
    values = figure["primary"]["table_values"]
    check("figure reads table", values and values[0]["values"]["y"] == 1.5, failures)
    check("figure gap without pixels", figure["primary"]["figure_gaps"], failures)
    compare = go("text", "compare", {
        "case_id": "ex-cmp",
        "documents": [
            {"id": "a", "condition": "dye A", "unit": "mM", "measures": {"concentration": 1}},
            {"id": "b", "condition": "dye B", "unit": "mM", "measures": {"concentration": 1}},
        ],
    })
    check("compare does not pool dyes", compare["primary"]["comparable"] == [], failures)
    extract = go("text", "extract", {
        "case_id": "ex-ex",
        "fields": ["Hc", "Ms"],
        "paragraphs": ["The Hc is 252.1 mT in the film."],
    })
    fields = {item["field"]: item["value"] for item in extract["primary"]["fields"]}
    check("extract reads Hc", fields["Hc"] == 252.1, failures)
    check("extract leaves Ms empty", fields["Ms"] is None, failures)


def test_fact_formula(failures):
    fact = go("text", "fact", {
        "case_id": "ex-fact",
        "claims": ["Hc increased", "Hc is 10"],
        "paragraphs": ["Hc did not increase in the control.", "The report says Hc is 10."],
    })
    verdicts = [item["verdict"] for item in fact["primary"]["claims"]]
    check("fact keeps negation", verdicts[0] == "insufficient_evidence", failures)
    check("fact can support", verdicts[1] == "supported", failures)
    formula = go("text", "formula", {"case_id": "ex-math"})
    check("formula without source is partial", formula["status"] == "partial" and formula["primary"]["derivation"] is None, failures)


def test_clean_stats(failures):
    clean = go("table", "clean", {
        "case_id": "ex-clean",
        "dictionary": {"missing": ["-999"]},
    }, {"data.csv": "name,value\na,1\na,1\nb,-999\n"})
    quality = clean["primary"]["quality"]
    stored = {row["name"]: row["value"] for row in clean["primary"]["rows"]}
    check("clean drops duplicate", quality["rows_out"] == 2, failures)
    check("clean does not impute", stored["b"] is None and quality["imputed_cells"] == 0, failures)
    stats = go("table", "stats", {"case_id": "ex-stats"}, {"data.csv": "x\n1\n2\n3\n"})
    column = stats["primary"]["columns"]["x"]
    check("stats mean", column["mean"] == 2 and column["p_value"] is None, failures)


def test_sql_viz(failures):
    root = tempfile.mkdtemp(prefix="p4sql-")
    try:
        db = os.path.join(root, "in", "lab.sqlite")
        os.makedirs(os.path.dirname(db), exist_ok=True)
        conn = sqlite3.connect(db)
        conn.execute("create table t(x integer)")
        conn.execute("insert into t(x) values (1),(2)")
        conn.commit()
        conn.close()
        with open(os.path.join(root, "in", "case.json"), "w", encoding="utf-8") as handle:
            json.dump({"case_id": "ex-sql", "query": "select count(*) as n from t"}, handle)
        good = run(os.path.join(root, "in"), os.path.join(root, "out"), "table", "sql")
        check("sql count", good["primary"]["rows"][0]["n"] == 2, failures)
        with open(os.path.join(root, "in", "case.json"), "w", encoding="utf-8") as handle:
            json.dump({"case_id": "ex-sql", "query": "select 1; drop table t"}, handle)
        bad = run(os.path.join(root, "in"), os.path.join(root, "out2"), "table", "sql")
        check("sql rejects multi", bad["status"] == "partial" and bad["primary"]["rows"] is None, failures)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    viz = go("table", "viz", {"case_id": "ex-viz"}, {"data.csv": "x\n4\n"})
    check("viz has number", viz["status"] == "success" and "4" in json.dumps(viz["primary"]), failures)


def test_audit_draft_draw(failures):
    audit = go("text", "audit", {
        "case_id": "ex-audit",
        "facets": ["伦理"],
        "paragraphs": ["The film was annealed at 100 C."],
    })
    finding = audit["primary"]["findings"][0]
    check("audit does not plant a defect", finding["status"] == "not_observed" and finding["verdict"] is None, failures)
    draft = go("draft", "evidence", {
        "case_id": "ex-draft",
        "sources": [{"id": "s1", "text": "The measured gap is 1.2 eV."}],
    })
    check("draft cites source", draft["primary"]["sentences"][0]["source_id"] == "s1", failures)
    translated = go("draft", "translate", {
        "case_id": "ex-tr",
        "sources": [{"id": "s1", "text": "The value is 10."}],
        "translations": [{"source_id": "s1", "text": "数值是 11。"}],
    })
    check("translation drops changed number", translated["primary"]["sentences"] == [], failures)
    draw = go("draft", "schematic", {
        "case_id": "ex-svg",
        "entities": [{"id": "A", "label": "anode"}, {"id": "B", "label": "cathode"}],
        "relations": [{"source": "A", "target": "B", "label": "ion"}, {"source": "A", "target": "C", "label": "missing"}],
    })
    check("schematic drops unknown node", len(draw["primary"]["nodes"]) == 2 and len(draw["primary"]["edges"]) == 1, failures)


TESTS = [
    ("rank", test_rank),
    ("screen", test_screen),
    ("cite", test_cite),
    ("coverage", test_coverage),
    ("recent", test_recent),
    ("quality", test_quality),
    ("cross", test_cross_patent),
    ("empty", test_empty),
    ("qa", test_qa),
    ("figure", test_figure_compare_extract),
    ("fact", test_fact_formula),
    ("clean", test_clean_stats),
    ("sql", test_sql_viz),
    ("draft", test_audit_draft_draw),
]

PROFILE_TEST = {
    "rank": "rank", "screen": "screen", "cite": "cite", "coverage": "coverage",
    "recent": "recent", "quality": "quality", "crosslang": "cross", "patent": "cross",
    "index": "rank", "synthesis": "screen",
    "qa": "qa", "client": "qa", "figure": "figure", "compare": "figure",
    "extract": "figure", "litclean": "figure", "fact": "fact", "formula": "fact",
    "repro": "fact", "audit": "draft",
    "clean": "clean", "stats": "clean", "viz": "sql", "code": "clean", "sql": "sql",
    "evidence": "draft", "format": "draft", "structure": "draft", "results": "draft",
    "response": "draft", "translate": "draft", "grant": "draft", "proposal": "draft",
    "thesis": "draft", "transfer": "draft", "mindmap": "draft", "schematic": "draft",
}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=None)
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)
    selected = TESTS
    if args.profile:
        name = PROFILE_TEST.get(args.profile)
        selected = [item for item in TESTS if item[0] == name]
        if not selected:
            print("no selftest for profile %s" % args.profile)
            return 2
    failures = []
    for name, func in selected:
        func(failures)
    if failures:
        print("FAILED %d" % len(failures))
        for item in failures:
            print(" -", item)
        return 1
    print("passed %d groups" % len(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
