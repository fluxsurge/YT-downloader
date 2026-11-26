"""配置读写与系统环境探测。"""
from __future__ import annotations

import json
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_dir() -> str:
    """打包成 exe 后返回 exe 所在目录，源码运行返回项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return PROJECT_DIR


# 注意：必须在 app_dir() 之后计算，否则打包后配置会落到 _internal 里
CONFIG_PATH = os.environ.get("YTDLP_GUI_CONFIG") or os.path.join(app_dir(), "config.json")

DEFAULTS = {
    "ytdlp_path": "",
    "ffmpeg_dir": "",
    "deno_path": "",
    "proxy_mode": "auto",          # auto | manual | off
    "proxy_url": "",
    "cookies_browser": "",         # "" | chrome | edge | firefox | brave
    "cookies_file": "",            # Netscape 格式 cookies.txt
    "concurrent_fragments": 8,
    "infinite_retry": True,
    "download_dir": "",
    "output_template": "%(title)s.%(ext)s",
    "audio_pref": "m4a",           # m4a | opus | best
    "audio_mode": "copy",          # copy=直出原始流 | mp3=转码 mp3 320k
    "embed_thumbnail": True,       # 嵌入封面
    "embed_metadata": True,        # 嵌入标题/作者等元数据
    "embed_chapters": True,        # 嵌入章节
    "embed_subs": False,           # 下载字幕（默认关，字幕接口容易限流）
    "sub_langs": "zh-Hans,zh-Hant,en",        # 字幕语言（yt-dlp 语法，逗号分隔，支持正则）
    "codec_pref": "auto",          # auto | vp9 | av1
    "container": "auto",           # auto | mp4 | mkv
    "extra_args": "",
    "last_quality": "best",
    "check_update": True,
    "window_geometry": "",
    "deps_cache": {},              # 依赖版本缓存（避免每次启动都跑 yt-dlp --version）
}


def _default_download_dir() -> str:
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    return downloads if os.path.isdir(downloads) else home


def _detect_system_proxy() -> str:
    """读取 Windows 系统代理；失败则回落到环境变量。"""
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
            )
            try:
                enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")
                server, _ = winreg.QueryValueEx(key, "ProxyServer")
            finally:
                winreg.CloseKey(key)
            if enabled and server:
                server = str(server).strip()
                if "=" in server:
                    parts = {}
                    for chunk in server.split(";"):
                        if "=" in chunk:
                            k, v = chunk.split("=", 1)
                            parts[k.strip().lower()] = v.strip()
                    server = parts.get("http") or parts.get("https") or ""
                if server and "://" not in server:
                    server = "http://" + server
                return server
        except Exception:
            pass
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(name, "").strip()
        if value:
            if "://" not in value:
                value = "http://" + value
            return value
    return ""


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg["download_dir"] = _default_download_dir()
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            if isinstance(saved, dict):
                for key in DEFAULTS:
                    if key in saved:
                        cfg[key] = saved[key]
        except Exception:
            pass
    if not cfg.get("download_dir"):
        cfg["download_dir"] = _default_download_dir()
    return cfg


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def resolve_proxy(cfg: dict) -> str:
    mode = cfg.get("proxy_mode", "auto")
    if mode == "off":
        return ""
    if mode == "manual":
        value = (cfg.get("proxy_url") or "").strip()
        if value and "://" not in value:
            value = "http://" + value
        return value
    return _detect_system_proxy()


def app_dir() -> str:
    """打包成 exe 后返回 exe 所在目录，源码运行返回项目根目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return PROJECT_DIR
