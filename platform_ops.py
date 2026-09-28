"""跨平台系统层 —— 把 Windows / macOS 的系统差异收敛到一个模块。

设计原则：
  · 上层（proxy_core / main_window / main / tray）只调用这里的统一接口，
    不再直接 import winreg 或 ctypes.windll。
  · 每个能力都提供「当前平台实现」，不可用时优雅降级（返回中性值 / no-op），
    绝不让 ImportError 冒到 UI。

支持的平台：
  · Windows —— 注册表 HKCU\\...\\Internet Settings + WinInet 刷新
  · macOS   —— networksetup / scutil 读写系统代理
  · 其它    —— 全部降级为 no-op（便于开发调试，不报错）

macOS 代理实现说明：
  macOS 的「系统代理」分两层，必须都改才能让 GUI 与命令行都生效：
    1. 网络服务层：`networksetup -setwebproxy <service> <host> <port>`
       —— 决定每个网络服务（Wi-Fi / Ethernet）的代理设置，访达与 App 走这层。
    2. 全局层：`scutil --proxy` 只读；写全局需要用 SystemConfiguration 框架，
       但 networksetup 改的服务层已覆盖绝大多数场景，故这里只做服务层。
  绕过列表：`networksetup -setproxybypassdomains <service> <domains...>`
"""
import os
import platform
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"

# macOS 上要操作的网络服务名（自动探测，找不到则用 "Wi-Fi"）
_MAC_DEFAULT_SERVICE = "Wi-Fi"


# ══════════════════════════════════════════════
#  macOS：网络服务探测
# ══════════════════════════════════════════════

def _sub_run(args: list[str], timeout: int = 8):
    """统一的 subprocess.run 包装：容错解码 + Windows 下隐藏控制台窗口。

    返回带 .returncode/.stdout/.stderr 的对象；失败时返回空输出的假对象，
    保证调用方无需 try/except。
    """
    kwargs = dict(capture_output=True, text=True, timeout=timeout,
                  errors="replace")
    if IS_WINDOWS:
        # 避免在 windowed 应用里闪出黑框
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        return subprocess.run(args, **kwargs)
    except (OSError, subprocess.SubprocessError) as e:
        return _FakeProc(e)


class _FakeProc:
    """subprocess 调用失败时的替身，统一暴露空结果"""

    def __init__(self, err):
        self.returncode = 1
        self.stdout = ""
        self.stderr = str(err)


def _mac_services() -> list[str]:
    """列出可用的网络服务名（networksetup -listallnetworkservices）"""
    out = _sub_run(["networksetup", "-listallnetworkservices"], timeout=5)
    services = []
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if not line or line.startswith("An asterisk"):
            continue
        services.append(line.lstrip("*").strip())
    return services


def _mac_active_services() -> list[str]:
    """返回当前处于「已连接/启用」状态的网络服务，优先 Wi-Fi。

    networksetup 无直接「哪个在线」的查询，这里用 `route get default`
    找到默认网卡，再用 `networksetup -listnetworkserviceorder` 反查服务名。
    """
    route = _sub_run(["route", "-n", "get", "default"], timeout=5)
    iface = ""
    for line in (route.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("interface:"):
            iface = line.split(":", 1)[1].strip()
            break
    if iface:
        order = _sub_run(["networksetup", "-listnetworkserviceorder"],
                         timeout=5)
        # 形如：(1) Wi-Fi\n(Hardware Port: Wi-Fi, Device: en0)
        lines = (order.stdout or "").splitlines()
        for i, ln in enumerate(lines):
            if f"Device: {iface}" in ln:
                # 往上找最近一条 "(n) 服务名"
                for j in range(i, -1, -1):
                    s = lines[j].strip()
                    if s.startswith("(") and ")" in s:
                        name = s.split(")", 1)[1].strip()
                        if name:
                            return [name]
    # 兜底：Wi-Fi 优先，其次第一个可用服务
    services = _mac_services()
    if _MAC_DEFAULT_SERVICE in services:
        return [_MAC_DEFAULT_SERVICE]
    return services[:1]


# ══════════════════════════════════════════════
#  统一接口：读取当前代理
# ══════════════════════════════════════════════

def get_proxy_state():
    """读取系统代理 -> dict

    返回：
        {
          "enabled": bool,          # HTTP 代理是否启用
          "server":  str,           # "host:port"，未设置时 ""
          "bypass":  list[str],     # 绕过域名/IP 列表
          "pac":     str | None,    # PAC 地址（Windows: AutoConfigURL）
          "raw":     dict,          # 平台原始快照，用于还原
        }
    """
    if IS_WINDOWS:
        return _win_get_proxy_state()
    if IS_MACOS:
        return _mac_get_proxy_state()
    return {"enabled": False, "server": "", "bypass": [], "pac": None, "raw": {}}


def set_proxy(host: str, port: str, bypass: list[str] | None,
              clear_pac: bool = True) -> None:
    """写入并启用系统 HTTP 代理。bypass=None 表示清除绕过列表。"""
    if IS_WINDOWS:
        _win_set_proxy(host, port, bypass, clear_pac)
    elif IS_MACOS:
        _mac_set_proxy(host, port, bypass, clear_pac)


def clear_proxy(raw: dict | None = None) -> None:
    """关闭系统代理。raw 为 get_proxy_state()['raw']，用于精确还原。"""
    if IS_WINDOWS:
        _win_clear_proxy(raw)
    elif IS_MACOS:
        _mac_clear_proxy(raw)


def refresh_system() -> None:
    """通知系统代理设置已变更（Windows: WinInet；macOS: 无需）"""
    if IS_WINDOWS:
        _win_refresh()


# ══════════════════════════════════════════════
#  Windows 实现
# ══════════════════════════════════════════════

_WIN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"


def _win_reg():
    import winreg
    return winreg


def _win_open(write: bool = False):
    winreg = _win_reg()
    access = winreg.KEY_READ | (winreg.KEY_WRITE if write else 0)
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_REG_PATH, 0, access)


