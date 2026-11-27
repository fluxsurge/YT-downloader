import os
import sys
import tempfile
import traceback

os.environ["YTDLP_GUI_CONFIG"] = os.path.join(tempfile.gettempdir(), "cfg_smoke.json")
os.environ["YTDLP_GUI_HISTORY"] = os.path.join(tempfile.gettempdir(), "hist_smoke.json")
# 每次从干净配置开始，否则上一轮写进去的 cookies_browser 会污染后续解析
for _path in (os.environ["YTDLP_GUI_CONFIG"], os.environ["YTDLP_GUI_HISTORY"]):
    if os.path.exists(_path):
        os.remove(_path)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from app import engine, history
from app.branding import chevron_path
from app.config import load_config
from app.theme import build_qss
import app.ui.main_window as mw
from app.ui.history_dialog import HistoryDialog
from app.ui.settings_dialog import SettingsDialog


class FakeBox:
    class Icon:
        Warning = Information = Critical = 0

    class StandardButton:
        Yes = 1
        No = 2
        Ok = 3

    def __init__(self, *a, **k):
        pass

    def setIcon(self, *a):
        pass

    def setWindowTitle(self, *a):
        pass

    def setText(self, *a):
        pass

    def setInformativeText(self, *a):
        pass

    def setDetailedText(self, *a):
        pass

    def exec(self):
        return 3

    information = warning = critical = staticmethod(lambda *a, **k: 3)
    # 一律回答「是」：403 引导会走「去设置」而不是真的重试下载
    question = staticmethod(lambda *a, **k: 1)


mw.QMessageBox = FakeBox
# 403 引导会打开模态设置窗口，headless 下会阻塞；测试里只记录调用
_opened_settings = []
mw.MainWindow._open_settings = lambda self: _opened_settings.append(True)

app = QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(build_qss(chevron_path()))

results = []


def step(label, fn):
    try:
        fn()
        results.append((label, "OK", ""))
    except Exception as exc:  # noqa: BLE001
        results.append((label, "FAIL", f"{type(exc).__name__}: {exc}"))
        traceback.print_exc()


cfg = load_config()
w = mw.MainWindow(cfg)
w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
w.resize(900, 880)
w.show()
app.processEvents()

# 1) 设置窗口
dlg = SettingsDialog(cfg, w)
dlg.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
step("设置窗口 构造", lambda: dlg.show())
step("设置窗口 读取配置", lambda: dlg._load())
step("设置窗口 保存", lambda: dlg.accept())
step("设置窗口 字幕语言往返", lambda: (
    dlg.subs_edit.setText("zh-Hans"),
    dlg.accept(),
    (_ for _ in ()).throw(AssertionError("sub_langs 未保存"))
    if dlg.cfg.get("sub_langs") != "zh-Hans" else None,
))

# 2) 解析
deps = engine.detect_deps(cfg)
w._on_deps_ready(deps)
info = engine.probe("https://www.youtube.com/watch?v=dQw4w9WgXcQ", cfg, deps)
step("解析并填表", lambda: (w.url_edit.setText("https://www.youtube.com/watch?v=dQw4w9WgXcQ"), w._on_probe_ok(info)))
app.processEvents()

# 3) 逐个交互
for mode in ("best", "1080", "720", "custom"):
    step(f"清晰度胶囊 {mode}", lambda m=mode: w.chips[m].click())
for value in ("auto", "vp9", "av1"):
    step(f"编码 {value}", lambda v=value: w.codec_combo.setCurrentIndex(w.codec_combo.findData(v)))
for value in ("m4a", "opus", "best"):
    step(f"音频源 {value}", lambda v=value: w.audio_combo.setCurrentIndex(w.audio_combo.findData(v)))
for value in ("auto", "mp4", "mkv"):
    step(f"容器 {value}", lambda v=value: w.container_combo.setCurrentIndex(w.container_combo.findData(v)))
for value in ("copy", "mp3"):
    step(f"音频输出 {value}", lambda v=value: w.audio_mode_combo.setCurrentIndex(w.audio_mode_combo.findData(v)))
for key in ("embed_thumbnail", "embed_metadata", "embed_chapters", "embed_subs"):
    step(f"附加项 {key} 关", lambda k=key: w.attach_chips[k].click())
    step(f"附加项 {key} 开", lambda k=key: w.attach_chips[k].click())
step("仅下载音频 勾选", lambda: w.audio_only_check.setChecked(True))
step("仅下载音频 取消", lambda: w.audio_only_check.setChecked(False))
step("显示全部画质", lambda: w.show_all_check.setChecked(True))
step("显示全部画质 复位", lambda: w.show_all_check.setChecked(False))
step("显示全部音频", lambda: w.show_all_audio_check.setChecked(True))
step("显示全部音频 复位", lambda: w.show_all_audio_check.setChecked(False))
step("点视频行", lambda: w._on_video_clicked(w.video_table.item(0, 0)))
step("点音频行", lambda: w._on_audio_clicked(w.audio_table.item(0, 0)))
step("摘要刷新", lambda: w._update_summary())
step("再下一次", lambda: w._on_retry_other())
step("打开文件夹", lambda: w._on_open_folder())
step("历史窗口", lambda: HistoryDialog(w).show())
step("历史 空记录", lambda: HistoryDialog(w)._reload())

# 4) 下载回调分支（不真下载）
step("回调-取消", lambda: (setattr(w, "_cancel_requested", True), w._on_download_done(1, "ERROR: Interrupted")))
step("回调-失败", lambda: w._on_download_done(1, "ERROR: unable to download video data: HTTP Error 403"))
step("回调-启动失败", lambda: w._on_download_done(-2, "boom"))

print("\n" + "=" * 52)
bad = 0
for label, status, detail in results:
    if status != "OK":
        bad += 1
    print(f"{status:4} {label}" + (f"  <- {detail}" if detail else ""))
print("=" * 52)
print(f"共 {len(results)} 项，失败 {bad} 项")
