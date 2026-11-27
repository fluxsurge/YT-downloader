"""界面样式（YouTube 品牌色系，浅色主题）。

配色取自 YouTube 品牌：
  主红 #FF0000 / 悬停深红 #CC0000 / 浅红底 #FFEBEE / 正文 #0F0F0F / 次要 #606060
"""
from __future__ import annotations

BRAND = "#FF0000"
BRAND_DARK = "#CC0000"
BRAND_TINT = "#FFEBEE"
BRAND_TINT_BORDER = "#FFCDD2"
BRAND_TEXT = "#B3261E"

_TEMPLATE = """
QWidget {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
    color: #0F0F0F;
}
QMainWindow, QDialog, #Root {
    background: #FFFFFF;
}
QLabel#AppTitle {
    font-size: 15px;
    font-weight: 500;
}
QLabel#Muted {
    color: #606060;
    font-size: 12px;
}
QLabel#Hint {
    color: #909090;
    font-size: 12px;
}
QLabel#FieldLabel {
    color: #8A8A8A;
    font-size: 12px;
    padding-left: 2px;
}
QLabel#VideoTitle {
    font-size: 14px;
    font-weight: 500;
}
QLabel#Thumb {
    border: 1px solid #E5E5E5;
    border-radius: 8px;
    background: #F9F9F9;
    color: #909090;
    font-size: 12px;
}
QLabel#VersionBadge {
    color: $BRAND_TEXT;
    background: $BRAND_TINT;
    border-radius: 9px;
    padding: 2px 8px;
    font-size: 11px;
}
QFrame#Divider {
    background: #EFEFEF;
    max-height: 1px;
    border: none;
}
QFrame#VDivider {
    background: #EDEDED;
    min-width: 1px;
    max-width: 1px;
    border: none;
}
QLineEdit {
    border: 1px solid #E3E3E3;
    border-radius: 8px;
    padding: 6px 10px;
    background: #FFFFFF;
    selection-background-color: $BRAND_TINT_BORDER;
    selection-color: #7A0B0B;
}
QLineEdit:hover {
    border-color: #D2D2D2;
}
QLineEdit:focus {
    border-color: $BRAND;
}
QLineEdit:disabled {
    background: #F9F9F9;
    color: #909090;
}
QComboBox {
    border: 1px solid #E3E3E3;
    border-radius: 8px;
    padding: 5px 26px 5px 10px;
    background: #FFFFFF;
    min-height: 20px;
}
QComboBox:hover {
    border-color: #CFCFCF;
    background: #FDFDFD;
}
QComboBox:on, QComboBox:focus {
    border-color: $BRAND;
}
QComboBox:disabled {
    background: #F7F7F7;
    color: #A8A8A8;
    border-color: #ECECEC;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: none;
}
QComboBox::down-arrow {
    image: url("$CHEVRON");
    width: 11px;
    height: 11px;
}
QComboBox QAbstractItemView {
    border: 1px solid #E3E3E3;
    border-radius: 8px;
    padding: 4px;
    background: #FFFFFF;
    selection-background-color: $BRAND_TINT;
    selection-color: $BRAND_TEXT;
    outline: none;
}
QComboBox QAbstractItemView::item {
    min-height: 26px;
    padding: 2px 8px;
    border-radius: 6px;
}
QPushButton {
    border: 1px solid #E3E3E3;
    border-radius: 8px;
    padding: 6px 12px;
    background: #FFFFFF;
    color: #303030;
}
QPushButton:hover {
    background: #F5F5F5;
    border-color: #D8D8D8;
}
QPushButton:pressed {
    background: #EFEFEF;
}
QPushButton:disabled {
    color: #B0B0B0;
    background: #FBFBFB;
    border-color: #EFEFEF;
}
QPushButton#Primary {
    background: $BRAND;
    border: 1px solid $BRAND;
    color: #FFFFFF;
    font-weight: 500;
    padding: 6px 20px;
}
QPushButton#Primary:hover {
    background: $BRAND_DARK;
    border-color: $BRAND_DARK;
}
QPushButton#Primary:disabled {
    background: #FFB3B3;
    border-color: #FFB3B3;
    color: #FFFFFF;
}
QPushButton#Chip {
    border-radius: 14px;
    padding: 3px 13px;
    color: #606060;
    background: #FFFFFF;
    min-height: 20px;
}
QPushButton#Chip:hover {
    background: #F5F5F5;
    border-color: #D8D8D8;
}
QPushButton#Chip:checked {
    background: $BRAND_TINT;
    border-color: $BRAND_TINT_BORDER;
    color: $BRAND_TEXT;
    font-weight: 500;
}
QPushButton#Chip:disabled {
    color: #C6C6C6;
    border-color: #EFEFEF;
    background: #FCFCFC;
}
QPushButton#Link {
    border: none;
    background: transparent;
    color: $BRAND_DARK;
    padding: 3px 6px;
}
QPushButton#Link:hover {
    color: #990000;
    background: #FFF3F3;
    border-radius: 6px;
}
QTableWidget {
    border: 1px solid #EDEDED;
    border-radius: 8px;
    background: #FFFFFF;
    alternate-background-color: #FBFBFB;
    outline: none;
}
QTableWidget::item {
    padding: 2px 6px;
    border: none;
}
QLabel#Phase {
    color: #B0B0B0;
    font-size: 12px;
}
QLabel#Phase[state="current"] {
    color: $BRAND;
    font-weight: 600;
}
QLabel#Phase[state="done"] {
    color: #1E8E3E;
}
QLabel#PhaseArrow {
    color: #DADADA;
    font-size: 12px;
}

QTableWidget::item:selected {
    background: #FFD6D6;
    color: #8B0000;
}
QTableWidget:disabled {
    background: #FBFBFB;
    border-color: #F0F0F0;
}
QTableWidget:disabled::item {
    color: #BEBEBE;
}
QTableWidget:disabled::item:selected {
    background: #F2F2F2;
    color: #AFAFAF;
}
QHeaderView::section {
    background: #F9F9F9;
    border: none;
    border-bottom: 1px solid #EDEDED;
    padding: 6px 8px;
    color: #606060;
    font-size: 12px;
    font-weight: 400;
}
QProgressBar {
    border: none;
    border-radius: 3px;
    background: #EFEFEF;
    max-height: 6px;
    min-height: 6px;
}
QProgressBar::chunk {
    border-radius: 3px;
    background: $BRAND;
}
QPlainTextEdit#Log {
    border: 1px solid #EDEDED;
    border-radius: 8px;
    background: #FAFAFA;
    padding: 6px;
    selection-background-color: $BRAND_TINT_BORDER;
    selection-color: #7A0B0B;
}
QStatusBar {
    background: #F9F9F9;
    border-top: 1px solid #EDEDED;
    color: #606060;
    font-size: 12px;
}
QStatusBar::item {
    border: none;
}
QCheckBox {
    spacing: 8px;
}
QSpinBox {
    border: 1px solid #E3E3E3;
    border-radius: 8px;
    padding: 4px 6px;
    background: #FFFFFF;
}
QSpinBox:focus {
    border-color: $BRAND;
}
QScrollBar:vertical {
    width: 8px;
    background: transparent;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #D9D9D9;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #BDBDBD;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    height: 8px;
    background: transparent;
}
QScrollBar::handle:horizontal {
    background: #D9D9D9;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
"""


def build_qss(chevron: str = "") -> str:
    """生成样式表；chevron 为空时退回系统默认下拉箭头。"""
    qss = _TEMPLATE
    if chevron:
        qss = qss.replace("$CHEVRON", chevron.replace("\\", "/"))
    else:
        qss = qss.replace('    image: url("$CHEVRON");\n    width: 11px;\n    height: 11px;\n', "")
    return (
        qss.replace("$BRAND_TINT_BORDER", BRAND_TINT_BORDER)
        .replace("$BRAND_TINT", BRAND_TINT)
        .replace("$BRAND_TEXT", BRAND_TEXT)
        .replace("$BRAND_DARK", BRAND_DARK)
        .replace("$BRAND", BRAND)
    )


QSS = build_qss()
