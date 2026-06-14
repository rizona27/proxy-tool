"""代理切换工具 — 入口模块"""
import sys
import os
import subprocess
import ctypes
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QPalette, QColor

from main_window import ProxyTool


def is_admin():
    """检查管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def run_as_admin():
    """以管理员权限运行（传递命令行参数）"""
    if getattr(sys, 'frozen', False):
        application_path = sys.executable
    else:
        application_path = sys.argv[0]
    params = subprocess.list2cmdline(sys.argv[1:]) if len(sys.argv) > 1 else ""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", application_path, params, None, 1)


def is_single_instance() -> bool:
    """Windows 命名互斥锁：确保只有一个实例运行，返回 True 表示可以继续"""
    import ctypes.wintypes
    mutex_name = "Global\\ProxyTool_SingleInstance_2025"
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
        return False
    return True


if __name__ == "__main__":
    if not is_admin():
        run_as_admin()
        sys.exit(0)

    if not is_single_instance():
        ctypes.windll.user32.MessageBoxW(0,
            "代理切换工具已在运行中（系统托盘）。\n请双击托盘图标或右键打开。", "提示", 0x40)
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#edeae4"))
    palette.setColor(QPalette.WindowText, QColor("#4a4947"))
    palette.setColor(QPalette.Base, QColor("#faf8f5"))
    palette.setColor(QPalette.AlternateBase, QColor("#f5f2ed"))
    palette.setColor(QPalette.ToolTipBase, QColor("#faf8f5"))
    palette.setColor(QPalette.ToolTipText, QColor("#8a8885"))
    palette.setColor(QPalette.Text, QColor("#4a4947"))
    palette.setColor(QPalette.Button, QColor("#faf8f5"))
    palette.setColor(QPalette.ButtonText, QColor("#4a4947"))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#8b9eb0"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)

    window = ProxyTool()
    window.show()

    sys.exit(app.exec_())
