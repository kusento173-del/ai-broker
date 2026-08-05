from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from .paths import WorkDirs, now_stamp
from .rules import is_warning, reason
from .utils import read_json


DATA_EXT_API = "/ark/api/data_ext/room/get_room_by_label"
FOLLOW_API = "/ark/api/broker/follow/get_room_by_label"
ROOM_DATA_API = "/ark/api/broker/follow/get_room_data"

COL_RAW_JSON = "原始JSON"
COL_WARNING = "是否预警主播"
COL_WARNING_REASON = "预警原因"
COL_BACKEND = "后台"
COL_NICKNAME = "主播昵称"
COL_ANCHOR_ID = "主播ID"
COL_DOUYIN_ID = "抖音号/短ID"

CSV_COLUMNS = [
    "序号",
    COL_BACKEND,
    COL_NICKNAME,
    COL_ANCHOR_ID,
    COL_DOUYIN_ID,
    "直播标题",
    "经纪人",
    "直播间ID",
    "LiveID",
    "开播时间",
    "开播时长",
    "当前人气",
    "累计观众",
    "送礼人数",
    "音浪/流水",
    "增长粉丝",
    "热度/Popularity",
    "是否私密",
    "是否隐身直播间",
    "是否经纪人",
    "是否招募经纪人",
    "FLV拉流地址",
    COL_WARNING,
    COL_WARNING_REASON,
    COL_RAW_JSON,
]


FETCH_ROOMS_SCRIPT = r"""
async ({ apiPath, pageSize, maxPages, roomTag, sortField, sortType }) => {
  const parseMaybeJSON = (value) => {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); } catch { return value; }
  };
  const normalizeResponse = (json) => {
    const seen = new Set();
    const arrays = [];
    const totals = [];
    const walk = (value, key = "") => {
      value = parseMaybeJSON(value);
      if (value && typeof value === "object") {
        if (seen.has(value)) return;
        seen.add(value);
      }
      if (Array.isArray(value)) {
        if (/rooms?|room_list|list|items|records|dataSource|series/i.test(key)) arrays.push(value);
        value.forEach((item) => walk(item));
        return;
      }
      if (!value || typeof value !== "object") return;
      for (const [k, v] of Object.entries(value)) {
        if (/^(total|count|total_count|totalCount)$/i.test(k) && Number.isFinite(Number(v))) totals.push(Number(v));
        walk(v, k);
      }
    };
    const payload = parseMaybeJSON(json?.data_string ?? json?.data ?? json);
    walk(payload);
    return { rooms: arrays.sort((a, b) => b.length - a.length)[0] || [], total: totals.length ? Math.max(...totals) : 0 };
  };
  const query = (params) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") qs.set(key, String(value));
    });
    return qs.toString();
  };
  const rowKey = (room) => [
    room?.id_str || room?.room_id || room?.baseData?.idStr || "",
    room?.owner?.user_id_str || room?.owner?.user_id || room?.anchor_id || "",
    room?.live_id || room?.baseData?.liveID || "",
  ].filter(Boolean).join("|") || JSON.stringify(room).slice(0, 200);

  const all = [];
  const seen = new Set();
  for (let page = 1; page <= maxPages; page += 1) {
    const url = `${apiPath}?${query({ room_tag: roomTag, sort_field: sortField, sort_type: sortType, cur_page: page, page_size: pageSize })}`;
    const response = await fetch(url, { credentials: "include", headers: { accept: "application/json, text/plain, */*", "x-requested-with": "XMLHttpRequest" } });
    const text = await response.text();
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
    const json = parseMaybeJSON(text);
    if (json?.status_code && Number(json.status_code) !== 0) throw new Error(json.status_message || json.message || `status_code=${json.status_code}`);
    const result = normalizeResponse(json);
    for (const room of result.rooms) {
      const key = rowKey(room);
      if (!seen.has(key)) {
        seen.add(key);
        all.push(room);
      }
    }
    if (!result.rooms.length || result.rooms.length < pageSize || (result.total && all.length >= result.total)) break;
  }
  return { rooms: all };
}
"""


