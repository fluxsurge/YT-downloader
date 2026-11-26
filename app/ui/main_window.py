"""主窗口。"""
from __future__ import annotations

import base64
import os
from collections import deque

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import engine, history
from ..branding import app_icon
from ..config import resolve_proxy, save_config
from .settings_dialog import SettingsDialog

QUALITY_MODES = [
    ("best", "4K 最佳"),
    ("1080", "1080p"),
    ("720", "720p"),
    ("custom", "自定义"),
]

AUDIO_PREFS = [("m4a 优先", "m4a"), ("opus 优先", "opus"), ("最佳音频", "best")]
CODEC_PREFS = [("自动", "auto"), ("VP9 优先", "vp9"), ("AV1 优先", "av1")]
CONTAINERS = [("自动", "auto"), ("mp4", "mp4"), ("mkv", "mkv")]
AUDIO_MODES = [("直出原始", "copy"), ("转 mp3", "mp3")]
ATTACH_ITEMS = [
    ("embed_thumbnail", "封面", "把缩略图作为封面嵌入文件（webm 不支持）"),
    ("embed_metadata", "元数据", "把标题/作者/日期写进文件标签"),
    ("embed_chapters", "章节", "嵌入 YouTube 的章节标记（webm 不支持）"),
    ("embed_subs", "字幕", "下载字幕：mkv 内嵌，其它容器存为 .srt；语言在设置里"),
]
CODEC_TIP = (
    "自动：优先 mp4 容器里的最佳画质\n"
    "VP9 优先：同等分辨率下选高码率 VP9（画质最好，体积大）\n"
    "AV1 优先：同等分辨率下选 AV1（体积约为 VP9 的一半，画质接近）"
)
CONTAINER_TIP = (
    "自动：由 yt-dlp 挑最兼容的容器——先试 mp4，再试 webm，都装不下才落 mkv\n"
    "（判断依据是编码白名单 + 源容器，不是简单的「同族保留」）\n"
    "强制 mp4：兼容性最好，但 VP9/Opus 塞进 mp4 很多播放器不认\n"
    "强制 mkv：什么都能装，VLC/MPC 通吃，但 iPhone 和老电视不认"
)

MIN_VIDEO_HEIGHT = 1080
MIN_AUDIO_ABR = 100  # kbps，低于此值默认隐藏


# --------------------------------------------------------------------------- #
# 后台线程
# --------------------------------------------------------------------------- #
class ProbeThread(QThread):
    ok = Signal(dict)
    fail = Signal(str, str)

    def __init__(self, url: str, cfg: dict, deps: engine.Deps):
        super().__init__()
        self.url, self.cfg, self.deps = url, cfg, deps

    def run(self) -> None:
        try:
            info = engine.probe(self.url, self.cfg, self.deps)
        except engine.EngineError as exc:
            self.fail.emit(exc.message, exc.hint)
            return
        except Exception as exc:  # noqa: BLE001
            self.fail.emit("解析失败", str(exc))
            return
        self.ok.emit(info)


class DownloadThread(QThread):
    log = Signal(str)
    progress = Signal(object)
    filepath = Signal(str)
    done = Signal(int, str)

    def __init__(self, cfg, deps, url, selector, audio_only, out_dir,
                 container="", template="", force=False, expected_container=""):
        super().__init__()
        self.dl = engine.Downloader(
            cfg, deps, url, selector, audio_only, out_dir,
            container, template, force, expected_container,
        )

    def run(self) -> None:
        tail: deque[str] = deque(maxlen=80)
        try:
            self.dl.start()
        except engine.EngineError as exc:
            self.done.emit(-2, f"{exc.message}\n{exc.hint}")
            return
        except Exception as exc:  # noqa: BLE001
            self.done.emit(-2, str(exc))
            return
        try:
            for line in self.dl.lines():
                tail.append(line)
                final_path = engine.parse_filepath_line(line)
                if final_path:
                    self.filepath.emit(final_path)
                    continue
                parsed = engine.parse_progress_line(line)
                if parsed is not None:
                    self.progress.emit(parsed)
                else:
                    self.log.emit(line)
        except Exception:  # noqa: BLE001
            pass
        self.done.emit(self.dl.wait(), "\n".join(tail))

    def stop(self) -> None:
        self.dl.stop()


class DepsThread(QThread):
    ready = Signal(object)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        try:
            deps = engine.detect_deps(self.cfg)
        except Exception:  # noqa: BLE001
            return
        self.ready.emit(deps)


class UpdateThread(QThread):
    finished_msg = Signal(int, str)

    def __init__(self, cfg, deps):
        super().__init__()
        self.cfg, self.deps = cfg, deps

    def run(self) -> None:
        code, output = engine.update_engine(self.cfg, self.deps)
        self.finished_msg.emit(code, output)


