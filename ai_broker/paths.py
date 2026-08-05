from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT, resolve_path


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def today_key() -> str:
    return datetime.now().strftime("%Y%m%d")


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value).strip())[:80] or "unknown"


def backend_slug(value: str) -> str:
    name = str(value).strip()
    return {"新心": "xinxin", "中鼎": "zhongding"}.get(name, safe_name(name))


class WorkDirs:
    def __init__(self, config: dict[str, Any], root: Path = PROJECT_ROOT) -> None:
        self.project_root = root
        self.data_root = resolve_path(root, config.get("data_root", "daily_data"))

    def day(self, day: str | None = None) -> Path:
        path = self.data_root / (day or today_key())
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exports(self) -> Path:
        return self._subdir("exports")

    def clips(self) -> Path:
        return self._subdir("clips")

    def previews(self) -> Path:
        return self._subdir("request_previews")

    def ai_results(self) -> Path:
        return self._subdir("ai_results")

    def state(self) -> Path:
        return self._subdir("state")

    def logs(self) -> Path:
        return self._subdir("logs")

    def _subdir(self, name: str) -> Path:
        path = self.day() / name
        path.mkdir(parents=True, exist_ok=True)
        return path


def latest_csv(dirs: WorkDirs) -> Path:
    files = list(dirs.exports().glob("实时主播数据-*.csv"))
    if not files:
        raise FileNotFoundError("没有找到实时主播数据 CSV，请先运行导出。")
    return max(files, key=lambda path: path.stat().st_mtime)
