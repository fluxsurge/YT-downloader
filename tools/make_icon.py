"""生成应用图标：YouTube 风格红色圆角播放键。

用法：python tools/make_icon.py
输出：assets/icon.ico（多尺寸）、assets/icon.png（256px，供界面预览用）
"""
from __future__ import annotations

import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
BRAND = QColor("#FF0000")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def render(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # 红色圆角底板：高度约占 70%，圆角按高度比例
    pad_x = size * 0.02
    height = size * 0.70
    rect = QRectF(pad_x, (size - height) / 2, size - pad_x * 2, height)
    radius = height * 0.24

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, BRAND)

    # 白色播放三角
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


def png_bytes(pix: QPixmap) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pix.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def render_chevron(size: int = 32, color: str = "#6B7280") -> QPixmap:
    """下拉框的小箭头。"""
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


def write_ico(path: str, images: list[tuple[int, bytes]]) -> None:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = []
    payload = b""
    for size, data in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if size >= 256 else size,
                0 if size >= 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        offset += len(data)
        payload += data
    with open(path, "wb") as fh:
        fh.write(header + b"".join(entries) + payload)


def main() -> int:
    _app = QGuiApplication(sys.argv)  # noqa: F841
    os.makedirs(ASSETS, exist_ok=True)

    images = []
    for size in SIZES:
        images.append((size, png_bytes(render(size))))
    write_ico(os.path.join(ASSETS, "icon.ico"), images)

    big = render(256)
    big.save(os.path.join(ASSETS, "icon.png"), "PNG")

    render_chevron(32).save(os.path.join(ASSETS, "chevron_down.png"), "PNG")
    print("icon.ico / icon.png / chevron_down.png written:", len(images), "sizes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
