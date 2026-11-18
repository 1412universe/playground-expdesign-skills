"""Small helpers shared by the four experimental-design skills."""
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
    return [value]


def norm_name(value) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value).lower())


def unit_key(unit):
    if unit is None:
        return None
    text = str(unit).strip().lower().replace(" ", "").replace("°", "").replace("º", "")
    text = text.replace("℃", "c")
    aliases = {
        "c": "c", "degc": "c", "celsius": "c", "摄氏度": "c",
        "h": "h", "hr": "h", "hrs": "h", "hour": "h", "hours": "h", "小时": "h",
        "d": "d", "day": "d", "days": "d", "天": "d",
        "g": "g", "gram": "g", "grams": "g", "克": "g",
        "ml": "ml", "毫升": "ml",
        "mg": "mg", "毫克": "mg",
    }
    return aliases.get(text, text)


def units_compatible(left, right):
    a, b = unit_key(left), unit_key(right)
    if a is None or b is None:
        return None
    return a == b


def first(mapping, keys, default=None):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    folded = {str(key).lower(): key for key in mapping}
    for key in keys:
        original = folded.get(str(key).lower())
        if original is None:
            continue
        value = mapping[original]
        if value not in (None, "", [], {}):
            return value
    return default


def strings_of(value, found=None):
    found = found if found is not None else []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            strings_of(item, found)
    elif isinstance(value, list):
        for item in value:
            strings_of(item, found)
    return found


def find_key(obj, keys, depth=0):
    """Return (value, path) for the first matching key, top level before children."""
    if not isinstance(obj, dict) or depth > 5:
        return None, None
    for key in keys:
        if key in obj:
            return obj[key], str(key)
    for key, value in obj.items():
        if key in ("output_contract", "scoring"):
            continue
        if isinstance(value, dict):
            found, path = find_key(value, keys, depth + 1)
            if found is not None:
                return found, "%s.%s" % (key, path)
    return None, None


def evidence(locator, quote):
    text = str(quote)
    if len(text) > 240:
        text = text[:240]
    return {"locator": locator, "quote": text}


STATUS_MAP = {
    "on_hand": "on_hand", "available": "on_hand", "in_lab": "on_hand",
    "已具备": "on_hand", "具备": "on_hand", "在库": "on_hand",
    "outsource": "outsource", "可外协": "outsource", "外协": "outsource",
    "purchase": "purchase", "需采购": "purchase", "采购": "purchase", "order": "purchase",
    "unavailable": "unavailable", "不具备": "unavailable", "缺失": "unavailable",
    "missing": "unavailable", "none": "unavailable",
}


def canon_status(value):
    if value is None:
        return None
    key = str(value).strip().lower()
    return STATUS_MAP.get(key, STATUS_MAP.get(str(value).strip(), "unspecified"))
