"""核心算法单元测试。

这些逻辑没有 UI 依赖，改动前后都应跑一遍：
    .venv\\Scripts\\python.exe -m pytest tests -q
"""
import os

import pytest

from app import engine


def fmt(
    format_id="137",
    ext="mp4",
    height=1080,
    vcodec="avc1.640028",
    acodec="none",
    tbr=3000.0,
    abr=None,
    filesize=None,
    fps=30.0,
    proto="https",
):
    return engine.Format(
        format_id=format_id,
        ext=ext,
        height=height,
        width=1920,
        fps=fps,
        vcodec=vcodec,
        acodec=acodec,
        tbr=tbr,
        abr=abr,
        filesize=filesize,
        proto=proto,
        note="",
    )


# --------------------------------------------------------------------------
# 容器预测：8 组，全部来自真下载实测（见 HANDOFF ADR-04 / ADR-16）
# --------------------------------------------------------------------------
CONTAINER_CASES = [
    # (vcodec, acodec, vext, aext, 期望)
    ("avc1.640028", "mp4a.40.2", "mp4", "m4a", "mp4"),
    ("av01.0.08M.08", "mp4a.40.2", "mp4", "m4a", "mp4"),
    ("vp09.00.50.08", "mp4a.40.2", "mp4", "m4a", "mp4"),  # 625：靠扩展名兜底
    ("vp09.00.50.08", "opus", "webm", "webm", "webm"),
    ("av01.0.08M.08", "opus", "mp4", "webm", "webm"),
    ("vp09.00.50.08", "mp4a.40.2", "webm", "m4a", "mkv"),
    ("avc1.640028", "opus", "mp4", "webm", "mkv"),
    ("vp09.00.50.08", "opus", "mp4", "webm", "webm"),
]


@pytest.mark.parametrize("vcodec,acodec,vext,aext,expected", CONTAINER_CASES)
def test_predict_container(vcodec, acodec, vext, aext, expected):
    assert engine.predict_container(vcodec, acodec, vext, aext) == expected


@pytest.mark.parametrize("forced", ["mp4", "mkv"])
def test_predict_container_forced(forced):
    """强制容器时永远听用户的。"""
    got = engine.predict_container("vp09.00.50.08", "opus", "webm", "webm", [forced])
    assert got == forced


def test_predict_container_unknown_audio_defaults_to_opus():
    """音频未指定时按 +ba 通常选 Opus 处理。"""
    assert engine.predict_container("avc1.640028", "opus", "mp4", "webm") == "mkv"


def test_container_hint_audio_only():
    cfg = {"audio_mode": "copy"}
    assert engine.container_hint(cfg, None, fmt(ext="m4a", vcodec="none", acodec="mp4a.40.2"), True) == "m4a"
    cfg["audio_mode"] = "mp3"
    assert engine.container_hint(cfg, None, fmt(ext="m4a", vcodec="none", acodec="mp4a.40.2"), True) == "mp3"


def test_container_hint_video_with_audio_keeps_ext():
    merged = fmt(format_id="18", ext="mp4", height=360, vcodec="avc1", acodec="mp4a")
    assert engine.container_hint({}, merged, None, False) == "mp4"


# --------------------------------------------------------------------------
# 组合选择器
# --------------------------------------------------------------------------
def test_selector_video_plus_audio():
    video = fmt("137", "mp4", 1080, "avc1")
    audio = fmt("140", "m4a", None, "none", "mp4a.40.2", abr=130.0)
    selector, audio_only = engine.build_combo_selector(video, audio, False, "m4a")
    assert audio_only is False
    assert selector.startswith("137+140/137+ba/137/bv*+ba/b")


def test_selector_audio_only():
    audio = fmt("251", "webm", None, "none", "opus", abr=129.0)
    selector, audio_only = engine.build_combo_selector(None, audio, True, "m4a")
    assert audio_only is True
    assert selector.startswith("251/ba/b")


def test_selector_never_splits_audio_fallback():
    """audio 片段必须是单值，否则 / 会把回退链拆散（ADR-06）。"""
    video = fmt("137", "mp4", 1080, "avc1")
    audio = fmt("251", "webm", None, "none", "opus", abr=129.0)
    selector, _ = engine.build_combo_selector(video, audio, False, "opus")
    first = selector.split("/")[0]
    assert first.count("+") == 1


# --------------------------------------------------------------------------
# 文件名预算
# --------------------------------------------------------------------------
def test_filename_budget_bounds():
    assert engine.filename_budget(r"C:\Users\x\Downloads") <= 200
    deep = r"C:\Users\someone\Videos\archive\2026\long\deep\folder\structure"
    assert 60 <= engine.filename_budget(deep) < engine.filename_budget(r"C:\a")


def test_filename_budget_never_below_floor():
    assert engine.filename_budget("C:\\" + "x" * 300) >= 60


