from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import WorkDirs, today_key
from .utils import display_value, read_json, row_value, write_json


def anchor_key(row: dict[str, str]) -> str:
    return f"{row_value(row, '后台', '新心')}|{row_value(row, '主播ID')}|{row_value(row, '直播间ID')}"


def state_path(dirs: WorkDirs) -> Path:
    return dirs.state() / f"analyzed_{today_key()}.json"


def load_state(dirs: WorkDirs) -> dict[str, Any]:
    state = read_json(state_path(dirs), {"date": today_key(), "items": {}})
    items = state.get("items") or {}
    normalized = {}
    for key, item in items.items():
        if isinstance(item, dict) and key.count("|") == 1:
            item = {"后台": "新心", **item}
            key = f"新心|{key}"
        normalized[key] = item
    state["items"] = normalized
    return state


def save_state(dirs: WorkDirs, state: dict[str, Any]) -> None:
    write_json(state_path(dirs), state)


def mark_done(
    state: dict[str, Any],
    row: dict[str, str],
    media: dict[str, str],
    result_path: Path,
    table_path: str,
    webhook_rows: int,
) -> None:
    state.setdefault("items", {})[anchor_key(row)] = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "后台": row_value(row, "后台", "新心"),
        "主播昵称": display_value(row, "主播昵称"),
        "抖音号/短ID": display_value(row, "抖音号/短ID"),
        "主播ID": row_value(row, "主播ID"),
        "直播间ID": row_value(row, "直播间ID"),
        "对应运营": display_value(row, "经纪人"),
        "video": media["video"],
        "audio": media["audio"],
        "screenshot": media["screenshot"],
        "analysis": str(result_path),
        "written_table": table_path,
        "sent_table_webhook_rows": webhook_rows,
    }