def _win_query(key, name):
    winreg = _win_reg()
    try:
        return winreg.QueryValueEx(key, name)[0]
    except (FileNotFoundError, OSError):
        return None


def _win_get_proxy_state():
    try:
        with _win_open() as key:
            enabled = bool(_win_query(key, "ProxyEnable"))
            server = _win_query(key, "ProxyServer") or ""
            override = _win_query(key, "ProxyOverride") or ""
            pac = _win_query(key, "AutoConfigURL") or None
            bypass = [x for x in override.split(";") if x]
            return {
                "enabled": enabled,
                "server": server,
                "bypass": bypass,
                "pac": pac,
                "raw": {
                    "ProxyEnable": _win_query(key, "ProxyEnable"),
                    "ProxyServer": server or None,
                    "ProxyOverride": override or None,
                    "AutoConfigURL": pac,
                },
            }
    except (FileNotFoundError, PermissionError, OSError):
        return {"enabled": False, "server": "", "bypass": [],
                "pac": None, "raw": {}}


def _win_set_proxy(host, port, bypass, clear_pac):
    winreg = _win_reg()
    with _win_open(write=True) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ,
                          f"{host}:{port}")
        if bypass:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ,
                              ";".join(bypass))
        else:
            try:
                winreg.DeleteValue(key, "ProxyOverride")
            except FileNotFoundError:
                pass
        if clear_pac:
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass


def _win_clear_proxy(raw):
    winreg = _win_reg()
    with _win_open(write=True) as key:
        winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
        if not raw:
            try:
                winreg.DeleteValue(key, "ProxyOverride")
            except FileNotFoundError:
                pass
            return
        # 还原用户原有绕过列表
        orig = raw.get("ProxyOverride")
        if orig:
            winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, orig)
        else:
            try:
                winreg.DeleteValue(key, "ProxyOverride")
            except FileNotFoundError:
                pass
        # 还原 PAC
        pac = raw.get("AutoConfigURL")
        if pac:
            winreg.SetValueEx(key, "AutoConfigURL", 0, winreg.REG_SZ, pac)
        else:
            try:
                winreg.DeleteValue(key, "AutoConfigURL")
            except FileNotFoundError:
                pass


def _win_refresh():
    import ctypes
    INTERNET_OPTION_SETTINGS_CHANGED = 39
    INTERNET_OPTION_REFRESH = 37
    try:
        wininet = ctypes.windll.Wininet
        wininet.InternetSetOptionW(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, INTERNET_OPTION_REFRESH, 0, 0)
    except (AttributeError, OSError):
        pass


# ══════════════════════════════════════════════
#  macOS 实现
# ══════════════════════════════════════════════

