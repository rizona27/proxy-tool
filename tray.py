"""Windows 原生系统托盘图标 — 纯 ctypes 实现，无第三方依赖

替代 pystray：只做本工具需要的「图标 + 单击/双击 + 右键菜单」。
运行在独立线程中，通过回调把事件送回 Tkinter 主线程。
"""
import ctypes
import ctypes.wintypes as wt
import os
import threading

# ── Shell API 常量 ──
WM_USER = 0x0400
WM_APP = 0x8000
WM_TRAYICON = WM_APP + 1

WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002
WM_NULL = 0x0000

NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
IDI_APPLICATION = 32512

MF_STRING = 0x00000000
MF_SEPARATOR = 0x00000800
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100

# 菜单项 ID
IDM_TOGGLE = 1001
IDM_SHOW = 1002
IDM_COPY = 1003
IDM_ABOUT = 1004
IDM_QUIT = 1005

_CS_DBLCLKS = 0x0008


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wt.UINT),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uTimeoutOrVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
    ]


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,           # LRESULT
    wt.HWND,                     # hWnd
    wt.UINT,                     # msg
    ctypes.c_size_t,             # WPARAM (UINT_PTR)
    ctypes.c_ssize_t,            # LPARAM (LONG_PTR, 有符号)
)

_user32 = ctypes.windll.user32
_user32.DefWindowProcW.argtypes = [
    wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
_user32.DefWindowProcW.restype = ctypes.c_longlong


class TrayIcon:
    """系统托盘图标。

    回调 on_toggle / on_show / on_copy / on_about / on_quit 都在托盘线程中触发，
    调用方需要自行切回 UI 线程（本项目中通过 root.after 实现）。
    """

    def __init__(self, icon_path="", tooltip="代理切换工具",
                 on_toggle=None, on_show=None, on_copy=None,
                 on_about=None, on_quit=None):
        self.icon_path = icon_path
        self._tooltip = tooltip
        self._on_toggle = on_toggle
        self._on_show = on_show
        self._on_copy = on_copy
        self._on_about = on_about
        self._on_quit = on_quit

        self._hwnd = None
        self._hicon = None
        self._thread = None
        self._ready = threading.Event()
        self._stopped = False
        self._menu_toggle_text = "启用代理"

        self._user32 = ctypes.windll.user32
        self._shell32 = ctypes.windll.shell32
        self._kernel32 = ctypes.windll.kernel32
        self._wndproc_ref = None       # 保持引用，防止被 GC

    # ── 生命周期 ──

    def start(self):
        """启动托盘线程；等待窗口创建完成"""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3)
        if self._hwnd is None:
            raise RuntimeError("托盘窗口创建失败")
        self._add_icon()

    def _run(self):
        try:
            self._run_inner()
        except Exception:
            # 托盘线程异常绝不能冒泡：windowed 模式下没有 stderr，
            # 会触发 PyInstaller「Failed to obtain/convert traceback!」
            try:
                import traceback
                import os
                base = os.environ.get("APPDATA") or os.path.expanduser("~")
                folder = os.path.join(base, "ProxyTool")
                os.makedirs(folder, exist_ok=True)
                from datetime import datetime
                with open(os.path.join(folder, "error.log"), "a",
                          encoding="utf-8") as f:
                    f.write(f"\n{'=' * 60}\n"
                            f"{datetime.now():%Y-%m-%d %H:%M:%S}  [tray]\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass

    def _run_inner(self):
        hinst = self._kernel32.GetModuleHandleW(None)
        class_name = "ProxyToolTrayWnd"

        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASS()
        wc.style = _CS_DBLCLKS
        wc.lpfnWndProc = ctypes.cast(self._wndproc_ref, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.hIcon = self._load_icon(hinst)
        wc.hCursor = self._user32.LoadCursorW(None, ctypes.c_wchar_p(32512))
        wc.hbrBackground = None
        wc.lpszClassName = class_name

        self._user32.RegisterClassW(ctypes.byref(wc))
        # 允许点击穿透到托盘时立即收到消息
        self._hwnd = self._user32.CreateWindowExW(
            0, class_name, "ProxyToolTray", 0, 0, 0, 0, 0,
            None, None, hinst, None)
        self._ready.set()
        if not self._hwnd:
            return

        msg = wt.MSG()
        while not self._stopped and self._user32.GetMessageW(
                ctypes.byref(msg), None, 0, 0) > 0:
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

        self._user32.DestroyWindow(self._hwnd)
        self._user32.UnregisterClassW(class_name, hinst)

    def stop(self):
        self._stopped = True
        if self._hwnd:
            try:
                self._delete_icon()
                self._user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
            except Exception:
                pass
        if self._hicon:
            try:
                self._user32.DestroyIcon(self._hicon)
            except Exception:
                pass

    # ── 图标 ──

    def _load_icon(self, hinst):
        if self.icon_path and os.path.exists(self.icon_path) \
                and self.icon_path.lower().endswith(".ico"):
            h = self._user32.LoadImageW(
                None, self.icon_path, IMAGE_ICON, 0, 0,
                LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                return h
        return self._user32.LoadIconW(None, ctypes.c_wchar_p(IDI_APPLICATION))

    def _nid(self, flags):
        nid = NOTIFYICONDATA()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        nid.hWnd = self._hwnd
        nid.uID = 1
        nid.uFlags = flags
        nid.uCallbackMessage = WM_TRAYICON
        nid.hIcon = self._hicon
        nid.szTip = self._tooltip[:127]
        return nid

    def _add_icon(self):
        hinst = self._kernel32.GetModuleHandleW(None)
        self._hicon = self._load_icon(hinst)
        nid = self._nid(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        self._shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))

    def _delete_icon(self):
        nid = self._nid(0)
        self._shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))

    # ── 外部更新接口 ──

    def update_tooltip(self, text: str):
        self._tooltip = text
        if not self._hwnd:
            return
        nid = self._nid(NIF_TIP)
        self._shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def update_menu_text(self, toggle_text: str):
        self._menu_toggle_text = toggle_text

    # ── 消息处理 ──

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_TRAYICON:
                event = lparam & 0xFFFF
                if event in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    self._fire(self._on_show)
                elif event == WM_RBUTTONUP:
                    self._show_menu()
                return 0
            if msg == WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0
        except Exception:
            # 托盘线程绝不应因异常中断消息循环
            return 0
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _fire(self, callback):
        if callback:
            try:
                callback()
            except Exception:
                pass

    def _show_menu(self):
        menu = self._user32.CreatePopupMenu()
        if not menu:
            return
        try:
            self._user32.AppendMenuW(menu, MF_STRING, IDM_TOGGLE,
                                     self._menu_toggle_text)
            self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            self._user32.AppendMenuW(menu, MF_STRING, IDM_SHOW, "显示主窗口")
            self._user32.AppendMenuW(menu, MF_STRING, IDM_COPY, "复制代理信息")
            self._user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
            self._user32.AppendMenuW(menu, MF_STRING, IDM_ABOUT, "关于")
            self._user32.AppendMenuW(menu, MF_STRING, IDM_QUIT, "退出")

            pt = wt.POINT()
            self._user32.GetCursorPos(ctypes.byref(pt))
            # 必须前置窗口，否则点击菜单外部时菜单不会消失
            self._user32.SetForegroundWindow(self._hwnd)
            cmd = self._user32.TrackPopupMenu(
                menu, TPM_RIGHTBUTTON | TPM_RETURNCMD,
                pt.x, pt.y, 0, self._hwnd, None)
            # 菜单关闭后把焦点交还，避免菜单"粘住"
            self._user32.PostMessageW(self._hwnd, WM_NULL, 0, 0)

            dispatch = {
                IDM_TOGGLE: self._on_toggle,
                IDM_SHOW: self._on_show,
                IDM_COPY: self._on_copy,
                IDM_ABOUT: self._on_about,
                IDM_QUIT: self._on_quit,
            }
            if cmd in dispatch:
                self._fire(dispatch[cmd])
        except Exception:
            # 菜单异常不得让托盘线程崩溃
            pass
        finally:
            self._user32.DestroyMenu(menu)