FETCH_ROOM_DATA_SCRIPT = r"""
async ({ apiPath, roomIds, batchSize }) => {
  const parseMaybeJSON = (value) => {
    if (typeof value !== "string") return value;
    try { return JSON.parse(value); } catch { return value; }
  };
  const rooms = [];
  for (let start = 0; start < roomIds.length; start += batchSize || 20) {
    const batch = roomIds.slice(start, start + (batchSize || 20));
    const qs = batch.map((id) => `room_ids=${encodeURIComponent(id)}`).join("&");
    const response = await fetch(`${apiPath}?${qs}`, { credentials: "include", headers: { accept: "application/json, text/plain, */*", "x-requested-with": "XMLHttpRequest" } });
    const text = await response.text();
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${text.slice(0, 200)}`);
    const json = parseMaybeJSON(text);
    if (json?.status_code && Number(json.status_code) !== 0) throw new Error(json.message || `status_code=${json.status_code}`);
    const payload = parseMaybeJSON(json?.data_string ?? json?.data ?? json);
    if (Array.isArray(payload?.rooms)) rooms.push(...payload.rooms);
  }
  return rooms;
}
"""


def ensure_edge(cdp_url: str) -> None:
    try:
        with urlopen(cdp_url.rstrip("/") + "/json/version", timeout=2) as response:
            if response.status != 200:
                raise RuntimeError(f"Edge debug endpoint returned HTTP {response.status}.")
    except (OSError, URLError) as exc:
        raise RuntimeError("没有连接到共享 Edge 登录态。请先从直播数据导出项目启动并登录新心和中鼎 Edge。") from exc


