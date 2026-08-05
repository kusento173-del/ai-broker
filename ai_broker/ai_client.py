from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import requests

from .config import dimensions
from .rules import reason
from .utils import display_value, safe_print


PROMPT_GUIDE = """
五个维度的详细判断标准：

1. 运营维度
核心目标：判断主播是否能把进房用户，尤其是愿意消费的大哥，承接成停留、互动、关注和打赏。
必须观察：进房 3 秒钩子、标题和内容一致性、新进用户欢迎、公屏回应、礼物转化路径、高价值用户维护、节奏设计。
建议必须具体到话术或动作，例如点歌入口、音浪目标、榜单维护、欢迎话术和下一段内容预告。

2. 调试维度
核心目标：判断直播间技术状态是否影响用户停留、听感、互动和打赏冲动。
必须观察：人声音量、伴奏比例、爆音底噪、麦距、音画同步、卡顿黑屏、补光、网络、摄像头、声卡、耳返。
只在证据充分时判断真实直播间问题；若只是样本压缩导致不清晰，必须写采样限制。

3. 妆造维度
核心目标：判断主播上镜形象是否支撑人设、记忆点和大哥打赏意愿。
必须观察：底妆、眼妆、唇色、气色、发型、服装、人设匹配、配饰、背景、坐姿、表情和镜头自信度。
建议必须具体到补妆、发型固定、服装色系、标志物和背景调整。

4. 才艺维度
核心目标：判断才艺内容是否足够强、足够差异化，并能转化成互动和礼物理由。
必须观察：才艺完整度、高潮点、点歌投票、礼物触发节目、榜一专属内容、可循环节目单和标题匹配度。
建议必须给出节目结构，例如欢迎新进、唱副歌、点歌投票、感谢礼物、下一首预告。

5. 声乐维度
核心目标：判断主播声音表现是否能支撑听歌停留、情绪价值和点歌打赏。
必须观察：音准、节奏、咬字、气息、尾音、音色、情绪、伴奏比例和麦距。
建议必须能当场执行，例如换稳定曲目、降 Key、收短尾音、调整人声伴奏比例、唱后接关注和点歌话术。
""".strip()


