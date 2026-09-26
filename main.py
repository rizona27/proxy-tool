"""代理切换工具 — 入口模块（纯标准库，无第三方依赖）

依赖：Python 3.8+ 自带的 tkinter（Windows 官方安装包默认包含）
"""
import ctypes
import os
import subprocess
import sys

APP_NAME = "ProxyTool"
MUTEX_NAME = "Global\\ProxyTool_SingleInstance_v3"


# ── 权限 ──

def is_admin() -> bool:
    """检查是否具备管理员权限"""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def run_as_admin():
    """以管理员权限重新启动自己（保留命令行参数）"""
    exe = sys.executable if getattr(sys, "frozen", False) \
        else os.path.abspath(sys.argv[0])
    params = subprocess.list2cmdline(sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)


# ── 单实例 ──

class SingleInstance:
    """Windows 命名互斥锁：确保只有一个实例运行。

    句柄作为属性持有直到进程结束，避免被 GC 提前关闭导致互斥失效。
    """

    def __init__(self, name: str = MUTEX_NAME):
        self._handle = None
        self._name = name

    def acquire(self) -> bool:
        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        self._handle = kernel32.CreateMutexW(None, False, self._name)
        if not self._handle:
            return True                      # 拿不到句柄时不阻塞用户
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(self._handle)
            self._handle = None
            return False
        return True

    def release(self):
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None


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
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, APP_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return os.path.join(os.path.expanduser("~"), "ProxyTool_error.log")
    return os.path.join(folder, "error.log")


def install_excepthook():
    """安装全局异常处理器。

    这是修复「Failed to obtain/convert traceback!」的关键：
    PyInstaller 的 windowed 模式没有控制台，一旦异常逃逸出解释器，
    引导程序无法把 traceback 序列化到 stderr，就会弹出这句无信息的报错。
    这里主动捕获并写入日志文件 + 弹窗，保证任何崩溃都可定位。
    """
    import traceback

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
            ctypes.windll.user32.MessageBoxW(
                0,
                f"程序遇到未处理的错误：\n\n{exc_type.__name__}: {exc_value}\n\n"
                f"详细信息已写入：\n{path}",
                f"{APP_NAME} 错误", 0x10)
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

    if not check_tkinter():
        ctypes.windll.user32.MessageBoxW(
            0,
            "当前 Python 环境缺少 tkinter 模块。\n\n"
            "请使用 python.org 官方安装包（勾选 tcl/tk 组件），"
            "或改用打包好的 exe。",
            "缺少依赖", 0x30)
        return 1

    if not is_admin():
        run_as_admin()
        return 0

    instance = SingleInstance()
    if not instance.acquire():
        ctypes.windll.user32.MessageBoxW(
            0,
            "代理切换工具已在运行中（系统托盘）。\n请双击托盘图标恢复窗口。",
            "提示", 0x40)
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
