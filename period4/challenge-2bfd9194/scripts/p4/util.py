"""Helpers for the period-4 skill runner. Standard library only."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "").replace("，", "")
        if text.lower() in MISSING_TOKENS:
            return None
        match = re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", text)
        if not match:
            return None
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


def sane(value):
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        rounded = round(value, 10)
        if abs(rounded) < 1e15 and abs(rounded - round(rounded)) < 1e-9:
            return int(round(rounded))
        return rounded
    if isinstance(value, dict):
        return {str(key): sane(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sane(item) for item in value]
    return value


def dump(obj) -> str:
    return json.dumps(sane(obj), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def write_json(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(dump(obj))


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return []


def first(mapping, keys, default=None):
    if not isinstance(mapping, dict):
        return default
    folded = {str(key).lower(): key for key in mapping}
    for key in keys:
        original = mapping.get(key, None)
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
        folded_key = folded.get(str(key).lower())
        if folded_key is None:
            continue
        value = mapping[folded_key]
        if value not in (None, "", [], {}):
            return value
        original = value
    return default


def find_key(obj, keys, depth=0):
    if not isinstance(obj, dict) or depth > 6:
        return None, None
    wanted = {str(key).lower() for key in keys}
    for key, value in obj.items():
        if str(key).lower() in wanted and value not in (None, "", [], {}):
            return value, str(key)
    for key, value in obj.items():
        if str(key).lower() in ("output_contract", "scoring", "contract"):
            continue
        if isinstance(value, dict):
            found, path = find_key(value, keys, depth + 1)
            if found is not None:
                return found, "%s.%s" % (key, path)
    return None, None


def evidence(locator, quote):
    text = re.sub(r"\s+", " ", str(quote or "")).strip()
    if len(text) > 240:
        text = text[:240]
    return {"locator": locator, "quote": text}


MISSING_TOKENS = {
    "", "-", "--", "na", "n/a", "null", "none", "nan", ".", "missing",
    "-999", "-9999", "9999", "未检测", "缺失", "空", "#n/a",
}

STOP = {
    "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
    "a", "an", "of", "to", "in", "on", "or", "by", "at", "as", "is", "be",
    "的", "了", "与", "及", "和", "在", "对", "中", "为",
}


def tokens(text):
    found = re.findall(r"[a-z0-9]{2,}|[\u4e00-\u9fff]{2,}", str(text or "").lower())
    return [item for item in found if item not in STOP]


def norm_title(text):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(text or "").lower())


def clip(text, limit=400):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        return text[:limit]
    return text