def _mac_run(args: list[str]) -> tuple[int, str]:
    p = _sub_run(args)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _mac_parse_proxy_out(text: str) -> tuple[bool, str]:
    """解析 `networksetup -getwebproxy <svc>` 输出 -> (enabled, 'host:port')"""
    enabled = False
    server = ""
    port = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Enabled:"):
            enabled = line.split(":", 1)[1].strip().lower() == "yes"
        elif line.startswith("Server:"):
            server = line.split(":", 1)[1].strip()
        elif line.startswith("Port:"):
            port = line.split(":", 1)[1].strip()
    if enabled and server and port:
        return True, f"{server}:{port}"
    return enabled, ""


def _mac_get_proxy_state():
    services = _mac_active_services()
    raw = {"services": services,
           "webproxy": {}, "bypass": {}, "autoproxy": {}}
    enabled_any = False
    server_any = ""
    bypass_any: list[str] = []
    pac_any = None

    for svc in services:
        _, out = _mac_run(["networksetup", "-getwebproxy", svc])
        en, srv = _mac_parse_proxy_out(out)
        raw["webproxy"][svc] = out
        if en and srv:
            enabled_any = True
            if not server_any:
                server_any = srv

        _, bout = _mac_run(["networksetup", "-getproxybypassdomains", svc])
        raw["bypass"][svc] = bout
        domains = []
        for line in bout.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("there aren't any"):
                continue
            domains.append(line)
        if domains and not bypass_any:
            bypass_any = domains

        _, aout = _mac_run(["networksetup", "-getautoproxyurl", svc])
        raw["autoproxy"][svc] = aout
        for line in aout.splitlines():
            line = line.strip()
            if line.startswith("URL:") and line.split(":", 1)[1].strip():
                pac_any = line.split(":", 1)[1].strip()
                break

    return {"enabled": enabled_any, "server": server_any,
            "bypass": bypass_any, "pac": pac_any, "raw": raw}


def _mac_set_proxy(host, port, bypass, clear_pac):
    for svc in _mac_active_services():
        # 1) 开启 HTTP 代理
        _mac_run(["networksetup", "-setwebproxy", svc, host, str(port)])
        # 2) 同时开启 HTTPS 代理（大多数工具走 https 时会看这一项）
        _mac_run(["networksetup", "-setsecurewebproxy", svc, host, str(port)])
        # 3) 绕过列表
        if bypass:
            _mac_run(["networksetup", "-setproxybypassdomains", svc]
                     + list(bypass))
        else:
            _mac_run(["networksetup", "-setproxybypassdomains", svc, "Empty"])
        # 4) 清 PAC（PAC 优先级高于手动代理）
        if clear_pac:
            _mac_run(["networksetup", "-setautoproxystate", svc, "off"])


def _mac_clear_proxy(raw):
    raw = raw or {}
    services = raw.get("services") or _mac_active_services()
    for svc in services:
        _mac_run(["networksetup", "-setwebproxystate", svc, "off"])
        _mac_run(["networksetup", "-setsecurewebproxystate", svc, "off"])
        # 还原绕过列表
        bout = raw.get("bypass", {}).get(svc, "")
        domains = []
        for line in (bout or "").splitlines():
            line = line.strip()
            if not line or line.lower().startswith("there aren't any"):
                continue
            domains.append(line)
        if domains:
            _mac_run(["networksetup", "-setproxybypassdomains", svc] + domains)
        # 还原 PAC 状态
        aout = raw.get("autoproxy", {}).get(svc, "")
        if "Enabled: Yes" in aout:
            url = ""
            for line in aout.splitlines():
                if line.strip().startswith("URL:"):
                    url = line.split(":", 1)[1].strip()
            if url:
                _mac_run(["networksetup", "-setautoproxyurl", svc, url])
                _mac_run(["networksetup", "-setautoproxystate", svc, "on"])


# ══════════════════════════════════════════════
#  平台杂项：弹窗 / 打开文件 / 图标 / 权限 / 单实例
# ══════════════════════════════════════════════

def message_box(text: str, title: str = "提示", kind: str = "info") -> None:
    """跨平台简单弹窗（不依赖 tkinter，用于启动早期/异常兜底）"""
    if IS_WINDOWS:
        import ctypes
        flags = {"info": 0x40, "warn": 0x30, "error": 0x10}.get(kind, 0x40)
        try:
            ctypes.windll.user32.MessageBoxW(0, text, title, flags)
            return
        except Exception:
            pass
    if IS_MACOS:
        icon = {"info": "note", "warn": "caution", "error": "stop"}.get(
            kind, "note")
        _sub_run(
            ["osascript", "-e",
             f'display dialog {_osa_quote(text)} with title '
             f'{_osa_quote(title)} buttons {{"好"}} default button 1 '
             f'with icon {icon}'],
            timeout=30)
        return
    print(f"[{title}] {text}", file=sys.stderr)


