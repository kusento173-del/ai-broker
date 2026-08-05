from __future__ import annotations

import csv
import time
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .ai_client import build_payload, call_with_retries, parse_ai_json
from .capture import capture_clip
from .config import configured_concurrency, load_config
from .exporter import export_csv
from .outputs import send_table_webhook, send_wechat_summary, write_local_table
from .paths import WorkDirs, backend_slug, latest_csv, safe_name
from .rules import is_warning, reason
from .state import anchor_key, load_state, mark_done, save_state
from .utils import display_value, row_value, safe_print, write_json


def load_warning_rows(csv_path: Path, config: dict[str, Any]) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    warnings = [row for row in rows if is_warning(row, config)]
    warning_reason = reason(config)
    for row in warnings:
        row["是否预警主播"] = "是"
        row["预警原因"] = warning_reason
    return warnings


def runtime_concurrency(config: dict[str, Any], name: str, total: int) -> int:
    return min(configured_concurrency(config.get("runtime", {}).get(name, 1), total), total)


def ai_submit_interval(config: dict[str, Any]) -> float:
    return max(0.0, float(config.get("runtime", {}).get("ai_submit_interval_seconds", 0)))


def loop_interval(config: dict[str, Any]) -> int:
    return max(1, int(float(config.get("runtime", {}).get("monitor_interval_minutes", 10)) * 60))


def capture_item(index: int, total: int, row: dict[str, str], config: dict[str, Any], dirs: WorkDirs) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    safe_print(f"[{index}/{total}] 录制 {display_value(row, '后台')} 主播 {display_value(row, '主播ID')} ...")
    media = capture_clip(row, config, dirs)
    payload = build_payload(row, media, config, include_audio=True)
    prefix = f"{backend_slug(row_value(row, '后台', '新心'))}_{safe_name(row_value(row, '主播ID'))}_{safe_name(row_value(row, '直播间ID'))}"
    preview = dirs.previews() / f"{prefix}.json"
    write_json(preview, {"row": row, "media": media, "payload_note": "payload 内包含 base64 视频/音频，正式调用会直接使用此结构。", "payload": payload})
    safe_print(f"已保存片段: {media['video']}")
    safe_print(f"已保存音频: {media['audio']}")
    safe_print(f"已保存截图: {media['screenshot']}")
    safe_print(f"已保存请求预览: {preview}")
    return row, media, payload


def has_audio(payload: dict[str, Any]) -> bool:
    content = payload["messages"][0]["content"]
    return any(part.get("type") == "input_audio" for part in content)


def analyze_item(
    index: int,
    total: int,
    row: dict[str, str],
    media: dict[str, str],
    payload: dict[str, Any],
    config: dict[str, Any],
    dirs: WorkDirs,
) -> dict[str, Any]:
    label = f"{display_value(row, '后台')} 主播 {display_value(row, '主播昵称')} / {display_value(row, '抖音号/短ID')}"
    safe_print(f"[{index}/{total}] AI 分析{label} ...")
    try:
        raw = call_with_retries(payload, config, label)
    except RuntimeError as exc:
        if not has_audio(payload):
            raise
        safe_print(f"含音频调用失败，重试仅视频分析: {exc}")
        raw = call_with_retries(build_payload(row, media, config, include_audio=False), config, f"{label} 仅视频")
    analysis = parse_ai_json(raw)
    prefix = f"{backend_slug(row_value(row, '后台', '新心'))}_{safe_name(row_value(row, '主播ID'))}_{safe_name(row_value(row, '直播间ID'))}"
    result_path = dirs.ai_results() / f"{prefix}.json"
    write_json(result_path, {"row": row, "media": media, "analysis": analysis, "raw": raw})
    return {"key": anchor_key(row), "row": row, "media": media, "analysis": analysis, "result_path": result_path}


def run_once(args: Namespace) -> None:
    config = load_config(args.config)
    dirs = WorkDirs(config)

    if args.refresh_export or args.export_only:
        export_path = dirs.exports() / f"实时主播数据-{time.strftime('%Y%m%d-%H%M%S')}-含预警标记.csv"
        safe_print(f"先刷新实时导出: {export_path}")
        args.input = export_csv(config, dirs, export_path)
        if args.export_only:
            return

    csv_path = Path(args.input) if args.input else latest_csv(dirs)
    warnings = load_warning_rows(csv_path, config)
    state = load_state(dirs)
    done = state.setdefault("items", {})
    pending = warnings if args.rerun_today else [row for row in warnings if anchor_key(row) not in done]
    if args.limit:
        pending = pending[: args.limit]

    print(f"输入文件: {csv_path}")
    print(f"预警主播: {len(warnings)}，今日待分析: {len(pending)}")
    if not pending:
        return

    captured: list[tuple[dict[str, str], dict[str, str], dict[str, Any]] | None] = [None] * len(pending)
    capture_workers = runtime_concurrency(config, "capture_concurrency", len(pending))
    print(f"开始批量录制所有待分析主播，并发数: {capture_workers}")
    with ThreadPoolExecutor(max_workers=capture_workers) as executor:
        futures = {executor.submit(capture_item, index, len(pending), row, config, dirs): index for index, row in enumerate(pending, start=1)}
        for future in as_completed(futures):
            index = futures[future]
            row = pending[index - 1]
            try:
                captured[index - 1] = future.result()
            except Exception as exc:
                safe_print(f"跳过主播 {display_value(row, '主播ID')}: {exc}")

    items = [item for item in captured if item is not None]
    print(f"批量录制完成: 成功 {len(items)} 个，跳过 {len(pending) - len(items)} 个")
    if not args.call_ai or not items:
        return

    ai_workers = runtime_concurrency(config, "ai_concurrency", len(items))
    interval = ai_submit_interval(config)
    print(f"开始 AI 分析，并发数: {ai_workers}，提交间隔: {interval:g} 秒")
    results: list[dict[str, Any] | None] = [None] * len(items)
    with ThreadPoolExecutor(max_workers=ai_workers) as executor:
        futures = {}
        for index, (row, media, payload) in enumerate(items, start=1):
            if interval and index > 1:
                time.sleep(interval)
            futures[executor.submit(analyze_item, index, len(items), row, media, payload, config, dirs)] = index
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index - 1] = future.result()
            except Exception as exc:
                safe_print(f"[{index}/{len(items)}] AI 分析失败: {exc}")

    successful_rows: list[dict[str, str]] = []
    for item in results:
        if not item:
            continue
        row = item["row"]
        analysis = item["analysis"]
        media = item["media"]
        table_path = ""
        webhook_rows = 0
        if args.write_table:
            table_path = str(write_local_table(row, analysis, config, dirs))
            safe_print(f"已写入本地表格: {table_path}")
        if args.send_table_webhook:
            webhook_rows = send_table_webhook(row, analysis, config)
            safe_print(f"已发送飞书表格 webhook: {webhook_rows} 条")
        mark_done(state, row, media, item["result_path"], table_path, webhook_rows)
        save_state(dirs, state)
        successful_rows.append(row)
    send_wechat_summary(successful_rows, config)


def run_loop(args: Namespace) -> None:
    while True:
        print(f"\n===== warning analysis loop started {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
        try:
            run_once(args)
        except Exception as exc:
            print(f"loop failed: {exc}")
        config = load_config(args.config)
        seconds = loop_interval(config)
        print(f"sleeping {seconds} seconds...")
        time.sleep(seconds)
