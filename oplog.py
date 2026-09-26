"""操作日志模块 —— 纯标准库实现，倒序记录（最新在最前）。

设计要点
  · 单一文本文件，UTF-8，`.txt` 后缀
  · **倒序**：新纪录写在文件头部，打开即可看到最新操作
  · 每行格式：`[YYYY-MM-DD HH:MM:SS] [级别] 内容`
  · 默认路径与 exe 同目录；可在界面上自定义
  · 写入失败静默降级，绝不影响主功能

为什么不用 logging 模块
  标准 logging 是追加式（正序），与本需求「最新在最前」相反；
  且需要自行管理 handler 生命周期。这里直接把整文件重写，
  日志量级（数千行）下开销可忽略。
"""
import os
import sys
import threading
from datetime import datetime

# ── 级别 ──
LV_INFO = "INFO"
LV_OK = "OK  "
LV_WARN = "WARN"
LV_ERR = "ERR "

# 文件头分隔线（首次创建时写入）
_HEADER = (
    "=========================================================\n"
    " 代理切换工具 操作日志\n"
    " 格式：[时间] [级别] 内容    ※ 倒序，最新在最前\n"
    "=========================================================\n"
)

# 单文件最大行数，超出时截断尾部（保留最新）
MAX_LINES = 5000

_lock = threading.Lock()


def default_log_dir() -> str:
    """默认日志目录。

    Windows：exe（或脚本）所在目录 —— 便携，用户一眼能找到。
    macOS  ：.app 内部通常是只读签名的，写不进去；改用
             ~/Library/Logs/ProxyTool（系统约定的日志位置）。
    源码模式下统一用项目目录，方便调试。
    """
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        base = os.path.expanduser("~/Library/Logs/ProxyTool")
        try:
            os.makedirs(base, exist_ok=True)
        except OSError:
            base = os.path.expanduser("~")
        return base
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return base


def default_log_path() -> str:
    return os.path.join(default_log_dir(), "ProxyTool_log.txt")


class OperationLogger:
    """倒序操作日志。

    线程安全：内部用 RLock 串行化写入，工作线程也能安全调用。
    """

    def __init__(self, enabled: bool = False, path: str = ""):
        self._enabled = bool(enabled)
        self._path = path or default_log_path()

    # ── 属性 ──

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> str:
        return self._path

    def set_enabled(self, enabled: bool):
        self._enabled = bool(enabled)
        if self._enabled:
            # 立即落一条开启记录，同时确保文件被创建
            self.log("日志记录已开启", LV_INFO)

    def set_path(self, path: str):
        """切换日志文件路径（不搬迁已写内容）"""
        path = (path or "").strip().strip('"')
        if not path:
            return False
        # 只给了目录 -> 自动补文件名
        if os.path.isdir(path) or path.endswith(("\\", "/")):
            path = os.path.join(path, "ProxyTool_log.txt")
        if not path.lower().endswith(".txt"):
            path += ".txt"
        self._path = path
        return True

    # ── 写入 ──

    def log(self, message: str, level: str = LV_INFO):
        """写一条记录。未启用时静默忽略。"""
        if not self._enabled:
            return
        line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{level}] {message}\n"
        with _lock:
            try:
                self._prepend(line)
            except OSError:
                pass                        # 日志失败不影响主功能

    # 便捷方法
    def info(self, msg):
        self.log(msg, LV_INFO)

    def ok(self, msg):
        self.log(msg, LV_OK)

    def warn(self, msg):
        self.log(msg, LV_WARN)

    def error(self, msg):
        self.log(msg, LV_ERR)

    def exception(self, where: str, exc: BaseException):
        """记录异常（含类型与消息），供 UI 回调兜底使用"""
        import traceback
        detail = "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.log(f"{where} 抛出异常:\n{detail.rstrip()}", LV_ERR)

    # ── 内部 ──

    def _prepend(self, line: str):
        """把新行插到文件正文最前面（即日志头的分隔线之后）"""
        path = self._path
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)

        old = ""
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    old = f.read()
            except OSError:
                old = ""

        if not old:
            body = _HEADER + line
        else:
            # 已有内容：把新行插到文件头之后、旧正文之前
            if old.startswith(_HEADER):
                head, bodypart = _HEADER, old[len(_HEADER):]
            else:
                head, bodypart = "", old
            body = head + line + bodypart

        # 控制体积：超出上限时只保留最新的部分
        lines = body.splitlines(keepends=True)
        head_lines = len(_HEADER.splitlines(keepends=True))
        if len(lines) > MAX_LINES:
            lines = lines[:head_lines + MAX_LINES]
            body = "".join(lines)

        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        os.replace(tmp, path)

    def read(self, limit: int = 200) -> str:
        """读取日志内容（倒序文件本身就是最新在前），用于「打开日志」预览"""
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:limit * 200]
        except OSError:
            return ""
