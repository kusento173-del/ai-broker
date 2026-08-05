from __future__ import annotations

import subprocess
from typing import Any

import imageio_ffmpeg

from .paths import WorkDirs, backend_slug, now_stamp, safe_name
from .utils import row_value


def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed with code {result.returncode}:\n{result.stderr}")


def capture_clip(row: dict[str, str], config: dict[str, Any], dirs: WorkDirs) -> dict[str, str]:
    url = row_value(row, "FLV拉流地址").strip()
    if not url:
        raise ValueError("该主播没有 FLV 拉流地址，无法录制。")

    capture = config["capture"]
    seconds = int(capture["seconds"])
    width = int(capture["video_width"])
    output_fps = int(capture.get("video_output_fps", 12))
    video_crf = str(capture.get("video_crf", 30))
    audio_bitrate = str(capture.get("audio_bitrate", "64k"))
    screenshot_width = int(capture.get("screenshot_width", width))
    screenshot_quality = str(capture.get("screenshot_quality", 2))

    prefix = f"{backend_slug(row_value(row, '后台', '新心'))}_{safe_name(row_value(row, '主播ID'))}_{safe_name(row_value(row, '直播间ID'))}_{now_stamp()}"
    video = dirs.clips() / f"{prefix}.mp4"
    audio = dirs.clips() / f"{prefix}.m4a"
    screenshot = dirs.clips() / f"{prefix}.jpg"
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    run_ffmpeg([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-rw_timeout", "15000000",
        "-i", url, "-t", str(seconds), "-vf", f"scale={width}:-2,fps={output_fps}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", video_crf, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", audio_bitrate, "-movflags", "+faststart", str(video),
    ])
    run_ffmpeg([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vn", "-c:a", "aac", "-b:a", audio_bitrate, str(audio),
    ])
    try:
        run_ffmpeg([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-rw_timeout", "15000000",
            "-i", url, "-frames:v", "1", "-vf", f"scale={screenshot_width}:-2",
            "-q:v", screenshot_quality, str(screenshot),
        ])
    except RuntimeError:
        second = max(1, min(seconds - 1, seconds // 2))
        run_ffmpeg([
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(second), "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={screenshot_width}:-2", "-q:v", screenshot_quality, str(screenshot),
        ])

    return {"video": str(video), "audio": str(audio), "screenshot": str(screenshot)}
