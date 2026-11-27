"""程序入口。"""
from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.branding import app_icon, chevron_path  # noqa: E402
from app.config import app_dir, load_config  # noqa: E402
from app.theme import build_qss  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402


def _install_excepthook() -> None:
    """打包成无控制台的 exe 后，异常默认无处可见。

    这里把 traceback 写到 exe 同级的 startup_error.log，并尽量弹个框，
    否则用户只会看到「双击没反应」。
    """

    def hook(exc_type, exc, tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_path = os.path.join(app_dir(), "startup_error.log")
        try:
            with open(log_path, "w", encoding="utf-8") as fh:
                fh.write(text)
        except Exception:  # noqa: BLE001
            log_path = "（无法写入日志）"
        try:
            from PySide6.QtWidgets import QMessageBox

            if QApplication.instance() is None:
                QApplication([])
            QMessageBox.critical(
                None,
                "出错了",
                f"{exc_type.__name__}: {exc}\n\n详细信息见：\n{log_path}",
            )
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def _focus_existing_window() -> bool:
    """把已经打开的窗口拉到前台。标题会变（解析后带视频名），所以用包含匹配。"""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "YT 下载器" in buf.value:
                    found.append(hwnd)
                    return False
            return True

        user32.EnumWindows(callback_type(_enum), 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:  # noqa: BLE001
        return False


def _acquire_single_instance():
    """拿不到锁说明已有实例在跑；尝试唤醒它并让新进程退出。

    多开最直接的危害是两个进程同时写 config.json / history.json。
    """
    from PySide6.QtCore import QLockFile

    lock = QLockFile(os.path.join(app_dir(), "app.lock"))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    _focus_existing_window()
    return None


def _make_splash():
    """启动图：Windows 字体库初始化要 1.4 秒，先用纯图形遮住这段空窗。

    注意这里不能画文字——drawText 同样会触发字体库初始化，等于没遮。
    """
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QPainter, QPixmap
    from PySide6.QtWidgets import QSplashScreen

    width, height = 360, 200
    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(QColor("#E5E5E5"))
    painter.drawRoundedRect(QRectF(0.5, 0.5, width - 1, height - 1), 12, 12)
    icon = app_icon().pixmap(96, 96)
    painter.drawPixmap((width - 96) // 2, (height - 96) // 2 - 6, icon)
    painter.end()

    splash = QSplashScreen(pix)
    splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    splash.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    return splash


def main() -> int:
    _install_excepthook()

    lock = _acquire_single_instance()
    if lock is None:
        return 0

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ytdlp.gui.1")
        except Exception:  # noqa: BLE001
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("YT 下载器")
    app.setApplicationDisplayName("YT 下载器")
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(build_qss(chevron_path()))

    splash = _make_splash()
    splash.show()
    app.processEvents()

    window = MainWindow(load_config())
    window.show()
    splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