# --------------------------------------------------------------------------
# 附加项能力矩阵
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "container,thumbnail,chapters,embed_subs",
    [
        ("mkv", True, True, True),
        ("mp4", True, True, False),
        ("webm", False, False, False),
        ("m4a", True, False, False),
        ("mp3", True, False, False),
    ],
)
def test_enhance_caps(container, thumbnail, chapters, embed_subs):
    cfg = {"embed_thumbnail": True, "embed_metadata": True,
           "embed_chapters": True, "embed_subs": True, "sub_langs": "zh-Hans,en"}
    plan = engine.enhance_plan(cfg, container, False)
    assert plan["metadata"] is True
    assert plan["thumbnail"] is thumbnail
    assert plan["chapters"] is chapters
    assert plan["embed_subs"] is embed_subs


def test_enhance_respects_user_toggles():
    cfg = {"embed_thumbnail": False, "embed_metadata": False,
           "embed_chapters": False, "embed_subs": False, "sub_langs": "en"}
    plan = engine.enhance_plan(cfg, "mkv", False)
    assert not any([plan["thumbnail"], plan["metadata"], plan["chapters"], plan["subs"]])


def test_enhance_no_subs_for_audio_only():
    cfg = {"embed_thumbnail": True, "embed_metadata": True,
           "embed_chapters": True, "embed_subs": True, "sub_langs": "en"}
    plan = engine.enhance_plan(cfg, "m4a", True)
    assert plan["subs"] is False


def test_enhance_args_embed_vs_write_subs():
    """内嵌时不能同时给 --write-subs，否则会多留一份 .srt（ADR-19）。"""
    cfg = {"embed_thumbnail": False, "embed_metadata": False,
           "embed_chapters": False, "embed_subs": True, "sub_langs": "en"}
    mkv_args = engine.enhance_args(cfg, "mkv", False)
    mp4_args = engine.enhance_args(cfg, "mp4", False)
    assert "--embed-subs" in mkv_args and "--write-subs" not in mkv_args
    assert "--write-subs" in mp4_args and "--embed-subs" not in mp4_args
    assert "--ignore-errors" in mkv_args


# --------------------------------------------------------------------------
# 输出模板
# --------------------------------------------------------------------------
def test_template_appends_label_only_for_default():
    video = fmt("137", "mp4", 1080, "avc1")
    audio = fmt("140", "m4a", None, "none", "mp4a.40.2", abr=130.0)
    default = {"output_template": "%(title)s.%(ext)s"}
    custom = {"output_template": "%(uploader)s - %(title)s.%(ext)s"}
    assert engine.output_template_for(default, video, audio, False) == "%(title)s.1080p.H264.%(ext)s"
    assert engine.output_template_for(custom, video, audio, False) == "%(uploader)s - %(title)s.%(ext)s"


def test_template_audio_only_label():
    audio = fmt("140", "m4a", None, "none", "mp4a.40.2", abr=130.0)
    cfg = {"output_template": "%(title)s.%(ext)s"}
    assert engine.output_template_for(cfg, None, audio, True) == "%(title)s.audio.%(ext)s"


def test_template_height_unknown_falls_back_to_id():
    video = fmt("625", "mp4", None, "vp09.00.50.08")
    audio = fmt("140", "m4a", None, "none", "mp4a.40.2", abr=130.0)
    cfg = {"output_template": "%(title)s.%(ext)s"}
    out = engine.output_template_for(cfg, video, audio, False)
    assert ".VP9.625." in out


# --------------------------------------------------------------------------
# 大小估算
# --------------------------------------------------------------------------
def test_estimate_size_prefers_filesize():
    f = fmt(filesize=1000, tbr=9999)
    assert engine.estimate_size(f, 100) == (1000, False)


def test_estimate_size_from_bitrate():
    f = fmt(filesize=None, tbr=8000.0)
    size, estimated = engine.estimate_size(f, 60)
    assert estimated is True
    assert size == int(8000 * 1000 / 8 * 60)


def test_estimate_size_unknown():
    f = fmt(filesize=None, tbr=None)
    assert engine.estimate_size(f, 60) == (None, False)


# --------------------------------------------------------------------------
# 进度行解析（v1.4.1 起带 format_id，用于判断「视频流/音频流」阶段）
# --------------------------------------------------------------------------
def test_progress_line_with_format_id():
    line = "PROG|downloading|1024|358608461|NA|153666.0|2339|NA|NA|313"
    p = engine.parse_progress_line(line)
    assert p.format_id == "313"
    assert p.total == 358608461.0
    assert p.downloaded == 1024.0


def test_progress_line_na_format_id():
    line = "PROG|downloading|1|2|NA|3|4|NA|NA|NA"
    assert engine.parse_progress_line(line).format_id == ""


def test_progress_line_without_format_id_field():
    """老格式（9 段）仍要能解析，format_id 退化为空串。"""
    line = "PROG|downloading|1|2|NA|3|4|NA|NA"
    assert engine.parse_progress_line(line).format_id == ""


def test_progress_finished_line_has_no_total():
    """finished 行没有 total —— 阶段判断不能靠它算百分比。"""
    line = "PROG|finished|358608461|NA|NA|NA|NA|NA|NA|313"
    p = engine.parse_progress_line(line)
    assert p.status == "finished"
    assert p.total is None
    assert p.format_id == "313"


def test_postprocess_line():
    p = engine.parse_progress_line("PP|started|Merger")
    assert p.postprocessor == "Merger"
    assert p.status == "started"
