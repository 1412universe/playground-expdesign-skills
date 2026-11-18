"""Read /input without assuming a domain from the filename."""
from __future__ import annotations

import csv
import json
import os
import zipfile
from xml.etree import ElementTree as ET

from ed.util import sha256_file

TEXT_EXT = {".md", ".txt", ".tex", ".csv", ".tsv", ".json", ".log"}
TABLE_EXT = {".csv", ".tsv"}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def load(input_dir: str):
    root = os.path.abspath(input_dir)
    case = {}
    case_path = os.path.join(root, "case.json")
    if os.path.isfile(case_path):
        case = _read_json(case_path) or {}
        if not isinstance(case, dict):
            case = {"_non_object_case": case}
    task = ""
    task_path = os.path.join(root, "task.md")
    if os.path.isfile(task_path):
        task = _read_text(task_path)
    files = []
    extras = []
    if os.path.isdir(root):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in (".git", "__pycache__")]
            for name in sorted(filenames):
                path = os.path.join(dirpath, name)
                rel = os.path.relpath(path, root)
                meta = _read_file(path, rel)
                files.append(meta)
                if meta.get("json") is not None and rel != "case.json" and isinstance(meta["json"], dict):
                    extras.append({"path": rel, "json": meta["json"]})
    return {
        "root": root,
        "case": case if isinstance(case, dict) else {},
        "task": task,
        "files": files,
        "extras": extras,
    }


def _read_file(path, rel):
    ext = os.path.splitext(path)[1].lower()
    info = {
        "path": rel,
        "bytes": os.path.getsize(path),
        "sha256": sha256_file(path),
        "kind": ext.lstrip(".") or "file",
        "text": None,
        "rows": None,
        "json": None,
        "reader": None,
        "truncated": False,
        "error": None,
    }
    try:
        if ext in TABLE_EXT:
            rows, text, truncated = _read_table(path, ext)
            info.update(rows=rows, text=text, truncated=truncated, reader="csv")
        elif ext == ".json":
            obj = _read_json(path)
            info["json"] = obj
            info["text"] = json.dumps(obj, ensure_ascii=False)[:200000]
            info["reader"] = "json"
        elif ext in (".md", ".txt", ".tex", ".log"):
            info["text"] = _read_text(path)
            info["reader"] = "text"
            info["truncated"] = len(info["text"]) >= 200000
        elif ext == ".xlsx":
            rows, text, err = _read_xlsx(path)
            info.update(rows=rows, text=text, reader="xlsx-stdlib", error=err)
        elif ext == ".pdf":
            text, reader, err = _read_pdf(path)
            info.update(text=text, reader=reader, error=err)
        elif ext == ".mat":
            rows, reader, err = _read_mat(path)
            info.update(rows=rows, reader=reader, error=err)
        else:
            info["error"] = "unsupported type %s; not interpreted" % ext
    except Exception as exc:  # noqa: BLE001 — record and continue
        info["error"] = "read failed: %s" % exc
    return info


def _read_text(path, limit=200000):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_table(path, ext, limit=5000):
    delimiter = "\t" if ext == ".tsv" else ","
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = []
        truncated = False
        for row in reader:
            if len(rows) >= limit:
                truncated = True
                break
            rows.append(dict(row))
    text = ""
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(200000)
    return rows, text, truncated


def _read_xlsx(path, limit=5000):
    try:
        with zipfile.ZipFile(path) as archive:
            shared = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for node in root.findall("m:si", NS):
                    shared.append("".join(text.text or "" for text in node.iter("{%s}t" % NS["m"])))
            sheet_name = "xl/worksheets/sheet1.xml"
            if sheet_name not in archive.namelist():
                sheets = [name for name in archive.namelist() if name.startswith("xl/worksheets/sheet")]
                if not sheets:
                    return [], "", "xlsx has no worksheet"
                sheet_name = sorted(sheets)[0]
            root = ET.fromstring(archive.read(sheet_name))
            grid = []
            for row in root.findall("m:sheetData/m:row", NS):
                values = []
                for cell in row.findall("m:c", NS):
                    kind = cell.attrib.get("t")
                    value_node = cell.find("m:v", NS)
                    inline = cell.find("m:is", NS)
                    if kind == "s" and value_node is not None and value_node.text:
                        values.append(shared[int(value_node.text)])
                    elif kind == "inlineStr" and inline is not None:
                        values.append("".join(text.text or "" for text in inline.iter("{%s}t" % NS["m"])))
                    elif value_node is not None and value_node.text is not None:
                        values.append(value_node.text)
                    else:
                        values.append("")
                grid.append(values)
            if not grid:
                return [], "", "xlsx sheet empty"
            header = [str(item) or "col%d" % (i + 1) for i, item in enumerate(grid[0])]
            rows = []
            for raw in grid[1:limit + 1]:
                rows.append({header[i]: raw[i] if i < len(raw) else "" for i in range(len(header))})
            return rows, "", None
    except Exception as exc:  # noqa: BLE001
        return [], "", "xlsx read failed: %s" % exc


def _read_pdf(path):
    try:
        import fitz
        doc = fitz.open(path)
        pages = []
        for index, page in enumerate(doc):
            if index >= 40:
                break
            pages.append(page.get_text("text") or "")
        doc.close()
        return "\n".join(pages)[:200000], "pymupdf", None
    except Exception:
        pass
    try:
        from pdfminer.high_level import extract_text
        return (extract_text(path) or "")[:200000], "pdfminer", None
    except Exception as exc:  # noqa: BLE001
        return None, None, "pdf not read: %s" % exc


def _read_mat(path):
    try:
        from scipy.io import loadmat
    except Exception as exc:  # noqa: BLE001
        return None, None, "mat not read: %s" % exc
    try:
        raw = loadmat(path)
        rows = []
        for key, value in raw.items():
            if key.startswith("_"):
                continue
            rows.append({"name": key, "shape": list(getattr(value, "shape", [])), "type": type(value).__name__})
        return rows, "scipy.io.loadmat", None
    except Exception as exc:  # noqa: BLE001
        return None, None, "mat not read: %s" % exc
