from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "analysis_config.json"
DEFAULT_DIMENSIONS = ["运营维度", "调试维度", "妆造维度", "才艺维度", "声乐维度"]


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"配置文件必须是 JSON 对象: {path}")
    return data


def resolve_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (root / path).resolve()


def dimensions(config: dict[str, Any]) -> list[str]:
    values = config.get("dimensions", DEFAULT_DIMENSIONS)
    if not isinstance(values, list):
        return DEFAULT_DIMENSIONS.copy()
    cleaned = [str(item).strip() for item in values if str(item).strip()]
    return cleaned or DEFAULT_DIMENSIONS.copy()


def configured_concurrency(value: Any, total: int) -> int:
    if isinstance(value, str) and value.strip().lower() in {"all", "auto"}:
        return max(1, total)
    return max(1, int(value or 1))