def data_url(path: Path, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def analysis_prompt(row: dict[str, str], config: dict[str, Any]) -> str:
    capture = config.get("capture", {})
    capture_seconds = capture.get("seconds", "本次")
    dim_names = dimensions(config)
    sample_note = {
        "视频分析抽帧fps": capture.get("fps"),
        "录制视频宽度": capture.get("video_width"),
        "保存视频帧率": capture.get("video_output_fps"),
        "视频压缩CRF": capture.get("video_crf"),
        "音频码率": capture.get("audio_bitrate"),
        "录制时长秒": capture.get("seconds"),
    }
    meta = {
        "后台": display_value(row, "后台"),
        "主播昵称": display_value(row, "主播昵称"),
        "抖音号/短ID": display_value(row, "抖音号/短ID"),
        "主播ID": display_value(row, "主播ID"),
        "对应运营": display_value(row, "经纪人"),
        "直播间ID": display_value(row, "直播间ID"),
        "直播标题": display_value(row, "直播标题"),
        "开播时长": display_value(row, "开播时长"),
        "累计观众": display_value(row, "累计观众"),
        "音浪/流水": display_value(row, "音浪/流水"),
        "当前人气": display_value(row, "当前人气"),
    }
    return f"""
你是娱播直播运营质检专家。当前数据来自主播所属后台，后台名称已包含在实时数据中。公司收入核心来自吸引高价值付费用户和大哥打赏，请基于接下来 {capture_seconds} 秒直播视频和音频，结合主播实时数据，分析这个预警主播为什么“{reason(config, prompt_style=True)}”，并给出详细、准确、能当场执行的改进动作。

分析必须围绕直播转化链路：进房吸引、3秒停留、互动承接、关注沉淀、礼物破冰、大哥维护、音浪提升。
本次样本时长为 {capture_seconds} 秒。若样本达到 45 秒以上，必须观察前段/中段/后段节奏变化，不要只依据单一截图或单一句话下结论。

重要采样说明：
{json.dumps(sample_note, ensure_ascii=False, indent=2)}

你看到的视频和音频是压缩、抽帧、降码率后的分析样本。默认把低分辨率、低帧率、压缩噪点、码率不足、声音单薄视为“本次分析素材问题”，不要直接归因为主播直播间画质差、音质差、推流差或设备差。只有当问题不依赖素材清晰度也能明确观察或听到时，才能判断为直播间问题；证据不充分时必须写“受采样压缩影响，需看原始直播流确认”。

主播实时数据：
{json.dumps(meta, ensure_ascii=False, indent=2)}

请严格输出 JSON，不要输出 Markdown。JSON 顶层必须只有这 {len(dim_names)} 个 key：{"、".join(dim_names)}。
每个维度都返回这些字段：
- 维度结论：1 条，120 字以内，概括本维度核心问题和它对场观/留存/音浪的影响
- 证据摘要：3 条，每条 110 字以内，标明证据来自画面、声音、直播间数据、前中后段节奏或无法判断
- 问题诊断：3 条，每条 120 字以内，说明阻碍曝光、场观、停留、互动、关注或音浪的具体原因
- 转化影响：2 条，每条 110 字以内，说明如何影响大哥停留、礼物破冰、客单、关注或复访
- 优化建议：4 条，每条 130 字以内，具体到话术、动作、参数、机位、妆造、节目段落或大哥维护方式
- 10分钟内立刻执行：3 条，每条 110 字以内，必须是主播或运营现在就能做的动作
- 下次开播前准备：2-3 条，每条 110 字以内，适合复盘后准备
- 优先级：高/中/低
- 摘要消息：650-900 字中文，必须包含主播昵称、抖音号/短ID、对应运营；至少点出本维度 4 个具体动作；如果接口未返回昵称或抖音号，要如实写“接口未返回”

禁止空泛套话，建议要比“加强互动、优化画面”更具体。无法充分判断的维度要写清原因，并给出低风险检查动作。

{PROMPT_GUIDE}
""".strip()


def build_payload(row: dict[str, str], media: dict[str, str], config: dict[str, Any], include_audio: bool = True) -> dict[str, Any]:
    ark = config["ark"]
    content: list[dict[str, Any]] = [
        {"type": "video_url", "video_url": {"url": data_url(Path(media["video"]), "video/mp4"), "fps": int(config["capture"]["fps"])}}
    ]
    if include_audio and Path(media["audio"]).exists():
        content.append({"type": "input_audio", "input_audio": {"data": base64.b64encode(Path(media["audio"]).read_bytes()).decode("ascii"), "format": "m4a"}})
    content.append({"type": "text", "text": analysis_prompt(row, config)})
    payload: dict[str, Any] = {
        "model": ark["model"],
        "messages": [{"role": "user", "content": content}],
        "temperature": ark["temperature"],
        "max_tokens": ark["max_tokens"],
    }
    if ark.get("reasoning", {}).get("enabled"):
        payload["reasoning"] = {"effort": ark["reasoning"].get("effort", "medium")}
    return payload


def post_ark(payload: dict[str, Any], config: dict[str, Any]) -> requests.Response:
    ark = config["ark"]
    api_key = os.environ.get(ark["api_key_env"])
    if not api_key:
        raise RuntimeError(f"请先设置环境变量 {ark['api_key_env']}。")
    return requests.post(
        ark["base_url"],
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=240,
    )


def call_ark(payload: dict[str, Any], config: dict[str, Any]) -> str:
    response = post_ark(payload, config)
    if not response.ok and response.status_code == 400 and "reasoning" in payload:
        retry_payload = dict(payload)
        retry_payload.pop("reasoning", None)
        response = post_ark(retry_payload, config)
    if not response.ok:
        raise RuntimeError(f"Ark API failed HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()["choices"][0]["message"]["content"]


def retryable(exc: Exception) -> bool:
    text = str(exc)
    return any(mark in text for mark in ["429", "RequestBurstTooFast", "SetLimitExceeded", "Read timed out", "ConnectionResetError", "Max retries exceeded"])


def call_with_retries(payload: dict[str, Any], config: dict[str, Any], label: str) -> str:
    for attempt, delay in enumerate([0, 20, 45, 90], start=1):
        if delay:
            time.sleep(delay)
        try:
            return call_ark(payload, config)
        except RuntimeError as exc:
            if attempt == 4 or not retryable(exc):
                raise
            safe_print(f"{label} Ark 限流/超时，准备重试第 {attempt + 1} 次: {exc}")
    raise RuntimeError("Ark retry loop exited unexpectedly.")


def parse_ai_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise
        return json.loads(match.group(0))