def get_path(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return ""
        cur = cur[part]
    return "" if cur is None else cur


def first_value(data: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = get_path(data, path)
        if value not in ("", None):
            return value
    return ""


def anchor_id(room: dict[str, Any]) -> str:
    return str(first_value(room, "owner.user_id_str", "owner.user_id", "owner.userIDStr", "anchor_id", "uid"))


def room_id(room: dict[str, Any]) -> str:
    return str(first_value(room, "id_str", "room_id", "baseData.idStr", "baseData.roomID"))


def merge_missing(target: dict[str, Any], path: str, value: Any) -> None:
    if value in ("", None):
        return
    cur = target
    parts = path.split(".")
    for part in parts[:-1]:
        child = cur.get(part)
        if not isinstance(child, dict):
            child = {}
            cur[part] = child
        cur = child
    if cur.get(parts[-1]) in ("", None):
        cur[parts[-1]] = value


def merge_follow_rooms(rooms: list[dict[str, Any]], follow_rooms: list[dict[str, Any]]) -> None:
    by_anchor = {anchor_id(room): room for room in follow_rooms if anchor_id(room)}
    by_room = {room_id(room): room for room in follow_rooms if room_id(room)}
    for room in rooms:
        follow = by_anchor.get(anchor_id(room)) or by_room.get(room_id(room))
        if follow:
            merge_missing(room, "owner.nick_name", first_value(follow, "owner.nick_name", "owner.nickname", "owner.nickName", "nickname"))
            merge_missing(room, "owner.avatar_large", first_value(follow, "owner.avatar_large"))


def merge_room_data(rooms: list[dict[str, Any]], room_data: list[dict[str, Any]]) -> None:
    by_room = {room_id(item) or str(first_value(item, "base_data.id_str")): item for item in room_data}
    for room in rooms:
        item = by_room.get(room_id(room))
        if not item:
            continue
        for source, target in [
            ("owner.nick_name", "owner.nick_name"),
            ("owner.nickname", "owner.nick_name"),
            ("owner.short_id", "owner.short_id"),
            ("owner.aweme_id", "owner.aweme_id"),
            ("owner.user_id_str", "owner.user_id_str"),
            ("base_data.broker_name", "broker_name"),
            ("base_data.title", "title"),
            ("base_data.ticket_count", "ticket_count"),
            ("base_data.total_user_count", "total_user_count"),
            ("base_data.pay_user_count", "pay_user_count"),
            ("base_data.follow_count", "follow_count"),
            ("base_data.user_count", "user_count"),
            ("base_data.create_time", "create_time"),
            ("base_data.live_id", "live_id"),
            ("base_data.id_str", "id_str"),
        ]:
            merge_missing(room, target, first_value(item, source))


def unix_time_text(value: Any) -> str:
    if value in ("", None):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number > 1_000_000_000_000:
        number /= 1000
    return datetime.fromtimestamp(number).strftime("%Y-%m-%d %H:%M:%S")


def hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def live_duration(room: dict[str, Any]) -> str:
    explicit = first_value(room, "live_duration", "liveDuration", "baseData.liveDuration")
    if explicit:
        return str(explicit)
    started = first_value(room, "create_time", "baseData.createTime", "baseData.startTime")
    try:
        timestamp = int(float(started))
    except (TypeError, ValueError):
        return ""
    if timestamp > 1_000_000_000_000:
        timestamp //= 1000
    return hms(int(datetime.now(tz=timezone.utc).timestamp()) - timestamp)


def row_warning(row: dict[str, Any], config: dict[str, Any]) -> tuple[str, str]:
    if not is_warning(row, config):
        return "否", ""
    return "是", reason(config)


def room_to_row(room: dict[str, Any], index: int, backend: str, config: dict[str, Any]) -> dict[str, Any]:
    row = {
        "序号": index,
        COL_BACKEND: backend,
        COL_NICKNAME: first_value(room, "owner.nick_name", "owner.nickname", "owner.nickName", "nickname"),
        COL_ANCHOR_ID: first_value(room, "owner.user_id_str", "owner.user_id", "owner.userIDStr", "anchor_id"),
        COL_DOUYIN_ID: first_value(room, "owner.short_id", "owner.aweme_id", "owner.awemeID"),
        "直播标题": first_value(room, "title", "baseData.title"),
        "经纪人": first_value(room, "broker_name", "baseData.brokerName", "brokerName"),
        "直播间ID": first_value(room, "id_str", "room_id", "baseData.idStr", "baseData.roomID"),
        "LiveID": first_value(room, "live_id", "liveID", "baseData.liveID"),
        "开播时间": unix_time_text(first_value(room, "create_time", "baseData.createTime", "baseData.startTime")),
        "开播时长": live_duration(room),
        "当前人气": first_value(room, "user_count", "baseData.userCount", "userCount"),
        "累计观众": first_value(room, "total_user_count", "baseData.totalUserCount", "totalUserCount", "watchUV"),
        "送礼人数": first_value(room, "pay_user_count", "baseData.payUserCount", "payUserCount"),
        "音浪/流水": first_value(room, "ticket_count", "baseData.ticketCount", "baseData.totalIncome", "score"),
        "增长粉丝": first_value(room, "follow_count", "baseData.followCount", "followCount", "followUV"),
        "热度/Popularity": first_value(room, "popularity"),
        "是否私密": first_value(room, "is_secret", "privateData.isSecret"),
        "是否隐身直播间": first_value(room, "is_invisible_room"),
        "是否经纪人": first_value(room, "owner.is_broker", "owner.isBroker"),
        "是否招募经纪人": first_value(room, "owner.is_recruit_broker", "owner.isRecruitBroker"),
        "FLV拉流地址": first_value(room, "flv_pull_url"),
        COL_RAW_JSON: json.dumps(room, ensure_ascii=False, separators=(",", ":")),
    }
    row[COL_WARNING], row[COL_WARNING_REASON] = row_warning(row, config)
    return row


def identity_key(row: dict[str, Any]) -> str:
    backend = str(row.get(COL_BACKEND) or "新心").strip()
    anchor = str(row.get(COL_ANCHOR_ID) or "").strip()
    return f"{backend}|{anchor}" if anchor else ""


def remember_identity(cache: dict[str, dict[str, str]], row: dict[str, Any]) -> None:
    key = identity_key(row)
    if not key:
        return
    cached = cache.setdefault(key, {})
    for column in (COL_NICKNAME, COL_DOUYIN_ID):
        value = str(row.get(column) or "").strip()
        if value and value != "接口未返回":
            cached[column] = value


def identity_cache(dirs: WorkDirs, output: Path) -> dict[str, dict[str, str]]:
    cache: dict[str, dict[str, str]] = {}
    for path in sorted(dirs.exports().glob("*.csv"), key=lambda item: item.stat().st_mtime):
        if path.resolve() == output.resolve():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    remember_identity(cache, row)
        except OSError:
            continue
    state = read_json(dirs.state() / f"analyzed_{dirs.day().name}.json", {"items": {}})
    for item in (state.get("items") or {}).values():
        if isinstance(item, dict):
            remember_identity(cache, item)
    for path in sorted(dirs.ai_results().glob("*.json"), key=lambda item: item.stat().st_mtime):
        data = read_json(path, {})
        row = data.get("row") if isinstance(data, dict) else None
        if isinstance(row, dict):
            remember_identity(cache, row)
    return cache


def backfill_identity(rows: list[dict[str, Any]], dirs: WorkDirs, output: Path) -> int:
    cache = identity_cache(dirs, output)
    count = 0
    for row in rows:
        cached = cache.get(identity_key(row))
        if not cached:
            continue
        changed = False
        for column in (COL_NICKNAME, COL_DOUYIN_ID):
            if not str(row.get(column) or "").strip() and cached.get(column):
                row[column] = cached[column]
                changed = True
        if changed:
            count += 1
        remember_identity(cache, row)
    return count


def fetch_rooms(page: Any, api_path: str) -> list[dict[str, Any]]:
    result = page.evaluate(
        FETCH_ROOMS_SCRIPT,
        {"apiPath": api_path, "pageSize": 100, "maxPages": 50, "roomTag": 0, "sortField": "user_count", "sortType": "desc"},
    )
    return result.get("rooms") or []


def fetch_room_data(page: Any, rooms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = list(dict.fromkeys(room_id(room) for room in rooms if room_id(room)))
    if not ids:
        return []
    return page.evaluate(FETCH_ROOM_DATA_SCRIPT, {"apiPath": ROOM_DATA_API, "roomIds": ids, "batchSize": 20})


def export_rooms(browser: dict[str, Any]) -> list[dict[str, Any]]:
    cdp_url = browser["cdp_url"]
    ensure_edge(cdp_url)
    with sync_playwright() as p:
        browser_client = p.chromium.connect_over_cdp(cdp_url)
        context = browser_client.contexts[0] if browser_client.contexts else None
        if context is None:
            browser_client.close()
            raise RuntimeError("已连接 Edge，但没有可用的浏览器上下文。")
        pages = [page for ctx in browser_client.contexts for page in ctx.pages]
        page = next((item for item in pages if "union.bytedance.com" in item.url and "followRoomList" in item.url), None)
        page = page or next((item for item in pages if "union.bytedance.com" in item.url), None) or context.new_page()
        if "union.bytedance.com" not in page.url or "followRoomList" not in page.url:
            print("正在用现有 Edge 打开跟播列表页...")
            page.goto(browser["page_url"], wait_until="domcontentloaded", timeout=60_000)
        else:
            print("已找到现有 Edge 里的跟播列表页。")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except PlaywrightTimeoutError:
            pass
        print("正在读取直播指标数据...")
        rooms = fetch_rooms(page, DATA_EXT_API)
        print("正在补全列表昵称...")
        merge_follow_rooms(rooms, fetch_rooms(page, FOLLOW_API))
        print("正在批量补全主播卡片信息...")
        merge_room_data(rooms, fetch_room_data(page, rooms))
        browser_client.close()
        return rooms


def export_csv(config: dict[str, Any], dirs: WorkDirs, output: Path | None = None) -> Path:
    output = output or (dirs.exports() / f"实时主播数据-{now_stamp()}-含预警标记.csv")
    browsers = config.get("browsers")
    if not isinstance(browsers, dict) or not browsers:
        raise ValueError("analysis_config.json 未配置 browsers。")

    rows: list[dict[str, Any]] = []
    for backend, browser in browsers.items():
        print(f"正在读取 {backend} 后台...")
        rooms = export_rooms(browser)
        start = len(rows) + 1
        rows.extend(room_to_row(room, start + index, backend, config) for index, room in enumerate(rooms))
        print(f"{backend} 在线直播间: {len(rooms)}")
    filled = backfill_identity(rows, dirs, output)
    if filled:
        print(f"已从历史数据回填主播昵称/抖音号: {filled} 个")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"已生成: {output}")
    print(f"行数: {len(rows)}")
    return output
