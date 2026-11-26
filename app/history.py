"""下载历史。

去重键 = video_id + 视频格式 + 音频格式 + 容器。
注意：**不能用 yt-dlp 的 --download-archive**，它按视频 ID 记录，
同视频换画质也会被整体跳过，与「一个视频下多个版本」的需求冲突。
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

from .config import app_dir

HISTORY_PATH = os.environ.get("YTDLP_GUI_HISTORY") or os.path.join(app_dir(), "history.json")
MAX_ENTRIES = 1000


def make_key(
    video_id: str, video_format: str, audio_format: str, container: str
) -> str:
    return "|".join(
        [(video_id or "").strip(), video_format or "", audio_format or "", container or ""]
    )


def load() -> list[dict]:
    if not os.path.isfile(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def save(entries: list[dict]) -> None:
    try:
        tmp = HISTORY_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries[-MAX_ENTRIES:], fh, ensure_ascii=False, indent=1)
        os.replace(tmp, HISTORY_PATH)
    except Exception:  # noqa: BLE001
        pass


def find(key: str) -> Optional[dict]:
    for entry in reversed(load()):
        if entry.get("key") == key:
            return entry
    return None


def record(
    key: str,
    video_id: str,
    title: str,
    video_format: str,
    audio_format: str,
    container: str,
    path: str,
    url: str = "",
) -> None:
    entries = [e for e in load() if e.get("key") != key]
    entries.append(
        {
            "key": key,
            "video_id": video_id,
            "title": title,
            "video_format": video_format,
            "audio_format": audio_format,
            "container": container,
            "path": path,
            "url": url,
            "time": time.strftime("%Y-%m-%d %H:%M"),
        }
    )
    save(entries)


def remove(key: str) -> None:
    save([e for e in load() if e.get("key") != key])


def clear() -> None:
    save([])


def combo_text(entry: dict) -> str:
    video = entry.get("video_format") or ""
    audio = entry.get("audio_format") or ""
    container = entry.get("container") or ""
    if not video:
        base = f"仅音频 {audio}".strip()
    elif audio:
        base = f"{video} + {audio}"
    else:
        base = video
    return f"{base} → {container}" if container else base