def _osa_quote(s: str) -> str:
    """AppleScript 字符串转义：反斜杠 + 双引号"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def open_path(path: str) -> None:
    """用系统默认程序打开文件/目录"""
    if IS_WINDOWS:
        os.startfile(path)                       # noqa: S606
    elif IS_MACOS:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def log_dir(app_name: str = "ProxyTool") -> str:
    """各平台的用户级日志目录"""
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif IS_MACOS:
        base = os.path.expanduser("~/Library/Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME") \
            or os.path.join(os.path.expanduser("~"), ".local", "state")
    folder = os.path.join(base, app_name)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return os.path.expanduser("~")
    return folder


def resource_dirs() -> list[str]:
    """打包资源（app.png / app.icns 等）的候选目录，按优先级排列。

    各种运行形态的落点不同：
      · onefile        —— 全部资源解压在 sys._MEIPASS（临时目录）
      · onedir .app    —— 可执行文件在 Contents/MacOS，数据文件在
                          Contents/Resources（sys._MEIPASS 指向
                          Contents/Frameworks，不含 datas，必须另找）
      · onedir 平铺    —— 与可执行文件同目录
      · 源码运行       —— 与本模块同目录
    """
    dirs: list[str] = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        dirs.append(meipass)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    dirs.append(exe_dir)
    dirs.append(os.path.normpath(os.path.join(exe_dir, "..", "Resources")))
    dirs.append(os.path.dirname(os.path.abspath(__file__)))
    seen: set[str] = set()
    out: list[str] = []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def find_resource(names: tuple[str, ...] | list[str]) -> str:
    """按候选目录顺序查找第一个存在的资源文件，找不到返回空串。"""
    for d in resource_dirs():
        for name in names:
            p = os.path.join(d, name)
            if os.path.exists(p):
                return p
    return ""


def is_admin() -> bool:
    """是否具备修改系统代理所需的权限。

    macOS 改 networksetup 不需要 root（当前用户即可），故恒 True；
    Windows 需要管理员才能可靠刷新 WinInet。
    """
    if IS_MACOS:
        return True
    if not IS_WINDOWS:
        return True
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def elevate() -> None:
    """以管理员权限重启自己（仅 Windows 有意义）"""
    if not IS_WINDOWS:
        return
    import ctypes
    exe = sys.executable if getattr(sys, "frozen", False) \
        else os.path.abspath(sys.argv[0])
    params = subprocess.list2cmdline(sys.argv[1:])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)


class SingleInstance:
    """单实例锁。

    Windows：命名互斥体（CreateMutexW）。
    macOS / 其它：用锁文件 + fcntl.flock（进程退出自动释放）。
    """

    def __init__(self, name: str = "ProxyTool"):
        self._name = name
        self._handle = None
        self._lockfile = None

    def acquire(self) -> bool:
        if IS_WINDOWS:
            import ctypes
            ERROR_ALREADY_EXISTS = 183
            kernel32 = ctypes.windll.kernel32
            self._handle = kernel32.CreateMutexW(
                None, False, f"Global\\{self._name}_SingleInstance")
            if not self._handle:
                return True
            if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(self._handle)
                self._handle = None
                return False
            return True

        # POSIX：锁文件
        try:
            import fcntl
        except ImportError:
            return True
        path = os.path.join(log_dir(self._name), ".lock")
        try:
            self._lockfile = open(path, "w")
            fcntl.flock(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lockfile.write(str(os.getpid()))
            self._lockfile.flush()
            return True
        except (OSError, BlockingIOError):
            if self._lockfile:
                try:
                    self._lockfile.close()
                except OSError:
                    pass
                self._lockfile = None
            return False

    def release(self):
        if self._handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._lockfile:
            try:
                self._lockfile.close()
            except OSError:
                pass
            self._lockfile = None


def set_app_user_model_id(app_id: str = "ProxyTool.App.3") -> None:
    """Windows 任务栏图标分组标识；其它平台 no-op"""
    if not IS_WINDOWS:
        return
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def autostart_supported() -> bool:
    return IS_WINDOWS or IS_MACOS
