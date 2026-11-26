"""品牌资源：图标加载与回退绘制。"""
from __future__ import annotations

import os

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .config import app_dir

BRAND = QColor("#FF0000")
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def icon_path() -> str:
    return os.path.join(app_dir(), "assets", "icon.ico")


def _paint(size: int) -> QPixmap:
    """与 tools/make_icon.py 保持一致的绘制逻辑，作为图标文件缺失时的兜底。"""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    pad_x = size * 0.02
    height = size * 0.70
    rect = QRectF(pad_x, (size - height) / 2, size - pad_x * 2, height)
    radius = height * 0.24

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, BRAND)

    cx = size / 2 + size * 0.015
    half_w = size * 0.105
    half_h = size * 0.130
    triangle = QPainterPath()
    triangle.moveTo(QPointF(cx - half_w, size / 2 - half_h))
    triangle.lineTo(QPointF(cx - half_w, size / 2 + half_h))
    triangle.lineTo(QPointF(cx + half_w * 1.25, size / 2))
    triangle.closeSubpath()
    painter.fillPath(triangle, QColor("#FFFFFF"))
    painter.end()
    return pix


def app_icon() -> QIcon:
    path = icon_path()
    if os.path.isfile(path):
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    icon = QIcon()
    for size in SIZES:
        icon.addPixmap(_paint(size))
    return icon


def _chevron_pixmap(size: int = 32, color: str = "#6B7280") -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(size * 0.075)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(
        [
            QPointF(size * 0.28, size * 0.40),
            QPointF(size * 0.50, size * 0.61),
            QPointF(size * 0.72, size * 0.40),
        ]
    )
    painter.end()
    return pix


def chevron_path() -> str:
    """下拉箭头图片；缺失时按需生成，返回空串表示用系统默认箭头。"""
    path = os.path.join(app_dir(), "assets", "chevron_down.png")
    if not os.path.isfile(path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            _chevron_pixmap(32).save(path, "PNG")
        except Exception:  # noqa: BLE001
            return ""
    return path