class VersionCheckThread(QThread):
    found = Signal(str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        try:
            version = engine.check_latest_version(self.cfg)
        except Exception:  # noqa: BLE001
            return
        if version:
            self.found.emit(version)


class ConnectThread(QThread):
    result = Signal(bool, str)

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

    def run(self) -> None:
        ok, message = engine.test_connectivity(self.cfg)
        self.result.emit(ok, message)


class ThumbThread(QThread):
    loaded = Signal(bytes)
    failed = Signal()

    def __init__(self, url, cfg):
        super().__init__()
        self.url, self.cfg = url, cfg

    def run(self) -> None:
        try:
            with engine._open_with_proxy(self.cfg, self.url, 10) as resp:  # noqa: SLF001
                data = resp.read(3_000_000)
        except Exception:  # noqa: BLE001
            self.failed.emit()
            return
        if data:
            self.loaded.emit(data)
        else:
            self.failed.emit()


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self.deps = None
        self.info: dict | None = None
        self.formats: list[engine.Format] = []
        self.video_rows: list[engine.Format] = []
        self.audio_rows: list[engine.Format] = []
        self.video_sel: engine.Format | None = None
        self.audio_sel: engine.Format | None = None
        self._audio_manual = False
        self.last_file = ""
        self.duration = 0.0
        self._force_download = False
        self._pending: dict = {}
        self._cancel_requested = False
        saved_mode = cfg.get("last_quality") or "best"
        self.mode = saved_mode if saved_mode in ("best", "1080", "720") else "best"
        self.latest_version = ""
        self._syncing = False
        self._pending_download = False
        self._probe_thread: ProbeThread | None = None
        self._dl_thread: DownloadThread | None = None
        self._update_thread: UpdateThread | None = None
        self._version_thread: VersionCheckThread | None = None
        self._connect_thread: ConnectThread | None = None
        self._thumb_thread: ThumbThread | None = None
        self._deps_thread: DepsThread | None = None
        self._pending_parse = False

        self.setWindowTitle("YT 下载器")
        self.setWindowIcon(app_icon())
        self.setMinimumSize(880, 780)
        self.setAcceptDrops(True)
        self._build()
        self._restore_geometry()
        self._refresh_deps_ui()
        self._bind_shortcuts()
        chip = self.chips.get(self.mode)
        if chip is not None:
            chip.setChecked(True)
        self.audio_mode_combo.setEnabled(self.audio_only_check.isChecked())

        self._start_deps_detect()
        if cfg.get("check_update", True):
            QTimer.singleShot(1200, self._check_version_async)

    # ------------------------------------------------------------------ #
    # 构建界面
    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 10)
        layout.setSpacing(8)

        layout.addLayout(self._build_header())
        layout.addWidget(self._divider())
        layout.addLayout(self._build_url_row())
        layout.addLayout(self._build_info_row())
        layout.addLayout(self._build_options_row())
        layout.addLayout(self._build_video_header())
        layout.addWidget(self.video_table, 2)
        layout.addLayout(self._build_audio_header())
        layout.addWidget(self.audio_table, 1)
        layout.addLayout(self._build_summary_row())
        layout.addLayout(self._build_path_row())
        self.progress_box = self._build_progress_row()
        layout.addWidget(self.progress_box)
        layout.addWidget(self._build_log())

        self._build_statusbar()

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        return line

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        logo = QLabel()
        logo.setFixedSize(20, 20)
        logo.setPixmap(app_icon().pixmap(20, 20))
        row.addWidget(logo)

        title = QLabel("YT 下载器")
        title.setObjectName("AppTitle")
        row.addWidget(title)

        self.version_label = QLabel("yt-dlp —")
        self.version_label.setObjectName("Muted")
        row.addWidget(self.version_label)

        self.new_version_badge = QLabel("")
        self.new_version_badge.setObjectName("VersionBadge")
        self.new_version_badge.setVisible(False)
        row.addWidget(self.new_version_badge)

        row.addStretch(1)

        self.history_btn = QPushButton("历史")
        self.history_btn.setObjectName("Link")
        self.history_btn.clicked.connect(self._open_history)
        row.addWidget(self.history_btn)

        self.update_btn = QPushButton("引擎更新")
        self.update_btn.setObjectName("Link")
        self.update_btn.clicked.connect(self._on_update_clicked)
        row.addWidget(self.update_btn)

        self.settings_btn = QPushButton("设置")
        self.settings_btn.setObjectName("Link")
        self.settings_btn.clicked.connect(self._open_settings)
        row.addWidget(self.settings_btn)
        return row

    def _build_url_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("粘贴 YouTube 链接（Ctrl+V 直接解析，Enter 开始下载）")
        self.url_edit.setClearButtonEnabled(True)
        self.url_edit.returnPressed.connect(self._on_parse)
        row.addWidget(self.url_edit, 1)

        paste_btn = QPushButton("粘贴")
        paste_btn.setFixedWidth(64)
        paste_btn.clicked.connect(self._on_paste)
        row.addWidget(paste_btn)

        self.parse_btn = QPushButton("解析")
        self.parse_btn.setFixedWidth(88)
        self.parse_btn.clicked.connect(self._on_parse)
        row.addWidget(self.parse_btn)
        return row

    def _build_info_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.thumb_label = QLabel("封面")
        self.thumb_label.setObjectName("Thumb")
        self.thumb_label.setFixedSize(104, 58)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(self.thumb_label)

        column = QVBoxLayout()
        column.setSpacing(4)
        self.title_label = QLabel("还没有解析任何视频")
        self.title_label.setObjectName("VideoTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(42)
        column.addWidget(self.title_label)

        self.meta_label = QLabel("粘贴链接后点「解析」，即可看到可用格式")
        self.meta_label.setObjectName("Muted")
        column.addWidget(self.meta_label)
        column.addStretch(1)
        row.addLayout(column, 1)
        return row

    def _build_options_row(self) -> QVBoxLayout:
        """清晰度胶囊一行，编码/音频/容器另一行——一行塞太多控件会互相挤。"""
        box = QVBoxLayout()
        box.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(6)
        hint = QLabel("清晰度")
        hint.setObjectName("Hint")
        top.addWidget(hint)

        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        self.chips: dict[str, QPushButton] = {}
        for mode, label in QUALITY_MODES:
            chip = QPushButton(label)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, m=mode: self._on_chip(m))
            self.chip_group.addButton(chip)
            self.chips[mode] = chip
            top.addWidget(chip)

        top.addStretch(1)

        self.audio_only_check = QCheckBox("仅下载音频")
        self.audio_only_check.setToolTip("勾选后忽略视频选择，只下载音频并转成 mp3 320k")
        self.audio_only_check.toggled.connect(self._on_audio_only_toggled)
        top.addWidget(self.audio_only_check)
        box.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        # 按 QSS 里的实际字号（13px）量文字宽度，否则会比真实渲染窄
        metric_font = QFont("Microsoft YaHei UI")
        metric_font.setPixelSize(13)
        metrics = QFontMetrics(metric_font)
        all_labels = [t for t, _ in CODEC_PREFS + AUDIO_PREFS + CONTAINERS]
        combo_width = max(metrics.horizontalAdvance(t) for t in all_labels) + 58

        def add_field(
            caption: str,
            items: list[tuple[str, str]],
            current: str,
            tip: str,
            handler,
            width: int,
        ) -> QComboBox:
            label = QLabel(caption)
            label.setObjectName("FieldLabel")
            bottom.addWidget(label)
            combo = QComboBox()
            for item_label, item_value in items:
                combo.addItem(item_label, item_value)
            idx = combo.findData(current)
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            combo.setFixedWidth(width)
            if tip:
                combo.setToolTip(tip)
            combo.currentIndexChanged.connect(handler)
            bottom.addWidget(combo)
            bottom.addSpacing(4)
            return combo

        self.codec_combo = add_field(
            "编码", CODEC_PREFS, self.cfg.get("codec_pref", "auto"),
            CODEC_TIP, self._on_codec_pref_changed, combo_width,
        )
        self.audio_combo = add_field(
            "音频", AUDIO_PREFS, self.cfg.get("audio_pref", "m4a"),
            "优先使用的音频流；选定视频后会自动按这个偏好配一条", self._on_audio_pref_changed, combo_width,
        )
        self.container_combo = add_field(
            "容器", CONTAINERS, self.cfg.get("container", "auto"),
            CONTAINER_TIP, self._on_container_changed, combo_width,
        )
        self.audio_mode_combo = add_field(
            "输出", AUDIO_MODES, self.cfg.get("audio_mode", "copy"),
            "仅「仅下载音频」时生效：直出原始流（m4a/webm，不转码）或转成 mp3 320k",
            self._on_audio_mode_changed, combo_width,
        )
        bottom.addStretch(1)
        box.addLayout(bottom)

        attach_row = QHBoxLayout()
        attach_row.setSpacing(6)
        attach_label = QLabel("附加")
        attach_label.setObjectName("Hint")
        attach_row.addWidget(attach_label)
        self.attach_chips: dict[str, QPushButton] = {}
        for key, text, tip in ATTACH_ITEMS:
            chip = QPushButton(text)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(tip)
            chip.setChecked(bool(self.cfg.get(key, key != "embed_subs")))
            chip.toggled.connect(lambda _=False, k=key: self._on_attach_toggled(k))
            self.attach_chips[key] = chip
            attach_row.addWidget(chip)
        attach_row.addStretch(1)
        self.attach_hint = QLabel("")
        self.attach_hint.setObjectName("Hint")
        attach_row.addWidget(self.attach_hint)
        box.addLayout(attach_row)
        return box

    def _make_table(self, headers: list[str], widths: list[int | None]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setWordWrap(False)
        header = table.horizontalHeader()
        header.setHighlightSections(False)
        header.setStretchLastSection(False)
        for col, width in enumerate(widths):
            if width:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
                table.setColumnWidth(col, width)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setDefaultSectionSize(28)
        return table

    def _build_video_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.video_count_label = QLabel("视频流")
        self.video_count_label.setObjectName("Muted")
        row.addWidget(self.video_count_label)
        row.addStretch(1)

        self.show_all_check = QCheckBox("显示全部画质")
        self.show_all_check.setToolTip(
            f"默认只显示 {MIN_VIDEO_HEIGHT}p 及以上；勾选后可看到 720p/480p 等低画质"
        )
        self.show_all_check.toggled.connect(self._on_show_all_toggled)
        row.addWidget(self.show_all_check)

        self.video_table = self._make_table(
            ["分辨率", "编码", "帧率", "大小", "格式 ID", "类型"],
            [130, 84, 56, 100, 92, None],
        )
        self.video_table.setMinimumHeight(84)   # 3 行；再小就压不动了
        self.video_table.itemClicked.connect(self._on_video_clicked)
        self.video_table.itemSelectionChanged.connect(self._on_video_selection)
        return row

    def _build_audio_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.audio_count_label = QLabel("音频流")
        self.audio_count_label.setObjectName("Muted")
        self.audio_count_label.setMinimumHeight(18)
        row.addWidget(self.audio_count_label)
        row.addStretch(1)
        self.show_all_audio_check = QCheckBox("显示全部音频")
        self.show_all_audio_check.setToolTip(
            "默认只显示 100kbps 及以上的音轨；勾选后可见 48/64kbps 等低质量音轨"
        )
        self.show_all_audio_check.toggled.connect(self._on_show_all_audio_toggled)
        row.addWidget(self.show_all_audio_check)

        self.audio_table = self._make_table(
            ["编码", "码率", "容器", "大小", "格式 ID"],
            [110, 100, 90, 100, None],
        )
        self.audio_table.setMinimumHeight(30 + 28 * 2)   # 2 行，最小窗口下也要看得见两条
        self.audio_table.setMaximumHeight(30 + 28 * 4)
        self.audio_table.itemClicked.connect(self._on_audio_clicked)
        self.audio_table.itemSelectionChanged.connect(self._on_audio_selection)
        return row

    def _build_summary_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Muted")
        row.addWidget(self.summary_label, 1)

        self.redownload_btn = QPushButton("仍要重新下载")
        self.redownload_btn.setObjectName("Link")
        self.redownload_btn.setVisible(False)
        self.redownload_btn.clicked.connect(self._on_redownload)
        row.addWidget(self.redownload_btn)

        self.retry_btn = QPushButton("再下一次（换个画质）")
        self.retry_btn.setObjectName("Link")
        self.retry_btn.setVisible(False)
        self.retry_btn.clicked.connect(self._on_retry_other)
        row.addWidget(self.retry_btn)
        return row

    def _build_path_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        label = QLabel("保存到")
        label.setObjectName("Muted")
        label.setFixedWidth(44)
        row.addWidget(label)

        self.dir_edit = QLineEdit(self.cfg.get("download_dir", ""))
        row.addWidget(self.dir_edit, 1)

        browse_btn = QPushButton("浏览")
        browse_btn.setFixedWidth(64)
        browse_btn.clicked.connect(self._on_browse_dir)
        row.addWidget(browse_btn)

        self.start_btn = QPushButton("开始下载")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setMinimumWidth(112)
        self.start_btn.clicked.connect(self._start_download)
        row.addWidget(self.start_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedWidth(64)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel)
        row.addWidget(self.cancel_btn)
        return row

    def _build_progress_row(self) -> QWidget:
        wrapper = QWidget()
        box = QVBoxLayout(wrapper)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        labels = QHBoxLayout()
        self.stage_label = QLabel("就绪")
        self.stage_label.setObjectName("Muted")
        self.metrics_label = QLabel("")
        self.metrics_label.setObjectName("Muted")
        self.metrics_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        labels.addWidget(self.stage_label, 1)
        labels.addWidget(self.metrics_label)
        box.addLayout(labels)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setFixedHeight(6)
        box.addWidget(self.progress)
        wrapper.setVisible(False)
        return wrapper

    def _build_log(self) -> QPlainTextEdit:
        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("Log")
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(5000)
        self.log_edit.setFixedHeight(96)
        self.log_edit.setPlaceholderText("yt-dlp 的实时输出会显示在这里")
        font = QFont("Cascadia Mono", 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.log_edit.setFont(font)
        return self.log_edit

    def _build_statusbar(self) -> None:
        bar = self.statusBar()
        self.deps_label = QLabel("")
        self.deps_label.setObjectName("Muted")
        bar.addWidget(self.deps_label, 1)

        self.connect_btn = QPushButton("测试连通")
        self.connect_btn.setObjectName("Link")
        self.connect_btn.clicked.connect(self._on_test_connect)
        bar.addPermanentWidget(self.connect_btn)

        self.open_file_btn = QPushButton("打开文件")
        self.open_file_btn.setObjectName("Link")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(self._on_open_file)
        bar.addPermanentWidget(self.open_file_btn)

        self.open_btn = QPushButton("打开文件夹")
        self.open_btn.setObjectName("Link")
        self.open_btn.clicked.connect(self._on_open_folder)
        bar.addPermanentWidget(self.open_btn)

    def _bind_shortcuts(self) -> None:
        QShortcut(QKeySequence.StandardKey.Paste, self, activated=self._shortcut_paste)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self, activated=self._shortcut_enter)
        QShortcut(QKeySequence(Qt.Key.Key_Enter), self, activated=self._shortcut_enter)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._shortcut_escape)

    # ------------------------------------------------------------------ #
    # 状态刷新
    # ------------------------------------------------------------------ #
    def _start_deps_detect(self) -> None:
        """依赖检测放到后台：yt-dlp --version 要 2 秒多，不能卡住窗口显示。"""
        self._deps_thread = DepsThread(self.cfg)
        self._deps_thread.ready.connect(self._on_deps_ready)
        self._deps_thread.start()

    def _on_deps_ready(self, deps) -> None:
        self._deps_thread = None
        self.deps = deps
        self.cfg["deps_cache"] = deps.cache
        self._refresh_deps_ui()
        if self._pending_parse:
            self._pending_parse = False
            self._on_parse()

    def _refresh_deps_ui(self) -> None:
        if self.deps is None:
            self.version_label.setText("yt-dlp 检测中…")
            self.deps_label.setText("正在检测 Deno / ffmpeg / 代理…")
            return
        version = self.deps.ytdlp_version or "未找到"
        self.version_label.setText(f"yt-dlp {version}")

        parts = []
        if self.deps.deno:
            deno_ver = self.deps.deno_version.split()[1] if " " in self.deps.deno_version else self.deps.deno_version
            parts.append(f"Deno {deno_ver}")
        else:
            parts.append('<span style="color:#A32D2D;">Deno 未找到</span>')
        if self.deps.ffmpeg:
            ff_version = self.deps.ffmpeg_version.split("-")[0]
            parts.append(f"ffmpeg {ff_version}")
        else:
            parts.append('<span style="color:#A32D2D;">ffmpeg 未找到</span>')

        proxy = resolve_proxy(self.cfg)
        mode = self.cfg.get("proxy_mode", "auto")
        if proxy:
            parts.append(f"代理 {proxy}")
        elif mode == "off":
            parts.append("代理 已关闭")
        else:
            parts.append('<span style="color:#A32D2D;">代理 未检测到</span>')

        if not self.deps.ytdlp:
            parts.insert(0, '<span style="color:#A32D2D;">引擎缺失</span>')
        self.deps_label.setText(" · ".join(parts))

    def _set_status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)

    def _append_log(self, text: str) -> None:
        for line in str(text).splitlines():
            self.log_edit.appendPlainText(line)

    # ------------------------------------------------------------------ #
    # 键盘流
    # ------------------------------------------------------------------ #
    def _shortcut_paste(self) -> None:
        widget = QApplication.focusWidget()
        if isinstance(widget, QLineEdit):
            widget.paste()
            if widget is self.url_edit:
                self._on_parse()
            return
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)
            self._on_parse()

    def _shortcut_enter(self) -> None:
        if QApplication.focusWidget() is self.url_edit:
            return  # returnPressed 已经处理
        self._start_download()

    def _shortcut_escape(self) -> None:
        if self._dl_thread is not None:
            self._on_cancel()

    # ------------------------------------------------------------------ #
    # 解析
    # ------------------------------------------------------------------ #
    def _on_paste(self) -> None:
        text = QApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)
            self._on_parse()

    def _on_parse(self) -> None:
        if self._probe_thread is not None:
            return
        if self.deps is None:
            self._pending_parse = True
            self._set_status("正在检测依赖，稍候自动开始解析…")
            return
        url = engine.normalize_url(self.url_edit.text())
        if not url:
            QMessageBox.information(self, "还没有链接", "请先粘贴一个 YouTube 视频链接。")
            return
        if url != self.url_edit.text().strip():
            self.url_edit.setText(url)

        self.parse_btn.setEnabled(False)
        self.parse_btn.setText("解析中…")
        self.progress_box.setVisible(True)
        self.stage_label.setText("正在解析视频信息…")
        self.progress.setRange(0, 0)

        self._probe_thread = ProbeThread(url, self.cfg, self.deps)
        self._probe_thread.ok.connect(self._on_probe_ok)
        self._probe_thread.fail.connect(self._on_probe_fail)
        self._probe_thread.finished.connect(self._on_probe_finished)
        self._probe_thread.start()

    def _on_probe_finished(self) -> None:
        self._probe_thread = None
        self.parse_btn.setEnabled(True)
        self.parse_btn.setText("解析")

    def _on_probe_ok(self, info: dict) -> None:
        self.info = info
        self.duration = float(info.get("duration") or 0)
        self._force_download = False
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.last_file = ""
        self.open_file_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self._audio_manual = False
        self._pending = {}
        self.audio_only_check.setChecked(False)
        self._populate(info)

        title = str(info.get("title") or "（无标题）")
        self.title_label.setText(title)
        self.setWindowTitle(f"{title} - YT 下载器")

        meta = []
        duration = info.get("duration")
        if duration:
            meta.append(engine.human_duration(duration))
        if info.get("uploader"):
            meta.append(str(info["uploader"]))
        if self.video_rows:
            top = self.video_rows[0]
            if top.height:
                meta.append(f"最高 {top.height}p")
        meta.append(f"{len(self.video_rows)} 个视频流 · {len(self.audio_rows)} 条音频")
        self.meta_label.setText(" · ".join(meta))

        thumb = info.get("thumbnail")
        if thumb:
            self._load_thumbnail(str(thumb))
        self.stage_label.setText("解析完成")
        self._set_status("解析完成，选好视频和音频后下载")

        if self._pending_download:
            self._pending_download = False
            QTimer.singleShot(50, self._start_download)

    def _on_probe_fail(self, message: str, hint: str) -> None:
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.stage_label.setText("解析失败")
        self._set_status("解析失败")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("解析失败")
        box.setText(message)
        if hint:
            box.setInformativeText(hint)
        box.exec()

    def _load_thumbnail(self, url: str) -> None:
        self.thumb_label.setText("加载中")
        self._thumb_thread = ThumbThread(url, self.cfg)
        self._thumb_thread.loaded.connect(self._on_thumb_loaded)
        self._thumb_thread.failed.connect(lambda: self.thumb_label.setText("封面"))
        self._thumb_thread.start()

    def _on_thumb_loaded(self, data: bytes) -> None:
        pix = QPixmap()
        if not pix.loadFromData(data):
            self.thumb_label.setText("封面")
            return
        scaled = pix.scaled(
            self.thumb_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.thumb_label.setPixmap(scaled)

    # ------------------------------------------------------------------ #
    # 两张格式表
    # ------------------------------------------------------------------ #
    def _populate(self, info: dict) -> None:
        self.formats = engine.parse_formats(info)
        self.video_sel = None
        self.audio_sel = None
        self._rebuild_audio_table()
        self._rebuild_video_table()

        mode = self.mode if self.mode in self.chips else "best"
        self._apply_mode(mode)

    def _rebuild_video_table(self) -> None:
        pref = self.cfg.get("codec_pref", "auto")
        rows = engine.video_formats(self.formats, pref)
        if not self.show_all_check.isChecked():
            filtered = [f for f in rows if (f.height or 0) >= MIN_VIDEO_HEIGHT]
            rows = filtered or rows
        self.video_rows = rows

        self._syncing = True
        try:
            self.video_table.setRowCount(0)
            for fmt in rows:
                row = self.video_table.rowCount()
                self.video_table.insertRow(row)
                cells = [
                    fmt.resolution_text,
                    engine.codec_name(fmt.vcodec),
                    fmt.fps_text,
                    engine.size_text(fmt, self.duration),
                    fmt.format_id,
                    fmt.kind_text,
                ]
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col == 4:
                        item.setForeground(QColor("#9AA0A6"))
                    if col == 5:
                        item.setForeground(QColor("#606060"))
                    item.setToolTip(
                        f"format_id: {fmt.format_id} · 容器 {fmt.ext} · 协议 {fmt.proto or '—'}"
                    )
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, fmt.format_id)
                    self.video_table.setItem(row, col, item)
        finally:
            self._syncing = False

        hidden = len(engine.video_formats(self.formats, pref)) - len(rows)
        suffix = f"（已隐藏 {hidden} 个低画质）" if hidden > 0 else ""
        self.video_count_label.setText(f"视频流 {len(rows)}{suffix}")

        if self.video_sel is not None:
            self._highlight(self.video_table, self.video_sel.format_id)

    def _rebuild_audio_table(self) -> None:
        all_rows = engine.audio_formats(self.formats)
        rows = all_rows
        if not self.show_all_audio_check.isChecked():
            filtered = [f for f in all_rows if (f.abr or 0) >= MIN_AUDIO_ABR]
            rows = filtered or all_rows
        self.audio_rows = rows

        self._syncing = True
        try:
            self.audio_table.setRowCount(0)
            for fmt in rows:
                row = self.audio_table.rowCount()
                self.audio_table.insertRow(row)
                cells = [
                    engine.codec_name(fmt.acodec),
                    f"{fmt.abr:.0f} kbps" if fmt.abr else "—",
                    fmt.ext,
                    engine.size_text(fmt, self.duration),
                    fmt.format_id,
                ]
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if col == 4:
                        item.setForeground(QColor("#9AA0A6"))
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, fmt.format_id)
                    item.setToolTip(
                        f"format_id: {fmt.format_id} · 容器 {fmt.ext} · 码率 {fmt.abr or '—'}"
                    )
                    self.audio_table.setItem(row, col, item)
        finally:
            self._syncing = False

        hidden = len(all_rows) - len(rows)
        suffix = f"（已隐藏 {hidden} 条低码率）" if hidden > 0 else ""
        self.audio_count_label.setText(f"音频流 {len(rows)}{suffix}")
        if self.audio_sel is not None:
            self._highlight(self.audio_table, self.audio_sel.format_id)

    def _highlight(self, table: QTableWidget, format_id: str) -> None:
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == format_id:
                self._syncing = True
                table.selectRow(row)
                table.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                self._syncing = False
                return

    def _apply_mode(self, mode: str) -> None:
        self.mode = mode
        chip = self.chips.get(mode)
        if chip is not None:
            chip.setChecked(True)
        if mode == "custom":
            self._update_summary()
            return

        cap = {"best": 2160, "1080": 1080, "720": 720}.get(mode, 2160)
        target = engine.best_video(self.formats, cap, self.cfg.get("codec_pref", "auto"))
        if target is not None:
            self._select_video(target)
        self._ensure_audio()
        self._update_summary()

    def _select_video(self, fmt: engine.Format) -> None:
        self.video_sel = fmt
        if self._row_of(self.video_table, fmt.format_id) < 0 and not self.show_all_check.isChecked():
            self.show_all_check.setChecked(True)
            self._rebuild_video_table()
        self._highlight(self.video_table, fmt.format_id)
        self._update_summary()

    def _select_audio(self, fmt: engine.Format) -> None:
        self.audio_sel = fmt
        self._highlight(self.audio_table, fmt.format_id)
        self._update_summary()

    @staticmethod
    def _row_of(table: QTableWidget, format_id: str) -> int:
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == format_id:
                return row
        return -1

    def _ensure_audio(self, force: bool = False) -> None:
        if not self.audio_rows:
            self.audio_sel = None
            return
        if self.audio_sel is not None and not force:
            return
        if self._audio_manual and not force:
            return
        want_ext = {"m4a": "m4a", "opus": "webm"}.get(self.cfg.get("audio_pref", "m4a"))
        pick = next((f for f in self.audio_rows if f.ext == want_ext), None) if want_ext else None
        self._select_audio(pick or self.audio_rows[0])

    def _on_chip(self, mode: str) -> None:
        if mode == "custom":
            self.mode = "custom"
            self._update_summary()
            return
        if self.audio_only_check.isChecked():
            self.audio_only_check.setChecked(False)
        self._apply_mode(mode)

    def _on_video_clicked(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        row = item.row()
        if not (0 <= row < len(self.video_rows)):
            return
        if self.audio_only_check.isChecked():
            self.audio_only_check.setChecked(False)
        self.video_sel = self.video_rows[row]
        self.mode = "custom"
        self.chips["custom"].setChecked(True)
        self._ensure_audio()
        self._update_summary()

    def _on_video_selection(self) -> None:
        if self._syncing:
            return
        row = self.video_table.currentRow()
        if 0 <= row < len(self.video_rows):
            self.video_sel = self.video_rows[row]
            self.mode = "custom"
            self.chips["custom"].setChecked(True)
            self._ensure_audio()
            self._update_summary()

    def _on_audio_clicked(self, item: QTableWidgetItem) -> None:
        if item is None:
            return
        row = item.row()
        if 0 <= row < len(self.audio_rows):
            self._audio_manual = True
            self._select_audio(self.audio_rows[row])

    def _on_audio_selection(self) -> None:
        if self._syncing:
            return
        row = self.audio_table.currentRow()
        if 0 <= row < len(self.audio_rows):
            self.audio_sel = self.audio_rows[row]
            self._update_summary()

    def _on_audio_only_toggled(self, checked: bool) -> None:
        self.video_table.setEnabled(not checked)
        for chip in self.chips.values():
            chip.setEnabled(not checked)
        self.codec_combo.setEnabled(not checked)
        self.container_combo.setEnabled(not checked)
        self.audio_mode_combo.setEnabled(checked)
        if checked:
            self._ensure_audio(force=True)
        self._update_summary()

    def _on_show_all_toggled(self) -> None:
        self._rebuild_video_table()

    def _on_show_all_audio_toggled(self) -> None:
        self._rebuild_audio_table()
        if self.audio_sel is not None and self._row_of(
            self.audio_table, self.audio_sel.format_id
        ) < 0:
            self._audio_manual = False
            self._ensure_audio(force=True)
        self._update_summary()

    def _on_audio_pref_changed(self) -> None:
        self.cfg["audio_pref"] = self.audio_combo.currentData() or "m4a"
        save_config(self.cfg)
        self._audio_manual = False
        self._ensure_audio(force=True)
        self._update_summary()

    def _on_codec_pref_changed(self) -> None:
        self.cfg["codec_pref"] = self.codec_combo.currentData() or "auto"
        save_config(self.cfg)
        self._rebuild_video_table()
        if self.mode in ("best", "1080", "720"):
            self._apply_mode(self.mode)
        else:
            self._update_summary()

    def _on_audio_mode_changed(self) -> None:
        self.cfg["audio_mode"] = self.audio_mode_combo.currentData() or "copy"
        save_config(self.cfg)
        self._update_summary()

    def _on_attach_toggled(self, key: str) -> None:
        self.cfg[key] = self.attach_chips[key].isChecked()
        save_config(self.cfg)
        self._update_summary()

    def _refresh_attach_state(self) -> None:
        """按当前容器/模式，禁用装不下的附加项，并提示原因。"""
        audio_only = self.audio_only_check.isChecked()
        container = engine.container_hint(self.cfg, self.video_sel, self.audio_sel, audio_only)
        caps = engine._EMBED_MATRIX.get(container, {})  # noqa: SLF001

        self.attach_chips["embed_metadata"].setEnabled(True)
        self.attach_chips["embed_thumbnail"].setEnabled(bool(caps.get("thumbnail")))
        self.attach_chips["embed_chapters"].setEnabled(bool(caps.get("chapters")) and not audio_only)
        self.attach_chips["embed_subs"].setEnabled(not audio_only)

        blocked = []
        if not caps.get("thumbnail"):
            blocked.append("封面")
        if not caps.get("chapters") or audio_only:
            blocked.append("章节")
        if audio_only:
            blocked.append("字幕")
        self.attach_hint.setText(
            f"{container} 不支持 {'/'.join(blocked)}，已跳过" if blocked else ""
        )

    def _on_container_changed(self) -> None:
        self.cfg["container"] = self.container_combo.currentData() or "auto"
        save_config(self.cfg)
        self._update_summary()

    # ------------------------------------------------------------------ #
    # 组合摘要
    # ------------------------------------------------------------------ #
    def _update_summary(self) -> None:
        if not self.formats:
            self.summary_label.setText("")
            return
        self._refresh_attach_state()

        audio_only = self.audio_only_check.isChecked()
        if audio_only:
            fmt = self.audio_sel
            if fmt is None:
                self.summary_label.setText("将下载：仅音频（未选音频流）")
                return
            src = f"{engine.codec_name(fmt.acodec)}"
            if fmt.abr:
                src += f" {fmt.abr:.0f}kbps"
            mode = (self.cfg.get("audio_mode") or "copy").lower()
            target = "mp3 320k" if mode == "mp3" else f"直出 {fmt.ext}"
            bits = [f"仅音频 → {target}", f"源 {fmt.format_id}（{src}）"]
            size, estimated = engine.estimate_size(fmt, self.duration)
            if size:
                bits.append(("≈ " if estimated else "") + engine.human_size(size))
            self.summary_label.setText("将下载：" + " · ".join(bits))
            return

        video = self.video_sel
        if video is None:
            self.summary_label.setText("")
            return

        head = [video.resolution_text, engine.codec_name(video.vcodec)]
        if video.fps:
            head.append(f"{video.fps:.0f}fps")

        audio = self.audio_sel
        if video.has_audio:
            combo = f"格式 {video.format_id}（自带音频）"
            v_size, v_est = engine.estimate_size(video, self.duration)
            a_size, a_est = 0, False
        elif audio is not None:
            src = engine.codec_name(audio.acodec)
            if audio.abr:
                src += f" {audio.abr:.0f}kbps"
            combo = f"格式 {video.format_id} + 音频 {audio.format_id}（{src}）"
            v_size, v_est = engine.estimate_size(video, self.duration)
            a_size, a_est = engine.estimate_size(audio, self.duration)
        else:
            combo = f"格式 {video.format_id} + 自动配音轨"
            v_size, v_est = engine.estimate_size(video, self.duration)
            a_size, a_est = 0, False

        bits = [" · ".join(head), combo]
        total = (v_size or 0) + (a_size or 0)
        if v_size is None and a_size:
            # 视频大小既没有 filesize 也没有码率可推算
            bits.append(f"音频 {engine.human_size(a_size)}（视频大小未知）")
        elif total:
            approx = "≈ " if (v_est or a_est) else ""
            bits.append(f"合计 {approx}{engine.human_size(total)}")
        container = engine.container_hint(self.cfg, video, audio, False)
        bits.append(f"容器 {container}")
        extra = engine.enhance_text(self.cfg, container, False)
        if extra:
            bits.append(f"附加 {extra}")
        self.summary_label.setText("将下载：" + " · ".join(bits))

    # ------------------------------------------------------------------ #
    # 下载
    # ------------------------------------------------------------------ #
    def _on_browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "选择下载目录", self.dir_edit.text() or os.path.expanduser("~")
        )
        if path:
            self.dir_edit.setText(os.path.normpath(path))

    def _start_download(self) -> None:
        if self._dl_thread is not None:
            return
        if self.deps is None:
            self._pending_parse = True
            self._set_status("正在检测依赖，稍候自动开始…")
            return

        url = engine.normalize_url(self.url_edit.text())
        if not url:
            QMessageBox.information(self, "还没有链接", "请先粘贴一个 YouTube 视频链接。")
            return
        if not self.formats:
            self._pending_download = True
            self._on_parse()
            return

        audio_only = self.audio_only_check.isChecked()
        if not audio_only and self.video_sel is None:
            QMessageBox.information(
                self, "还没选视频", "请在视频表里选一行；或者勾选「仅下载音频」只下音频。"
            )
            return

        out_dir = self.dir_edit.text().strip().strip('"')
        if not out_dir:
            out_dir = self.cfg.get("download_dir") or os.path.expanduser("~")
            self.dir_edit.setText(out_dir)
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "目录不可用", f"无法创建下载目录：\n{out_dir}\n\n{exc}")
                return

        self.cfg["download_dir"] = out_dir
        if self.mode != "custom":
            self.cfg["last_quality"] = self.mode
        save_config(self.cfg)

        selector, audio_only = engine.build_combo_selector(
            self.video_sel, self.audio_sel, audio_only, self.cfg.get("audio_pref", "m4a")
        )
        template = engine.output_template_for(
            self.cfg, self.video_sel, self.audio_sel, audio_only
        )
        container = "" if audio_only else engine.container_arg(self.cfg)
        shown_container = engine.container_hint(self.cfg, self.video_sel, self.audio_sel, audio_only)

        # ---- 历史去重：键 = video_id + 视频格式 + 音频格式 + 容器 ----
        info = self.info or {}
        video_id = str(info.get("id") or "")
        video_fmt = "" if audio_only else (self.video_sel.format_id if self.video_sel else "")
        if audio_only:
            audio_fmt = self.audio_sel.format_id if self.audio_sel else ""
        elif self.video_sel is not None and not self.video_sel.has_audio and self.audio_sel is not None:
            audio_fmt = self.audio_sel.format_id
        else:
            audio_fmt = ""
        key = history.make_key(video_id, video_fmt, audio_fmt, shown_container)
        self._pending = {
            "key": key,
            "video_id": video_id,
            "title": str(info.get("title") or ""),
            "video_format": video_fmt,
            "audio_format": audio_fmt,
            "container": shown_container,
            "url": url,
        }

        force = self._force_download
        self._force_download = False
        if not force:
            entry = history.find(key)
            if entry and entry.get("path") and os.path.isfile(entry["path"]):
                self.last_file = entry["path"]
                self.open_file_btn.setEnabled(True)
                self.stage_label.setText("这个组合已经下过了")
                self.metrics_label.setText("")
                self.progress_box.setVisible(True)
                self.progress.setRange(0, 100)
                self.progress.setValue(100)
                self._set_status("已跳过：历史里有这个组合")
                self._append_log(
                    f"# 跳过：{os.path.basename(entry['path'])}（{entry.get('time', '')} 下过）"
                )
                self.redownload_btn.setVisible(True)
                self.retry_btn.setVisible(False)
                return

        self.log_edit.clear()
        suffix = "  [仅音频 → mp3]" if audio_only else f"  [容器 {shown_container}]"
        self._append_log(f'$ yt-dlp -f "{selector}"' + suffix)
        self._append_log(f"# 文件名：{template}")
        self._append_log(f"# 输出目录：{out_dir}")
        extra = engine.enhance_text(self.cfg, shown_container, audio_only)
        if extra:
            note = "（webm 不支持封面/章节，已跳过）" if shown_container == "webm" else ""
            self._append_log(f"# 附加：{extra}{note}")
        if force:
            self._append_log("# 强制覆盖已存在的文件")

        self._dl_thread = DownloadThread(
            self.cfg, self.deps, url, selector, audio_only, out_dir,
            container, template, force, shown_container,
        )
        self._dl_thread.log.connect(self._append_log)
        self._dl_thread.progress.connect(self._on_progress)
        self._dl_thread.filepath.connect(self._on_filepath)
        self._dl_thread.done.connect(self._on_download_done)
        self._dl_thread.start()

        self.progress_box.setVisible(True)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.open_btn.setEnabled(False)
        self.open_file_btn.setEnabled(False)
        self.retry_btn.setVisible(False)
        self.redownload_btn.setVisible(False)
        self._cancel_requested = False
        self.progress.setRange(0, 0)
        self.stage_label.setText("正在启动下载…")
        self.metrics_label.setText("")
        self._set_status("下载中")

    def _on_progress(self, p: engine.Progress) -> None:
        if p.postprocessor:
            if p.status == "started":
                self.stage_label.setText("正在合并 / 转码…")
                self.progress.setRange(0, 0)
            elif p.status == "finished":
                self.stage_label.setText("后处理完成")
            return

        if p.status == "finished":
            self.stage_label.setText("下载完成，正在后处理…")
            self.progress.setRange(0, 0)
            return

        total = p.total
        if total:
            ratio = min(100.0, (p.downloaded or 0) / total * 100.0)
            self.progress.setRange(0, 100)
            self.progress.setValue(int(ratio))
        else:
            self.progress.setRange(0, 0)

        bits: list[str] = []
        if total:
            bits.append(f"{(p.downloaded or 0) / total * 100:.1f}%")
            bits.append(f"{engine.human_size(p.downloaded)} / {engine.human_size(total)}")
        elif p.downloaded:
            bits.append(engine.human_size(p.downloaded))
        if p.speed:
            bits.append(f"{engine.human_size(p.speed)}/s")
        if p.eta is not None:
            bits.append(f"剩余 {engine.human_eta(p.eta)}")
        if p.frag_count:
            bits.append(f"分片 {p.frag_index or 0}/{p.frag_count}")
        self.metrics_label.setText(" · ".join(bits))
        self.stage_label.setText("正在下载")

    def _on_filepath(self, path: str) -> None:
        self.last_file = path
        self.open_file_btn.setEnabled(os.path.isfile(path))
        self._append_log(f"# 输出文件：{path}")

    def _on_download_done(self, code: int, tail: str) -> None:
        self._dl_thread = None
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if code == 0:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.open_btn.setEnabled(True)
            self._record_history()

            if "has already been downloaded" in tail:
                self.stage_label.setText("这个组合已经下过了")
                self.metrics_label.setText("")
                self._set_status("跳过：同名文件已存在")
                self._append_log("== 已跳过（同名文件存在）==")
                QMessageBox.information(
                    self,
                    "已跳过",
                    "这个「视频 + 音频 + 容器」组合已经下过了，同名文件已存在，所以这次没有真正下载。\n\n"
                    "换一个画质、编码或容器会生成不同的文件名；想重新下同一组合，先删掉旧文件。",
                )
                return

            name = os.path.basename(self.last_file) if self.last_file else ""
            self.stage_label.setText(f"下载完成{(' · ' + name) if name else ''}")
            self.metrics_label.setText("")
            self.retry_btn.setVisible(True)
            self._append_log("== 全部完成 ==")
            self._set_status("下载完成")
            return

        if code == -2:
            self.stage_label.setText("无法启动下载")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            QMessageBox.critical(self, "无法启动下载", tail)
            return

        if code != 0 and self.last_file and os.path.isfile(self.last_file):
            # 常见于字幕/封面接口报错：视频其实已经下好了
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.open_btn.setEnabled(True)
            self.open_file_btn.setEnabled(True)
            self.retry_btn.setVisible(True)
            self._record_history()
            name = os.path.basename(self.last_file)
            self.stage_label.setText(f"视频已完成（部分附加项失败）· {name}")
            self.metrics_label.setText("")
            self._append_log("== 视频已产出，但字幕/封面等附加项有报错 ==")
            self._set_status("完成，但附加项有失败")
            return

        if self._cancel_requested:
            self._cancel_requested = False
            self.stage_label.setText("已取消（临时文件已保留，可续传）")
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.metrics_label.setText("")
            self._set_status("已取消")
            self._append_log(
                "# 已终止进程。已下载的分片保留为 .part/.ytdl，"
                "同一组合下次下载会自动续传；要清理请到 设置 → 清理临时文件"
            )
            return

        err = engine.translate_error(tail)
        self.stage_label.setText(f"失败：{err.message}")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.metrics_label.setText("")
        self._set_status("下载失败")

        if (
            "403" in tail
            and not self.cfg.get("cookies_browser")
            and not self.cfg.get("cookies_file")
        ):
            answer = QMessageBox.question(
                self,
                "遇到 403",
                f"{err.message}\n\n{err.hint}\n\n是否改用 Chrome Cookie 重试？\n"
                "（请先完全退出 Chrome，否则读取会失败）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.cfg["cookies_browser"] = "chrome"
                save_config(self.cfg)
                self._refresh_deps_ui()
                self._append_log("# 已切换到 Chrome Cookie，准备重试")
                QTimer.singleShot(200, self._start_download)
                return

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("下载失败")
        box.setText(err.message)
        box.setInformativeText(err.hint or tail[-600:])
        box.setDetailedText(tail[-2000:])
        box.exec()

    def _on_cancel(self) -> None:
        if self._dl_thread is None:
            return
        self._cancel_requested = True
        self.stage_label.setText("正在取消…")
        self._append_log("# 正在取消下载…")
        self._dl_thread.stop()

    def _on_retry_other(self) -> None:
        self.video_table.setFocus()
        self.video_table.scrollToTop()
        self._set_status("选另一个画质/编码，再点「开始下载」即可")
        self.retry_btn.setVisible(False)

    def _on_redownload(self) -> None:
        self._force_download = True
        self.redownload_btn.setVisible(False)
        self._start_download()

    def _record_history(self) -> None:
        if not self._pending or not self.last_file:
            return
        history.record(
            key=self._pending["key"],
            video_id=self._pending["video_id"],
            title=self._pending["title"],
            video_format=self._pending["video_format"],
            audio_format=self._pending["audio_format"],
            container=self._pending["container"],
            path=self.last_file,
            url=self._pending.get("url", ""),
        )
        self._pending = {}

    def _open_history(self) -> None:
        from .history_dialog import HistoryDialog

        HistoryDialog(self).exec()

    def _on_open_file(self) -> None:
        if self.last_file and os.path.isfile(self.last_file):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_file))
            return
        self._on_open_folder()

    def _on_open_folder(self) -> None:
        path = self.dir_edit.text().strip().strip('"')
        if not path or not os.path.isdir(path):
            path = self.cfg.get("download_dir") or os.path.expanduser("~")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ #
    # 引擎更新 / 连通性 / 设置
    # ------------------------------------------------------------------ #
    def _check_version_async(self) -> None:
        self._version_thread = VersionCheckThread(self.cfg)
        self._version_thread.found.connect(self._on_version_found)
        self._version_thread.start()

    def _on_version_found(self, latest: str) -> None:
        self.latest_version = latest
        current = self.deps.ytdlp_version if self.deps else ""
        if engine.is_newer(latest, current):
            self.new_version_badge.setText(f"新版本 {latest}")
            self.new_version_badge.setVisible(True)
            self.new_version_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self._version_thread = None

    def _on_update_clicked(self) -> None:
        if self._dl_thread is not None:
            QMessageBox.warning(
                self, "有任务在跑", "正在下载时更新引擎会导致替换失败。请先等下载完成或取消后再更新。"
            )
            return
        if self.deps is None or not self.deps.ytdlp:
            QMessageBox.warning(self, "找不到引擎", "请先在设置里指定 yt-dlp.exe 路径。")
            return
        if self._update_thread is not None:
            return

        target = self.latest_version or "最新版"
        answer = QMessageBox.question(
            self,
            "更新引擎",
            f"当前版本：{self.deps.ytdlp_version or '未知'}\n最新版本：{target}\n\n"
            "更新会下载并替换程序目录下的 yt-dlp.exe，需要联网（走当前代理）。继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.update_btn.setEnabled(False)
        self.update_btn.setText("更新中…")
        self._append_log("# 正在更新引擎…")
        self._update_thread = UpdateThread(self.cfg, self.deps)
        self._update_thread.finished_msg.connect(self._on_update_done)
        self._update_thread.start()

    def _on_update_done(self, code: int, output: str) -> None:
        self._update_thread = None
        self.update_btn.setEnabled(True)
        self.update_btn.setText("引擎更新")
        self._append_log(output)

        self.deps = engine.detect_deps(self.cfg)
        self._refresh_deps_ui()

        if code == 0:
            self.new_version_badge.setVisible(False)
            QMessageBox.information(
                self, "更新完成", f"引擎已更新到 {self.deps.ytdlp_version or '新版本'}。"
            )
        else:
            QMessageBox.warning(self, "更新失败", output[-800:] or "引擎返回了非零状态码。")

    def _on_test_connect(self) -> None:
        if self._connect_thread is not None:
            return
        self.connect_btn.setEnabled(False)
        self.connect_btn.setText("测试中…")
        self._connect_thread = ConnectThread(self.cfg)
        self._connect_thread.result.connect(self._on_connect_result)
        self._connect_thread.start()

    def _on_connect_result(self, ok: bool, message: str) -> None:
        self._connect_thread = None
        self.connect_btn.setEnabled(True)
        self.connect_btn.setText("测试连通")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information if ok else QMessageBox.Icon.Warning)
        box.setWindowTitle("连通性测试")
        box.setText(message)
        if not ok:
            box.setInformativeText("可到设置里检查代理模式与地址，或关闭代理直连再试。")
        box.exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg, self)
        if dialog.exec():
            self.cfg = dialog.cfg
            save_config(self.cfg)
            self.deps = engine.detect_deps(self.cfg)
            self._refresh_deps_ui()
            self._append_log("# 设置已保存")
            if self.cfg.get("check_update", True):
                self._check_version_async()

    # ------------------------------------------------------------------ #
    # 拖拽 / 关闭
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        text = event.mimeData().text().strip()
        if text:
            self.url_edit.setText(text)
            self._on_parse()

    def _restore_geometry(self) -> None:
        raw = self.cfg.get("window_geometry") or ""
        if raw:
            try:
                self.restoreGeometry(base64.b64decode(raw.encode("ascii")))
                # 恢复的尺寸可能小于最小尺寸，那会让两张表挤到重叠
                self.resize(
                    max(self.width(), self.minimumWidth()),
                    max(self.height(), self.minimumHeight()),
                )
                return
            except Exception:  # noqa: BLE001
                pass
        self.resize(900, 880)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._dl_thread is not None:
            answer = QMessageBox.question(
                self,
                "还有下载在进行",
                "关闭窗口会中止当前下载，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._dl_thread.stop()
            self._dl_thread.wait(3000)

        try:
            self.cfg["window_geometry"] = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            save_config(self.cfg)
        except Exception:  # noqa: BLE001
            pass
        event.accept()
