from __future__ import annotations

from typing import Any


DEFAULT_RULE = {"min_live_seconds": 3 * 3600, "max_total_users": 3000, "max_income": 3000}


def duration_to_seconds(value: Any) -> int:
    if value in ("", None):
        return 0
    parts = str(value).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(float(parts[1]))
        return int(float(parts[0]))
    except ValueError:
        return 0


def to_number(value: Any) -> float:
    if value in ("", None):
        return 0.0
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return 0.0


def rule(config: dict[str, Any]) -> dict[str, Any]:
    merged = DEFAULT_RULE.copy()
    configured = config.get("warning_rule", {})
    if isinstance(configured, dict):
        merged.update({key: value for key, value in configured.items() if value not in ("", None)})
    return merged


def duration_text(seconds: Any) -> str:
    total = int(float(seconds))
    if total % 3600 == 0:
        return f"{total // 3600}小时"
    if total % 60 == 0:
        return f"{total // 60}分钟"
    return f"{total}秒"


def reason(config: dict[str, Any], prompt_style: bool = False) -> str:
    current = rule(config)
    duration = duration_text(current["min_live_seconds"])
    total_users = int(float(current["max_total_users"]))
    income = int(float(current["max_income"]))
    joiner = "但" if prompt_style else "且"
    if total_users == income:
        return f"开播大于 {duration}，{joiner}累计观众和音浪/流水都小于 {total_users}"
    return f"开播大于 {duration}，{joiner}累计观众小于 {total_users}，音浪/流水小于 {income}"


def is_warning(row: dict[str, Any], config: dict[str, Any]) -> bool:
    current = rule(config)
    return (
        duration_to_seconds(row.get("开播时长")) > int(current["min_live_seconds"])
        and to_number(row.get("累计观众")) < float(current["max_total_users"])
        and to_number(row.get("音浪/流水")) < float(current["max_income"])
    )

