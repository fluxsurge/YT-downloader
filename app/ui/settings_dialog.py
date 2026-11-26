"""设置对话框。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import engine
from ..config import resolve_proxy

BROWSER_ITEMS = [
    ("不使用（推荐，遇到 403 再开）", ""),
    ("Chrome", "chrome"),
    ("Edge", "edge"),
    ("Firefox", "firefox"),
    ("Brave", "brave"),
]

PROXY_ITEMS = [
    ("自动读取系统代理", "auto"),
    ("手动指定", "manual"),
    ("不使用代理（直连）", "off"),
]

MANAGED_FLAGS = {
    "-f",
    "--format",
    "--merge-output-format",
    "--js-runtimes",
    "--proxy",
    "--cookies",
    "--cookies-from-browser",
    "-P",
    "--paths",
    "-o",
    "--output",
    "--no-playlist",
    "--ignore-config",
}


def _browse_row(line_edit: QLineEdit, caption: str, is_dir: bool, parent: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(line_edit, 1)
    button = QPushButton("浏览")
    button.setFixedWidth(64)

    def pick():
        if is_dir:
            path = QFileDialog.getExistingDirectory(parent, caption, line_edit.text() or os.path.expanduser("~"))
        else:
            path, _ = QFileDialog.getOpenFileName(parent, caption, line_edit.text() or os.path.expanduser("~"), "可执行文件 (*.exe);;所有文件 (*.*)")
        if path:
            line_edit.setText(os.path.normpath(path))

    button.clicked.connect(pick)
    row.addWidget(button)
    return row


class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.setWindowTitle("设置")
        self.setMinimumWidth(620)
        self._build()
        self._load()

    # ------------------------------------------------------------------ #
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        self.ytdlp_edit = QLineEdit()
        self.ytdlp_edit.setPlaceholderText("留空则使用程序目录下的 yt-dlp.exe")
        ytdlp_row = _browse_row(self.ytdlp_edit, "选择 yt-dlp.exe", False, self)
        self.ytdlp_check = QPushButton("检测版本")
        self.ytdlp_check.setFixedWidth(88)
        self.ytdlp_check.clicked.connect(self._check_ytdlp)
        ytdlp_row.addWidget(self.ytdlp_check)
        form.addRow("引擎路径", ytdlp_row)

        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setPlaceholderText("留空则使用系统 PATH 中的 ffmpeg")
        form.addRow("ffmpeg 目录", _browse_row(self.ffmpeg_edit, "选择 ffmpeg 所在目录", True, self))

        self.deno_edit = QLineEdit()
        self.deno_edit.setPlaceholderText("留空则使用系统 PATH 中的 deno")
        form.addRow("deno 路径", _browse_row(self.deno_edit, "选择 deno.exe", False, self))

        self.proxy_combo = QComboBox()
        for label, value in PROXY_ITEMS:
            self.proxy_combo.addItem(label, value)
        self.proxy_combo.currentIndexChanged.connect(self._sync_proxy_state)
        form.addRow("代理模式", self.proxy_combo)

        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("例如 http://127.0.0.1:7890 或 socks5://127.0.0.1:7891")
        form.addRow("代理地址", self.proxy_edit)

        self.cookie_combo = QComboBox()
        for label, value in BROWSER_ITEMS:
            self.cookie_combo.addItem(label, value)
        self.cookie_combo.currentIndexChanged.connect(self._sync_cookie_state)
        form.addRow("Cookie 来源", self.cookie_combo)

        self.cookie_file_edit = QLineEdit()
        self.cookie_file_edit.setPlaceholderText("可选：Netscape 格式 cookies.txt，填了会优先于上面的浏览器")
        form.addRow("cookies.txt", _browse_row(self.cookie_file_edit, "选择 cookies.txt", False, self))

        self.frag_spin = QSpinBox()
        self.frag_spin.setRange(1, 16)
        self.frag_spin.setFixedWidth(92)
        form.addRow("分片并发数", self.frag_spin)

        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("%(title)s.%(ext)s")
        self.template_edit.setToolTip(
            "保持默认即可：程序会自动在标题后加「.2160p.VP9」这类版本标签，同一视频的不同版本不会撞名。\n"
            "一旦改成别的模板，就完全按你写的来，不再自动加标签（撞名时 yt-dlp 会跳过）。"
        )
        form.addRow("文件名模板", self.template_edit)

        self.retry_check = QCheckBox("无限重试（4K 大文件建议开启）")
        form.addRow("重试策略", self.retry_check)

        self.update_check = QCheckBox("启动时检查引擎新版本（不会自动安装）")
        form.addRow("更新检查", self.update_check)

        subs_row = QHBoxLayout()
        subs_row.setSpacing(8)
        self.subs_edit = QLineEdit()
        self.subs_edit.setPlaceholderText("zh-Hans,zh-Hant,en")
        self.subs_edit.setToolTip("yt-dlp 语法，逗号分隔，支持正则。\n用精确语言码（zh-Hans/zh-Hant）比 zh.* 更干净，不会抓到 zh-Hans-es-419 这类自动翻译组合")
        subs_row.addWidget(self.subs_edit, 1)
        form.addRow("字幕语言", subs_row)

        self.extra_edit = QLineEdit()
        self.extra_edit.setPlaceholderText("透传给 yt-dlp 的额外参数，例如 --limit-rate 4M")
        extra_row = QHBoxLayout()
        extra_row.setSpacing(8)
        extra_row.addWidget(self.extra_edit, 1)
        import_btn = QPushButton("从 conf 导入")
        import_btn.setFixedWidth(110)
        import_btn.clicked.connect(self._import_conf)
        extra_row.addWidget(import_btn)
        form.addRow("高级参数", extra_row)

        cleanup_row = QHBoxLayout()
        cleanup_row.setSpacing(8)
        self.cleanup_btn = QPushButton("清理临时文件")
        self.cleanup_btn.setToolTip(
            "扫描下载目录里的 .part / .ytdl 残留。\n"
            "这些文件是取消下载后留下的，保留可让下次同组合续传；\n"
            "删除后本次进度会丢失。"
        )
        self.cleanup_btn.clicked.connect(self._cleanup_temp)
        cleanup_row.addWidget(self.cleanup_btn)
        cleanup_hint = QLabel("清理 .part / .ytdl 残留（会丢失续传进度）")
        cleanup_hint.setObjectName("Hint")
        cleanup_row.addWidget(cleanup_hint, 1)
        form.addRow("维护", cleanup_row)

        root.addLayout(form)

        self.hint_label = QLabel()
        self.hint_label.setObjectName("Hint")
        self.hint_label.setWordWrap(True)
        root.addWidget(self.hint_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("Primary")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        self.ytdlp_edit.setText(self.cfg.get("ytdlp_path", ""))
        self.ffmpeg_edit.setText(self.cfg.get("ffmpeg_dir", ""))
        self.deno_edit.setText(self.cfg.get("deno_path", ""))
        self._set_combo(self.proxy_combo, self.cfg.get("proxy_mode", "auto"))
        self.proxy_edit.setText(self.cfg.get("proxy_url", ""))
        self._set_combo(self.cookie_combo, self.cfg.get("cookies_browser", ""))
        self.cookie_file_edit.setText(self.cfg.get("cookies_file", ""))
        self.frag_spin.setValue(int(self.cfg.get("concurrent_fragments") or 8))
        self.template_edit.setText(self.cfg.get("output_template") or "%(title)s.%(ext)s")
        self.retry_check.setChecked(bool(self.cfg.get("infinite_retry", True)))
        self.update_check.setChecked(bool(self.cfg.get("check_update", True)))
        self.extra_edit.setText(self.cfg.get("extra_args", ""))
        self.subs_edit.setText(self.cfg.get("sub_langs", "zh-Hans,zh-Hant,en") or "")
        self._sync_proxy_state()
        self._sync_cookie_state()

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _sync_proxy_state(self) -> None:
        manual = self.proxy_combo.currentData() == "manual"
        self.proxy_edit.setEnabled(manual)
        if manual:
            self.hint_label.setText("手动模式下代理地址不会被自动替换；换端口需要回来改。")
        elif self.proxy_combo.currentData() == "auto":
            actual = resolve_proxy(self.cfg) or "未检测到系统代理"
            self.hint_label.setText(f"自动模式：当前系统代理为 {actual}。若代理软件已关闭但这里仍有地址，请求会直接失败。")
        else:
            self.hint_label.setText("直连模式：国内网络通常无法访问 YouTube。")

    def _sync_cookie_state(self) -> None:
        has_browser = bool(self.cookie_combo.currentData())
        self.cookie_file_edit.setEnabled(True)
        if has_browser:
            self.hint_label.setText(
                "注意：读取浏览器 Cookie 前必须完全退出该浏览器，否则数据库被锁定会失败；"
                "且该方式会以你的账号身份请求，存在被限流的风险。"
            )

    # ------------------------------------------------------------------ #
    def _check_ytdlp(self) -> None:
        path = self.ytdlp_edit.text().strip().strip('"')
        if not path:
            path = engine.find_ytdlp(self.cfg)
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "找不到引擎", "指定的路径不存在，请重新选择 yt-dlp.exe。")
            return
        version = engine._read_version(path)
        if version:
            QMessageBox.information(self, "引擎可用", f"路径：{path}\n版本：{version}")
        else:
            QMessageBox.warning(self, "引擎无法运行", f"文件存在但无法执行：\n{path}")

    def _import_conf(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 yt-dlp.conf",
            os.path.expanduser("~/Desktop"),
            "配置文件 (*.conf *.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                raw_lines = fh.readlines()
        except Exception as exc:
            QMessageBox.warning(self, "读取失败", str(exc))
            return

        kept: list[str] = []
        skipped: list[str] = []
        for line in raw_lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            flag = line.split()[0]
            if flag in MANAGED_FLAGS:
                skipped.append(flag)
                continue
            kept.append(line)

        if kept:
            merged = (self.extra_edit.text().strip() + " " + " ".join(kept)).strip()
            self.extra_edit.setText(merged)

        message = f"已导入 {len(kept)} 条参数到「高级参数」。"
        if skipped:
            message += "\n\n以下参数由界面接管，已忽略：" + "、".join(sorted(set(skipped)))
        QMessageBox.information(self, "导入完成", message)

    def _cleanup_temp(self) -> None:
        out_dir = (self.cfg.get("download_dir") or "").strip()
        if not out_dir or not os.path.isdir(out_dir):
            QMessageBox.information(self, "目录不存在", "当前下载目录不存在，先在主界面选一个。")
            return
        targets = []
        for name in os.listdir(out_dir):
            low = name.lower()
            if low.endswith((".part", ".ytdl", ".part-frag")):
                full = os.path.join(out_dir, name)
                if os.path.isfile(full):
                    targets.append(full)
        if not targets:
            QMessageBox.information(
                self, "没有残留", f"{out_dir}\n\n里面没有 .part / .ytdl 临时文件。"
            )
            return
        total = 0
        for path in targets:
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        answer = QMessageBox.question(
            self,
            "清理临时文件",
            f"在\n{out_dir}\n找到 {len(targets)} 个临时文件，共 {engine.human_size(total)}。\n\n"
            "删除后这些下载将无法续传，确定删除吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = 0
        failed = 0
        for path in targets:
            try:
                os.remove(path)
                removed += 1
            except OSError:
                failed += 1
        message = f"已删除 {removed} 个临时文件。"
        if failed:
            message += f"\n{failed} 个删除失败（可能仍被占用）。"
        QMessageBox.information(self, "清理完成", message)

    # ------------------------------------------------------------------ #
    def accept(self) -> None:
        self.cfg["ytdlp_path"] = self.ytdlp_edit.text().strip().strip('"')
        self.cfg["ffmpeg_dir"] = self.ffmpeg_edit.text().strip().strip('"')
        self.cfg["deno_path"] = self.deno_edit.text().strip().strip('"')
        self.cfg["proxy_mode"] = self.proxy_combo.currentData() or "auto"
        self.cfg["proxy_url"] = self.proxy_edit.text().strip()
        self.cfg["cookies_browser"] = self.cookie_combo.currentData() or ""
        self.cfg["cookies_file"] = self.cookie_file_edit.text().strip().strip('"')
        self.cfg["concurrent_fragments"] = self.frag_spin.value()
        self.cfg["output_template"] = self.template_edit.text().strip() or "%(title)s.%(ext)s"
        self.cfg["infinite_retry"] = self.retry_check.isChecked()
        self.cfg["check_update"] = self.update_check.isChecked()
        self.cfg["sub_langs"] = self.subs_edit.text().strip() or "zh-Hans,zh-Hant,en"
        self.cfg["extra_args"] = self.extra_edit.text().strip()
        super().accept()
