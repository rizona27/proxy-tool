"""代理切换工具 — 入口模块

依赖：Python 3.10+ 自带的 tkinter。
跨平台：Windows / macOS 均可运行，平台差异收敛在 platform_ops 里。
"""
import os
import sys

APP_NAME = "ProxyTool"


# ── 前置检查 ──

def check_tkinter() -> bool:
    """确认 tkinter 可用（部分精简版 Python 会剥离它）"""
    try:
        import tkinter  # noqa: F401
        return True
    except ImportError:
        return False


# ── 崩溃日志 ──

def log_path() -> str:
    import platform_ops
    return os.path.join(platform_ops.log_dir(APP_NAME), "error.log")


def install_excepthook():
    """安装全局异常处理器。

    这是修复「Failed to obtain/convert traceback!」的关键：
    PyInstaller 的 windowed 模式没有控制台，一旦异常逃逸出解释器，
    引导程序无法把 traceback 序列化到 stderr，就会弹出这句无信息的报错。
    这里主动捕获并写入日志文件 + 弹窗，保证任何崩溃都可定位。
    """
    import traceback
    import platform_ops

    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        path = log_path()
        try:
            with open(path, "a", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"\n{'=' * 60}\n{datetime.now():%Y-%m-%d %H:%M:%S}\n")
                f.write(detail)
        except OSError:
            path = "(日志写入失败)"
        try:
            platform_ops.message_box(
                f"程序遇到未处理的错误：\n\n{exc_type.__name__}: {exc_value}\n\n"
                f"详细信息已写入：\n{path}",
                title=f"{APP_NAME} 错误", kind="error")
        except Exception:
            pass

    sys.excepthook = handle

    # 线程内的异常同样要捕获，否则会静默消失
    def thread_hook(args):
        handle(args.exc_type, args.exc_value, args.exc_traceback)

    try:
        import threading
        threading.excepthook = thread_hook
    except (AttributeError, ImportError):
        pass


def main():
    install_excepthook()

    import platform_ops

    if not check_tkinter():
        platform_ops.message_box(
            "当前 Python 环境缺少 tkinter 模块。\n\n"
            "请使用 python.org 官方安装包（含 tcl/tk 组件），"
            "或改用打包好的安装包。",
            title="缺少依赖", kind="warn")
        return 1

    # Windows 需要管理员权限才能可靠刷新 WinInet 代理；macOS 不需要提权
    if platform_ops.IS_WINDOWS and not platform_ops.is_admin():
        platform_ops.elevate()
        return 0

    instance = platform_ops.SingleInstance(APP_NAME)
    if not instance.acquire():
        platform_ops.message_box(
            "代理切换工具已在运行中。\n请从托盘图标恢复窗口。",
            title="提示", kind="info")
        return 0

    try:
        from main_window import ProxyTool
        ProxyTool().run()
    except Exception:
        import traceback
        try:
            with open(log_path(), "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except OSError:
            pass
        raise
    finally:
        instance.release()
    return 0


if __name__ == "__main__":
    sys.exit(main())
