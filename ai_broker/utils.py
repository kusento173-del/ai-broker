from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def row_value(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key)
    return default if value in (None, "") else str(value)


def display_value(row: dict[str, Any], key: str, default: str = "接口未返回") -> str:
    return row_value(row, key, default).strip() or default


def text_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def safe_print(text: str) -> None:
    print(text, flush=True)

