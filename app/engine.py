"""yt-dlp 引擎封装：依赖探测、元数据解析、下载、引擎更新、连通性测试。

设计要点：
1. 所有参数以 list 形式传给 Popen，不经 shell，避免引号与中文路径问题。
2. 一律加 --ignore-config，保证 GUI 行为只由本程序决定（不受 exe 同目录 yt-dlp.conf 干扰）。
3. 解析走 -J（结构化 JSON），进度走 --progress-template（机器可读行），不解析文本表格。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from .config import app_dir, resolve_proxy

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PROGRESS_TEMPLATE = (
    "download:PROG|%(progress.status)s|%(progress.downloaded_bytes)s|"
    "%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|"
    "%(progress.speed)s|%(progress.eta)s|%(progress.fragment_index)s|"
    "%(progress.fragment_count)s|%(info.format_id)s"
)
POSTPROCESS_TEMPLATE = "postprocess:PP|%(progress.status)s|%(progress.postprocessor)s"

RELEASES_API = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
CONNECT_TEST_URL = "https://www.youtube.com/generate_204"


def _popen_kwargs() -> dict:
    return {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}


class EngineError(Exception):
    def __init__(self, message: str, hint: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint


# --------------------------------------------------------------------------- #
# 依赖探测
# --------------------------------------------------------------------------- #
@dataclass
class Deps:
    ytdlp: str = ""
    ytdlp_version: str = ""
    ffmpeg: str = ""
    ffmpeg_version: str = ""
    deno: str = ""
    deno_version: str = ""
    cache: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.ytdlp)


def find_ytdlp(cfg: dict) -> str:
    candidates = []
    custom = (cfg.get("ytdlp_path") or "").strip().strip('"')
    if custom:
        candidates.append(custom)
    candidates.append(os.path.join(app_dir(), "yt-dlp.exe"))
    which = shutil.which("yt-dlp")
    if which:
        candidates.append(which)
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def find_ffmpeg(cfg: dict) -> str:
    value = (cfg.get("ffmpeg_dir") or "").strip().strip('"')
    if value:
        if os.path.isdir(value):
            exe = os.path.join(value, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if os.path.isfile(exe):
                return exe
        elif os.path.isfile(value):
            return value
    return shutil.which("ffmpeg") or ""


def find_deno(cfg: dict) -> str:
    value = (cfg.get("deno_path") or "").strip().strip('"')
    if value:
        if os.path.isdir(value):
            exe = os.path.join(value, "deno.exe" if os.name == "nt" else "deno")
            if os.path.isfile(exe):
                return exe
        elif os.path.isfile(value):
            return value
    return shutil.which("deno") or ""


def _read_version(exe: str, args: tuple[str, ...] = ("--version",)) -> str:
    if not exe:
        return ""
    try:
        cp = subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            **_popen_kwargs(),
        )
        text = (cp.stdout or "") + (cp.stderr or "")
        first = text.strip().splitlines()[0] if text.strip() else ""
        match = re.search(r"ffmpeg version (\S+)", first)
        if match:
            return match.group(1)
        return first.strip()
    except Exception:
        return ""


def _file_stamp(path: str) -> list:
    try:
        stat = os.stat(path)
        return [stat.st_size, int(stat.st_mtime)]
    except OSError:
        return []


def _cached_version(path: str, cached: dict) -> Optional[str]:
    """路径 + 大小 + 修改时间都对得上，就直接用缓存版本号。"""
    if not path or not isinstance(cached, dict):
        return None
    if cached.get("path") != path:
        return None
    if cached.get("stamp") != _file_stamp(path):
        return None
    return cached.get("version") or None


def detect_deps(cfg: dict) -> Deps:
    """探测三个依赖。

    yt-dlp.exe 是 onefile 打包，单次 `--version` 要 2.3 秒（每次都要解包到临时目录），
    所以按「路径 + 大小 + mtime」缓存版本号，命中缓存就不起进程。
    """
    deps = Deps()
    deps.ytdlp = find_ytdlp(cfg)
    deps.ffmpeg = find_ffmpeg(cfg)
    deps.deno = find_deno(cfg)

    old_cache = cfg.get("deps_cache") or {}
    cache: dict = {}

    def resolve(name: str, path: str, args: tuple = ("--version",)) -> str:
        version = _cached_version(path, old_cache.get(name) or {})
        if version is None:
            version = _read_version(path, args) if path else ""
        cache[name] = {"path": path, "stamp": _file_stamp(path), "version": version}
        return version

    deps.ytdlp_version = resolve("ytdlp", deps.ytdlp)
    deps.ffmpeg_version = resolve("ffmpeg", deps.ffmpeg, ("-version",))
    deps.deno_version = resolve("deno", deps.deno)
    deps.cache = cache
    return deps


def split_extra_args(raw: str) -> list[str]:
    """把用户填的高级参数拆成 argv，兼容 Windows 反斜杠路径。"""
    if not raw or not raw.strip():
        return []
    try:
        parts = shlex.split(raw, posix=False)
    except ValueError:
        parts = raw.split()
    cleaned = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in "\"'":
            part = part[1:-1]
        if part:
            cleaned.append(part)
    return cleaned


# --------------------------------------------------------------------------- #
# 命令行拼装
# --------------------------------------------------------------------------- #
def base_args(cfg: dict, deps: Deps) -> list[str]:
    args = ["--ignore-config", "--no-colors", "--encoding", "utf-8", "--no-playlist"]

    deno_custom = (cfg.get("deno_path") or "").strip().strip('"')
    if deno_custom and os.path.isfile(deno_custom):
        args += ["--js-runtimes", f"deno:{deno_custom}"]
    elif deps.deno:
        args += ["--js-runtimes", "deno"]

    proxy = resolve_proxy(cfg)
    if proxy:
        args += ["--proxy", proxy]

    cookie_file = (cfg.get("cookies_file") or "").strip().strip('"')
    browser = (cfg.get("cookies_browser") or "").strip()
    if cookie_file and os.path.isfile(cookie_file):
        args += ["--cookies", cookie_file]
    elif browser:
        args += ["--cookies-from-browser", browser]

    ffmpeg_dir = (cfg.get("ffmpeg_dir") or "").strip().strip('"')
    if ffmpeg_dir:
        args += ["--ffmpeg-location", ffmpeg_dir]

    args += split_extra_args(cfg.get("extra_args") or "")
    return args


def normalize_url(raw: str) -> str:
    """清理链接：去空白/引号、抽 http(s)、YouTube 短链统一为 watch?v=ID。"""
    text = (raw or "").strip().strip('"').strip("'").strip()
    if not text:
        return ""
    match = re.search(r"https?://[^\s]+", text)
    if not match:
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
            return f"https://www.youtube.com/watch?v={text}"
        return text
    url = match.group(0)
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.netloc or "").lower()
        if host in ("youtu.be", "www.youtu.be"):
            vid = parsed.path.strip("/").split("/")[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        if "youtube.com" in host:
            query = urllib.parse.parse_qs(parsed.query)
            if "v" in query and query["v"]:
                return f"https://www.youtube.com/watch?v={query['v'][0]}"
    except Exception:
        pass
    return url


# --------------------------------------------------------------------------- #
# 格式模型
# --------------------------------------------------------------------------- #
_CODEC_NAMES = {
    "avc1": "H.264",
    "avc3": "H.264",
    "h264": "H.264",
    "vp09": "VP9",
    "vp9": "VP9",
    "av01": "AV1",
    "hev1": "H.265",
    "hvc1": "H.265",
    "mp4a": "AAC",
    "opus": "Opus",
}


def codec_name(codec: str) -> str:
    low = (codec or "").lower()
    if low in ("", "none"):
        return "—"
    for key, name in _CODEC_NAMES.items():
        if low.startswith(key):
            return name
    return (codec or "").split(".")[0].upper()


def human_size(num: Optional[float]) -> str:
    if not num or num <= 0:
        return "—"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    value = float(num)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    if idx == 0:
        return f"{value:.0f} {units[idx]}"
    return f"{value:.1f} {units[idx]}" if value < 100 else f"{value:.0f} {units[idx]}"


def human_duration(seconds: Optional[float]) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def estimate_size(fmt: Optional["Format"], duration: Optional[float]) -> tuple[Optional[int], bool]:
    """返回 (字节数, 是否为估算值)。

    有些格式（典型是 4K VP9 的 m3u8 流，如 625）没有 filesize，
    但 tbr（kbps）和视频时长是有的，可以按 码率 × 时长 推算。
    """
    if fmt is None:
        return None, False
    if fmt.filesize:
        return fmt.filesize, False
    if fmt.tbr and duration:
        return int(fmt.tbr * 1000 / 8 * duration), True
    return None, False


def size_text(fmt: Optional["Format"], duration: Optional[float]) -> str:
    """表格里显示的大小；估算值前面加 ≈。"""
    size, estimated = estimate_size(fmt, duration)
    if size is None:
        return "—"
    return ("≈ " if estimated else "") + human_size(size)


def human_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return "—"
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


@dataclass
class Format:
    format_id: str
    ext: str
    height: Optional[int]
    width: Optional[int]
    fps: Optional[float]
    vcodec: str
    acodec: str
    tbr: Optional[float]
    abr: Optional[float]
    filesize: Optional[int]
    proto: str
    note: str

    @property
    def is_video(self) -> bool:
        return self.vcodec not in ("", "none")

    @property
    def has_audio(self) -> bool:
        return self.acodec not in ("", "none")

    @property
    def is_audio_only(self) -> bool:
        return (not self.is_video) and self.has_audio

    @property
    def resolution_text(self) -> str:
        if self.is_video and self.height:
            if self.width:
                return f"{self.width}×{self.height}"
            return f"{self.height}p"
        if self.abr:
            return f"{self.abr:.0f} kbps"
        return "音频"

    @property
    def kind_text(self) -> str:
        if self.is_audio_only:
            return "纯音频"
        if self.has_audio:
            return "视频 + 音频"
        return "视频（无声）"

    @property
    def fps_text(self) -> str:
        if not self.fps:
            return "—"
        return f"{self.fps:.0f}"


def parse_formats(info: dict) -> list[Format]:
    formats: list[Format] = []
    for item in info.get("formats") or []:
        fid = str(item.get("format_id") or "")
        ext = str(item.get("ext") or "")
        note = str(item.get("format_note") or "")
        proto = str(item.get("protocol") or "")
        if not fid:
            continue
        if ext == "mhtml" or fid.startswith("sb") or "storyboard" in note.lower():
            continue
        if "storyboard" in proto.lower():
            continue
        size = item.get("filesize") or item.get("filesize_approx")
        formats.append(
            Format(
                format_id=fid,
                ext=ext,
                height=item.get("height"),
                width=item.get("width"),
                fps=item.get("fps"),
                vcodec=str(item.get("vcodec") or "none"),
                acodec=str(item.get("acodec") or "none"),
                tbr=item.get("tbr"),
                abr=item.get("abr"),
                filesize=int(size) if size else None,
                proto=proto,
                note=note,
            )
        )
    return formats


def video_formats(formats: list[Format], codec_pref: str = "auto") -> list[Format]:
    items = [f for f in formats if f.is_video]
    items.sort(
        key=lambda f: (
            f.height or 0,
            f.fps or 0,
            _codec_rank(f, codec_pref),
            f.tbr or 0,
        ),
        reverse=True,
    )
    return items


def _codec_rank(fmt: Format, codec_pref: str) -> int:
    """同一分辨率下，按编码偏好决定排序优先级。"""
    codec = (fmt.vcodec or "").lower()
    if codec_pref == "vp9":
        return 2 if codec.startswith(("vp9", "vp09")) else 0
    if codec_pref == "av1":
        return 2 if codec.startswith("av01") else 0
    # auto：与选择器里的 [ext=mp4] 偏好保持一致
    return 1 if fmt.ext == "mp4" else 0


def audio_formats(formats: list[Format]) -> list[Format]:
    items = [f for f in formats if f.is_audio_only]
    items.sort(key=lambda f: (f.abr or 0, f.tbr or 0), reverse=True)
    return items


def best_video(
    formats: list[Format], max_height: Optional[int], codec_pref: str = "auto"
) -> Optional[Format]:
    for fmt in video_formats(formats, codec_pref):
        if max_height is None or (fmt.height or 0) <= max_height:
            return fmt
    return None


DEFAULT_OUTPUT_TEMPLATE = "%(title)s.%(ext)s"

# 文件名里用的短编码名（不能用 H.264 这种带点的，会和扩展名混淆）
_CODEC_TAGS = {
    "avc1": "H264",
    "avc3": "H264",
    "h264": "H264",
    "vp09": "VP9",
    "vp9": "VP9",
    "av01": "AV1",
    "hev1": "H265",
    "hvc1": "H265",
}


def codec_tag(codec: str) -> str:
    low = (codec or "").lower()
    if low in ("", "none"):
        return "NA"
    for key, tag in _CODEC_TAGS.items():
        if low.startswith(key):
            return tag
    return (codec or "").split(".")[0].upper() or "NA"


def output_label(
    video: Optional[Format], audio: Optional[Format], audio_only: bool
) -> str:
    """文件名里的版本标签，点号分隔：2160p.VP9 / VP9.625 / audio。"""
    if audio_only:
        return "audio"
    if video is None:
        return "video"
    tag = codec_tag(video.vcodec)
    if video.height:
        return f"{video.height}p.{tag}"
    # 高度未知的 HLS 流退化为「编码.格式ID」
    return f"{tag}.{video.format_id}"


def output_template_for(
    cfg: dict,
    video: Optional[Format],
    audio: Optional[Format],
    audio_only: bool,
) -> str:
    """用户自定义过模板就照用，否则用「标题.版本标签.扩展名」。"""
    user = (cfg.get("output_template") or "").strip()
    if user and user != DEFAULT_OUTPUT_TEMPLATE:
        return user
    label = output_label(video, audio, audio_only)
    return f"%(title)s.{label}.%(ext)s"


def build_combo_selector(
    video: Optional[Format],
    audio: Optional[Format],
    audio_only: bool,
    audio_pref: str = "m4a",
) -> tuple[str, bool]:
    """视频行 + 音频行自由组合的选择器。

    规则（ADR-06）：音频片段必须是单值，回退只在最外层用 "/" 串联，
    否则 "/" 会把回退项拆散，出现「视频失败就只下音频」。
    """
    if audio_only:
        if audio is not None:
            return f"{audio.format_id}/ba/b", True
        return "ba/b", True

    if video is None:
        return "bv*+ba/b", False

    if video.has_audio:
        # 自带音频的合并流，再加一条音轨会变成双音轨
        return f"{video.format_id}/bv*+ba/b", False

    if audio is not None:
        return (
            f"{video.format_id}+{audio.format_id}/"
            f"{video.format_id}+ba/"
            f"{video.format_id}/bv*+ba/b",
            False,
        )
    return f"{video.format_id}+ba/{video.format_id}/bv*+ba/b", False


# ---------------------------------------------------------------------------
# 容器预测：逐行移植 yt-dlp 的 get_compatible_ext()
# （yt_dlp/utils/_utils.py，2026-11 版本）
# 早期我们按「容器族」简化，实测会错（VP9-in-mp4 + m4a 实际落 mp4 而非 mkv）。
# ---------------------------------------------------------------------------
_COMPATIBLE_CODECS = {
    "mp4": {"av1", "hevc", "avc1", "mp4a", "ac-4", "h264", "aacl", "ec-3"},
    "webm": {"av1", "vp9", "vp8", "opus", "vrbs", "vp9x", "vp8x"},
}
_COMPATIBLE_EXTS = (
    {"mp3", "mp4", "m4a", "m4p", "m4b", "m4r", "m4v", "ismv", "isma", "mov"},
    {"webm", "weba"},
)


def _sanitize_codec(codec: str) -> str:
    """'vp09.00.50.08' → 'vp9'；'av01.0.12M.08' → 'av1'；'mp4a.40.2' → 'mp4a'。"""
    return (codec or "").split(".")[0].replace("0", "").lower()


def predict_container(
    vcodec: str,
    acodec: str,
    vext: str,
    aext: str,
    preferences: Optional[list[str]] = None,
) -> str:
    """复刻 yt-dlp 的合并容器选择，保证界面预测与实际落盘一致。"""
    allow_mkv = not preferences or "mkv" in preferences

    vcodec_s = _sanitize_codec(vcodec)
    acodec_s = _sanitize_codec(acodec)

    # 1) 编码白名单：mp4 → webm → mkv
    for ext in preferences or ("mp4", "webm"):
        allowed = _COMPATIBLE_CODECS.get(ext, set())
        if ext == "mkv" or allowed.issuperset((vcodec_s, acodec_s)):
            return ext

    # 2) 兜底：按源扩展名是否同族
    for ext in preferences or [vext]:
        current = {ext, vext, aext}
        if ext == "mkv" or current == {ext} or any(
            group.issuperset(current) for group in _COMPATIBLE_EXTS
        ):
            return ext

    if allow_mkv:
        return "mkv"
    return preferences[-1] if preferences else "mkv"


def container_arg(cfg: dict) -> str:
    """返回 --merge-output-format 的值；空串表示交给 yt-dlp 自己判断。"""
    mode = (cfg.get("container") or "auto").lower()
    return mode if mode in ("mp4", "mkv") else ""


def container_hint(
    cfg: dict,
    video: Optional[Format],
    audio: Optional[Format],
    audio_only: bool,
) -> str:
    """预测最终容器（与 yt-dlp 的 get_compatible_ext 保持一致）。"""
    if audio_only:
        if (cfg.get("audio_mode") or "copy").lower() == "mp3":
            return "mp3"
        return audio.ext if audio is not None else "m4a"

    forced = container_arg(cfg)
    if forced:
        return predict_container(
            video.vcodec if video else "", audio.acodec if audio else "",
            video.ext if video else "mp4", audio.ext if audio else "m4a",
            [forced],
        )
    if video is None:
        return "mp4"
    if video.has_audio:
        return video.ext

    return predict_container(
        video.vcodec,
        audio.acodec if audio is not None else "opus",  # +ba 通常选 Opus
        video.ext,
        audio.ext if audio is not None else "webm",
    )


# 各容器能装什么（决定「尽可能全面」的边界）
#   mkv : 封面 + 元数据 + 章节 + 内嵌字幕（字幕保留 srt/ass 原格式）
#   mp4 : 封面 + 元数据 + 章节；字幕只能 mov_text（样式全丢）→ 改为外挂
#   webm: 元数据；封面/章节 ffmpeg 不认 → 跳过
#   mp3/m4a: 封面 + 元数据（音频无章节/字幕）
_EMBED_MATRIX = {
    "mkv": {"thumbnail": True, "chapters": True, "embed_subs": True},
    "mp4": {"thumbnail": True, "chapters": True, "embed_subs": False},
    "webm": {"thumbnail": False, "chapters": False, "embed_subs": False},
    "mp3": {"thumbnail": True, "chapters": False, "embed_subs": False},
    "m4a": {"thumbnail": True, "chapters": False, "embed_subs": False},
}


def enhance_plan(cfg: dict, container: str, audio_only: bool) -> dict:
    """按容器能力算出这次能嵌什么。"""
    plan = {
        "metadata": False,
        "chapters": False,
        "thumbnail": False,
        "subs": False,
        "embed_subs": False,
    }
    caps = _EMBED_MATRIX.get((container or "").lower(), {})
    plan["metadata"] = bool(cfg.get("embed_metadata", True))
    # 容器装不下的项，即使勾了也自动降级
    plan["chapters"] = bool(cfg.get("embed_chapters", True)) and bool(caps.get("chapters"))
    plan["thumbnail"] = bool(cfg.get("embed_thumbnail", True)) and bool(caps.get("thumbnail"))

    langs = (cfg.get("sub_langs") or "").strip()
    if not audio_only and cfg.get("embed_subs", False) and langs:
        plan["subs"] = True
        plan["embed_subs"] = bool(caps.get("embed_subs"))
    return plan


def enhance_args(cfg: dict, container: str, audio_only: bool) -> list[str]:
    plan = enhance_plan(cfg, container, audio_only)
    args: list[str] = []
    if plan["metadata"]:
        args += ["--embed-metadata"]
    if plan["chapters"]:
        args += ["--embed-chapters"]
    if plan["thumbnail"]:
        args += ["--embed-thumbnail"]
    if plan["subs"]:
        # 字幕接口经常 429，不加这个会让整条下载直接失败（视频一个字节都下不来）
        args += [
            "--ignore-errors",
            "--sleep-subtitles",
            "1",
            "--write-auto-subs",
            "--sub-langs",
            (cfg.get("sub_langs") or "zh-Hans,zh-Hant,en").strip(),
            "--convert-subs",
            "srt",
        ]
        # 内嵌时不要再加 --write-subs，否则 yt-dlp 会额外保留一份 .srt
        args += ["--embed-subs"] if plan["embed_subs"] else ["--write-subs"]
    return args


def enhance_text(cfg: dict, container: str, audio_only: bool) -> str:
    """摘要里显示的「封面+元数据+章节」。"""
    plan = enhance_plan(cfg, container, audio_only)
    bits = []
    if plan["thumbnail"]:
        bits.append("封面")
    if plan["metadata"]:
        bits.append("元数据")
    if plan["chapters"]:
        bits.append("章节")
    if plan["subs"]:
        bits.append("字幕内嵌" if plan["embed_subs"] else "字幕外挂")
    return "+".join(bits)


def probe_writable(out_dir: str) -> tuple[bool, str]:
    """用 0 字节探测文件确认目录真的可写（比 os.access 可靠，能发现只读共享盘）。"""
    if not out_dir:
        return False, "还没有选择保存目录"
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"目录不存在且无法创建：{exc}"
    probe = os.path.join(out_dir, ".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"目录不可写：{exc}"


def check_disk_space(out_dir: str, need_bytes: int, factor: float = 2.0) -> tuple[bool, str]:
    """剩余空间不足时返回 (False, 提示)。

    合并阶段要同时存在视频流 + 音频流 + 成品，所以按 need × factor 预留。
    估算值本身是近似值，factor 取 2.0 而不是 2.5，避免误报太频繁。
    """
    if not out_dir or not need_bytes:
        return True, ""
    try:
        usage = shutil.disk_usage(out_dir)
    except Exception:  # noqa: BLE001
        return True, ""
    required = int(need_bytes * factor)
    if usage.free >= required:
        return True, ""
    return False, (
        f"磁盘剩余 {human_size(usage.free)}，本次预计需要约 {human_size(required)}"
        f"（按下载大小的 {factor:.0f} 倍预留合并空间）"
    )


def filename_budget(out_dir: str) -> int:
    """按实际保存目录动态算 --trim-filenames。

    Windows 的 260 限制算的是绝对路径，且下载/合并期间会附加
    .f625.webm.part 这类临时后缀（约 20 字符），所以要预留。
    """
    base = os.path.abspath(out_dir or os.getcwd())
    budget = 240 - len(base) - 1 - 20
    return max(60, min(200, budget))


# --------------------------------------------------------------------------- #
# 错误翻译
# --------------------------------------------------------------------------- #
_ERROR_RULES: list[tuple[str, str, str]] = [
    (
        "sign in to confirm you're not a bot",
        "YouTube 要求验证身份",
        "通常是用得太频繁。可在设置里把 Cookie 改成 Chrome，或稍后再试。",
    ),
    (
        "http error 403",
        "服务器返回 403（拒绝访问）",
        "CDN 令牌过期或被限流。程序已自动重试；仍失败可带 Chrome Cookie 或更新引擎。",
    ),
    (
        "failed to decrypt with dpapi",
        "无法解密 Chrome 的 Cookie",
        "Chrome 新版启用了 App-Bound 加密。请完全退出 Chrome 后重试，或改用 cookies.txt 文件。",
    ),
    (
        "could not copy",
        "读不到浏览器的 Cookie 数据库",
        "请完全退出浏览器（含后台进程）后重试，或改用 cookies.txt 文件。",
    ),
    (
        "no supported javascript runtime",
        "缺少 JS 运行时",
        "请在设置里指定 deno 路径，或把 deno 加入系统 PATH。",
    ),
    (
        "ffmpeg",
        "缺少 ffmpeg 或调用失败",
        "合并音视频需要 ffmpeg。请在设置里指定 ffmpeg 所在目录。",
    ),
    (
        "video unavailable",
        "视频不可用",
        "可能已删除、有地区限制，或需要登录。",
    ),
    (
        "private video",
        "这是私享视频",
        "需要登录且账号有权访问，请配置 Cookie。",
    ),
    (
        "members-only",
        "会员专属视频",
        "需要带 Cookie 才能下载。",
    ),
    (
        "requested format is not available",
        "所选格式不可用",
        "格式 ID 会随视频变化。请重新点「解析」后再选。",
    ),
    (
        "unsupported url",
        "链接不受支持",
        "请确认是视频页面链接，而不是频道页或搜索页。",
    ),
    (
        "urlopen error",
        "网络连接失败",
        "检查代理是否可用：点状态栏的「测试连通」。",
    ),
    (
        "getaddrinfo failed",
        "域名解析失败",
        "检查网络或代理设置（状态栏「测试连通」）。",
    ),
    (
        "timed out",
        "请求超时",
        "网络或代理太慢，可稍后重试。",
    ),
]


def translate_error(text: str) -> EngineError:
    low = (text or "").lower()
    for needle, message, hint in _ERROR_RULES:
        if needle in low:
            return EngineError(message, hint)
    tail = ""
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.upper().startswith("ERROR"):
            tail = line
            break
    if not tail:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        tail = lines[-1] if lines else "未知错误"
    return EngineError("下载失败", tail[:300])


# --------------------------------------------------------------------------- #
# 解析（-J）
# --------------------------------------------------------------------------- #
def probe(url: str, cfg: dict, deps: Deps, timeout: int = 180) -> dict:
    if not deps.ytdlp:
        raise EngineError("找不到 yt-dlp.exe", "请在设置里指定引擎路径，或把 yt-dlp.exe 放回程序目录。")
    cmd = [deps.ytdlp, *base_args(cfg, deps), "-J", "--no-warnings", url]
    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **_popen_kwargs(),
        )
    except subprocess.TimeoutExpired:
        raise EngineError("解析超时", "网络或代理太慢，试试状态栏的「测试连通」。")
    except FileNotFoundError:
        raise EngineError("引擎无法启动", "yt-dlp.exe 路径无效，请在设置里重新指定。")

    if cp.returncode != 0:
        raise translate_error((cp.stderr or "") + "\n" + (cp.stdout or ""))

    try:
        info = json.loads(cp.stdout)
    except Exception:
        raise EngineError(
            "解析结果无法识别",
            "yt-dlp 输出的不是合法 JSON，可能是引擎版本过旧或参数被改动。可尝试更新引擎。",
        )

    if isinstance(info, dict) and info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if entries:
            info = entries[0]
        else:
            raise EngineError("这是空播放列表", "当前版本只支持单个视频链接。")
    if not isinstance(info, dict):
        raise EngineError("解析结果格式异常", "请重试，或更新引擎后再试。")
    return info


# --------------------------------------------------------------------------- #
# 下载
# --------------------------------------------------------------------------- #
@dataclass
class Progress:
    status: str = ""
    downloaded: Optional[float] = None
    total: Optional[float] = None
    speed: Optional[float] = None
    eta: Optional[float] = None
    frag_index: Optional[int] = None
    frag_count: Optional[int] = None
    postprocessor: str = ""
    format_id: str = ""


def parse_progress_line(line: str) -> Optional[Progress]:
    if line.startswith("PROG|"):
        parts = line.split("|")
        if len(parts) < 9:
            return None

        def num(idx: int, cast=float):
            try:
                return cast(parts[idx])
            except (TypeError, ValueError):
                return None

        total = num(3) or num(4)
        fmt_id = ""
        if len(parts) > 9:
            raw_id = parts[9].strip()
            fmt_id = "" if raw_id in ("", "NA", "None") else raw_id
        return Progress(
            status=parts[1],
            downloaded=num(2),
            total=total,
            speed=num(5),
            eta=num(6),
            frag_index=num(7, int),
            frag_count=num(8, int),
            format_id=fmt_id,
        )
    if line.startswith("PP|"):
        parts = line.split("|")
        if len(parts) >= 3:
            return Progress(status=parts[1], postprocessor=parts[2])
    return None


def parse_filepath_line(line: str) -> Optional[str]:
    """解析 --print after_move:FILEPATH|... 的输出行。"""
    prefix = "FILEPATH|"
    if line.startswith(prefix):
        value = line[len(prefix) :].strip().strip('"')
        return value or None
    return None


class Downloader:
    """一次下载任务。线程内使用，不跨线程共享。"""

    def __init__(
        self,
        cfg: dict,
        deps: Deps,
        url: str,
        selector: str,
        audio_only: bool = False,
        output_dir: str = "",
        container: str = "",
        template: str = "",
        force: bool = False,
        expected_container: str = "",
    ):
        self.cfg = cfg
        self.deps = deps
        self.url = url
        self.selector = selector
        self.audio_only = audio_only
        self.output_dir = output_dir or cfg.get("download_dir") or ""
        self.container = container
        self.template = template or cfg.get("output_template") or DEFAULT_OUTPUT_TEMPLATE
        self.force = force
        self.expected_container = expected_container
        self.proc: Optional[subprocess.Popen] = None

    def command(self) -> list[str]:
        cfg, deps = self.cfg, self.deps
        args = [deps.ytdlp, *base_args(cfg, deps)]
        args += [
            "--newline",
            "--no-quiet",
            "--progress-template",
            PROGRESS_TEMPLATE,
            "--progress-template",
            POSTPROCESS_TEMPLATE,
            # 后处理完成后打印真实路径（配合 --no-quiet 保住进度行）
            "--print",
            "after_move:FILEPATH|%(filepath)s",
            # Windows 260 字符路径上限：按实际保存目录动态计算
            "--trim-filenames",
            str(filename_budget(self.output_dir)),
        ]

        retries = "infinite" if cfg.get("infinite_retry", True) else "10"
        args += ["--retries", retries, "--fragment-retries", retries]
        args += ["--skip-unavailable-fragments"]
        if self.force:
            args += ["--force-overwrites"]

        try:
            frags = int(cfg.get("concurrent_fragments") or 8)
        except (TypeError, ValueError):
            frags = 8
        args += ["-N", str(max(1, min(16, frags)))]

        if self.output_dir:
            args += ["-P", self.output_dir]
        args += ["-o", self.template]

        if self.audio_only:
            args += ["-f", self.selector]
            if (cfg.get("audio_mode") or "copy").lower() == "mp3":
                args += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
        else:
            args += ["-f", self.selector]
            if self.container:
                args += ["--merge-output-format", self.container]

        # 按容器能力自动嵌入（封面/元数据/章节/字幕）
        expected = self.expected_container or ("mp3" if self.audio_only else "mp4")
        args += enhance_args(cfg, expected, self.audio_only)

        args.append(self.url)
        return args

    def start(self) -> None:
        if not self.deps.ytdlp:
            raise EngineError("找不到 yt-dlp.exe", "请在设置里指定引擎路径。")
        if self.output_dir and not os.path.isdir(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
        self.proc = subprocess.Popen(
            self.command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_popen_kwargs(),
        )

    def lines(self):
        if not self.proc or not self.proc.stdout:
            return
        for raw in self.proc.stdout:
            yield raw.rstrip("\r\n")

    def wait(self) -> int:
        if not self.proc:
            return -1
        return self.proc.wait()

    def stop(self) -> None:
        proc = self.proc
        if not proc or proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    **_popen_kwargs(),
                )
            else:
                proc.terminate()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# 引擎更新 / 版本检查 / 连通性
# --------------------------------------------------------------------------- #
def _version_tuple(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def is_newer(latest: str, current: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def _open_with_proxy(cfg: dict, url: str, timeout: int = 10):
    proxy = resolve_proxy(cfg)
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": "yt-dlp-gui/1.0"})
    return opener.open(request, timeout=timeout)


def check_latest_version(cfg: dict, timeout: int = 10) -> str:
    with _open_with_proxy(cfg, RELEASES_API, timeout) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    tag = str(data.get("tag_name") or "").strip()
    return tag.lstrip("vV")


def test_connectivity(cfg: dict, timeout: int = 8) -> tuple[bool, str]:
    import time

    proxy = resolve_proxy(cfg)
    started = time.time()
    try:
        with _open_with_proxy(cfg, CONNECT_TEST_URL, timeout) as resp:
            resp.read(64)
        elapsed = time.time() - started
        route = proxy or "直连"
        return True, f"连通正常（{route}，{elapsed:.1f}s）"
    except Exception as exc:
        route = proxy or "直连"
        return False, f"连不上（{route}）：{exc.__class__.__name__}"


def update_engine(cfg: dict, deps: Deps, timeout: int = 300) -> tuple[int, str]:
    """更新引擎；失败自动回滚，避免把 yt-dlp.exe 更新成砖。

    yt-dlp -U 是就地替换自身，中途断网/被杀软拦截会留下半个文件。
    """
    if not deps.ytdlp:
        return -1, "找不到 yt-dlp.exe"

    exe = deps.ytdlp
    backup = exe + ".bak"
    try:
        shutil.copy2(exe, backup)
    except Exception as exc:  # noqa: BLE001
        return -1, f"无法备份现有引擎（可能被占用）：{exc}"

    cmd = [exe, "-U", "--no-colors", "--encoding", "utf-8", "--ignore-config"]
    proxy = resolve_proxy(cfg)
    if proxy:
        cmd += ["--proxy", proxy]

    def rollback(reason: str) -> tuple[int, str]:
        try:
            shutil.copy2(backup, exe)
            return -1, f"{reason}\n\n已自动回滚到更新前的版本。"
        except Exception as exc:  # noqa: BLE001
            return -1, f"{reason}\n\n回滚也失败了：{exc}\n备份在 {backup}"

    try:
        cp = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            **_popen_kwargs(),
        )
        output = ((cp.stdout or "") + (cp.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return rollback("更新超时（网络太慢或代理不通）")
    except Exception as exc:  # noqa: BLE001
        return rollback(f"更新失败：{exc}")

    # 探活：能正常输出 --version 才算更新成功
    version = _read_version(exe)
    if not version:
        return rollback("更新后引擎无法运行（可能被杀软拦截或文件损坏）")

    try:
        os.remove(backup)
    except OSError:
        pass
    return cp.returncode, f"{output or '（引擎没有输出）'}\n\n当前版本：{version}"
