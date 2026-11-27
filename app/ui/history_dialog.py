"""下载历史窗口。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import history


class HistoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("下载历史")
        self.resize(820, 480)
        self._build()
        self._reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        hint = QLabel(
            "同一个「视频 + 音频 + 容器」组合只会记录一条；双击可直接打开文件。\n"
            "删除单条或清空只移除记录，不会删除本地已下载的视频文件。"
        )
        hint.setObjectName("Hint")
        root.addWidget(hint)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["时间", "标题", "组合", "文件"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 142)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(2, 176)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 300)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.cellDoubleClicked.connect(lambda *_: self._open_file())
        root.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.open_btn = QPushButton("打开文件")
        self.open_btn.clicked.connect(self._open_file)
        buttons.addWidget(self.open_btn)

        self.folder_btn = QPushButton("所在文件夹")
        self.folder_btn.clicked.connect(self._open_folder)
        buttons.addWidget(self.folder_btn)

        buttons.addStretch(1)

        self.remove_btn = QPushButton("删除选中")
        self.remove_btn.clicked.connect(self._remove_selected)
        buttons.addWidget(self.remove_btn)

        self.clear_btn = QPushButton("清空")
        self.clear_btn.clicked.connect(self._clear_all)
        buttons.addWidget(self.clear_btn)

        close_btn = QPushButton("关闭")
        close_btn.setObjectName("Primary")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    # ------------------------------------------------------------------ #
    def _reload(self) -> None:
        entries = list(reversed(history.load()))
        self._entries = entries
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            path = entry.get("path") or ""
            exists = bool(path) and os.path.isfile(path)
            cells = [
                entry.get("time") or "",
                entry.get("title") or "",
                history.combo_text(entry),
                os.path.basename(path) if path else "（无）",
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 0:
                    item.setForeground(QColor("#9AA0A6"))
                if col == 3 and not exists:
                    item.setForeground(QColor("#C0392B"))
                    item.setToolTip("文件已不在原位置")
                if col == 1:
                    item.setToolTip(entry.get("title") or "")
                if col == 3:
                    item.setToolTip(path or "（无）")
                self.table.setItem(row, col, item)

        if not entries:
            self.table.setRowCount(0)

    def _current_entry(self) -> dict | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _open_file(self) -> None:
        entry = self._current_entry()
        if not entry:
            return
        path = entry.get("path") or ""
        if path and os.path.isfile(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            QMessageBox.information(self, "文件不在了", "这个文件已不在原来的位置。")

    def _open_folder(self) -> None:
        entry = self._current_entry()
        if not entry:
            return
        path = entry.get("path") or ""
        folder = os.path.dirname(path) if path else ""
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QMessageBox.information(self, "目录不在了", "原目录已不存在。")

    def _remove_selected(self) -> None:
        entry = self._current_entry()
        if not entry:
            return
        history.remove(entry.get("key", ""))
        self._reload()

    def _clear_all(self) -> None:
        if not self._entries:
            return
        answer = QMessageBox.question(
            self,
            "清空历史",
            f"确定清空 {len(self._entries)} 条历史记录吗？\n（只删记录，不会删除已下载的文件）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            history.clear()
            self._reload()
