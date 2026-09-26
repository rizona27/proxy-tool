"""主窗口 — 莫兰迪风格紧凑界面 + 系统托盘

纯标准库 Tkinter 实现，零第三方依赖。
"""
import os
import queue
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from styles import (
    BG_COLOR, CARD_COLOR, TEXT_COLOR, LABEL_COLOR, MUTED, BORDER_COLOR,
    PRIMARY, DANGER, INFO, INACTIVE_LABEL, MAILTO_COLOR,
    SUCCESS_GREEN, WARNING_ORANGE, ERROR_RED,
    WIN_W, WIN_H, FONT_FAMILY, FLASH_MS,
)
from widgets import (
    RoundButton, FlatEntry, ToggleSwitch, LinkLabel, label,
    SmartHostEntry,
)
from proxy_core import (
    get_current_proxy, enable_proxy_registry, disable_proxy_registry,
    refresh_system, parse_proxy_server, snapshot_proxy_settings,
    has_restorable_snapshot, build_bypass, validate_host, validate_port,
    validate_host_live, looks_like_ipv4,
    normalize_host, is_private_ip, resolve_host, read_autoconfig_url,
)
from latency_tester import LatencyTester, GeoLookup, error_text

# 版本号只此一处定义，改 version.py 即可全局生效
from version import VERSION, APP_NAME, APP_TITLE
from oplog import OperationLogger, default_log_path, default_log_dir

HINT_IDLE = "Enter 切换 · Esc 清空 · 支持 IP/域名/IPv6"
MIN_H = 200

# 药丸开关尺寸（用户反馈偏大，已从 38x21 收窄到 33x18）
SW_W, SW_H = 29, 16

# Readme 折叠分组标题行的浅色带（比卡片底色略深一点点）
_SECTION_BG = "#f1eee8"


class ProxyTool:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.configure(bg=BG_COLOR)
        self.root.resizable(False, False)
        self._apply_window_icon()
        self._center_window(WIN_W, WIN_H)

        # ── 运行时状态 ──
        self._enabled = False
        self._proxy_host = ""
        self._proxy_port = ""
        self._host_text = ""           # 主机输入的原始文本（供锁定/恢复）
        self._tcp_ms = None
        self._egress_ms = None
        self._egress_geo = {}
        self._proxy_geo = {}
        self._tester = None
        self._geo_cache = {}
        self._ui_queue = queue.Queue()
        self._flash_job = None
        self._orig_snapshot = None
        self._tray = None

        self._load_settings()

        # ── 操作日志（默认路径：exe/脚本同目录） ──
        self.logger = OperationLogger(
            enabled=self._cfg.get("log_enabled", "0") == "1",
            path=self._cfg.get("log_path") or default_log_path())

        self._build_ui()
        self._setup_tray()
        self._fit_window()

        # 窗口就绪后再落一条启动记录（此时 set_enabled 会创建文件）
        if self.logger.enabled:
            self.logger.info(
                f"程序启动 v{VERSION} · 日志文件 {self.logger.path}")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", lambda e: self._clear_inputs())
        self.root.bind("<Return>", lambda e: self._toggle_proxy())

        # 关键：接管 Tk 回调异常。windowed 模式下 Tk 默认把回调异常
        # 打到 stderr，而 PyInstaller 的无控制台引导层拿不到 stderr，
        # 就会抛出「Failed to obtain/convert traceback!」这类无信息报错。
        self.root.report_callback_exception = self._on_callback_error

        self._pump_queue()
        self.root.after(120, self._refresh_status)

    # ═══════════════════════════════════════════
    #  异常兜底
    # ═══════════════════════════════════════════

    def _on_callback_error(self, exc_type, exc_value, exc_tb):
        """Tk 事件回调内的异常统一走这里，写日志而非静默崩溃"""
        import traceback
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        # 操作日志（若已开启）
        try:
            self.logger.error(
                f"UI 回调异常 {exc_type.__name__}: {exc_value}\n{detail.rstrip()}")
        except Exception:
            pass
        try:
            import main as _m
            path = _m.log_path()
            from datetime import datetime
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n{datetime.now():%Y-%m-%d %H:%M:%S}"
                        f"  [UI callback]\n")
                f.write(detail)
            shown = path
        except Exception:
            shown = "(日志写入失败)"
        try:
            self._set_hint(f"操作出错：{exc_type.__name__}", ERROR_RED)
        except Exception:
            pass
        try:
            messagebox.showerror(
                "操作出错",
                f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入：\n{shown}",
                parent=self.root)
        except Exception:
            pass

    # ═══════════════════════════════════════════
    #  窗口 / 设置持久化
    # ═══════════════════════════════════════════

    def _center_window(self, w, h):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 3}")

    def _fit_window(self):
        """按实际内容自适应窗口尺寸，并锁定不可拖拽缩放"""
        self.root.update_idletasks()
        need_h = max(self.root.winfo_reqheight(), MIN_H)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.root.geometry(f"{WIN_W}x{need_h}+{(sw - WIN_W) // 2}"
                           f"+{(sh - need_h) // 3}")
        # 锁定尺寸：既禁止拖拽，也防止系统 DPI 缩放改变窗口
        self.root.resizable(False, False)
        self.root.minsize(WIN_W, need_h)
        self.root.maxsize(WIN_W, need_h)

    def _settings_path(self):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = os.path.join(base, "ProxyTool")
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "settings.ini")

    def _load_settings(self):
        self._cfg = {"proxy_host": "", "proxy_port": "", "bypass_local": "1",
                     "minimize_to_tray": "1", "last_ok": "",
                     "log_enabled": "0", "log_path": ""}
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        # 丢弃已废弃的键（如内网域名模块移除后的遗留配置）
                        if k in self._cfg:
                            self._cfg[k] = v.strip()
        except (OSError, UnicodeDecodeError):
            pass

    def _saved_inputs(self):
        """把「上一次成功启用」的配置还原到输入框。

        只有 last_ok == "1"（即确实成功启用过）时才回填；否则一律保持
        空输入，让「启用代理」按钮处于灰度不可用状态。
        """
        if self._cfg.get("last_ok", "") == "1":
            return self._cfg.get("proxy_host", ""), self._cfg.get("proxy_port", "")
        return "", ""

    def _save_settings(self, remember_inputs: bool = False):
        """持久化设置。

        remember_inputs=True 时才把当前地址/端口记为「上次成功使用的配置」；
        普通保存（如切换开关）不会污染这份记录。
        """
        try:
            if remember_inputs:
                self._cfg["proxy_host"] = self._current_host()
                self._cfg["proxy_port"] = self.port_entry.get()
                self._cfg["last_ok"] = "1"
            self._cfg["bypass_local"] = "1" if self.bypass_switch.is_checked() else "0"
            self._cfg["minimize_to_tray"] = (
                "1" if self.tray_switch.is_checked() else "0")
            if hasattr(self, "log_switch"):
                self._cfg["log_enabled"] = (
                    "1" if self.log_switch.is_checked() else "0")
                self._cfg["log_path"] = self.logger.path
            with open(self._settings_path(), "w", encoding="utf-8") as f:
                for k, v in self._cfg.items():
                    f.write(f"{k}={v}\n")
        except OSError:
            pass

    # ═══════════════════════════════════════════
    #  界面构建
    # ═══════════════════════════════════════════

    def _build_ui(self):
        root = self.root
        margin = 8                            # 统一外边距，压缩空白

        # ── 卡片：代理配置（地址/端口 + 右侧按钮） ──
        card = tk.Frame(root, bg=CARD_COLOR)
        card.pack(fill="x", padx=margin, pady=(margin, 4))

        label_w = 44                          # 「地址/端口」标签列宽
        btn_w = 68
        entry_w = WIN_W - margin * 2 - label_w - btn_w - 22
        btn_col = tk.Frame(card, bg=CARD_COLOR)
        btn_col.pack(side="right", padx=(4, 7), pady=6)

        self.toggle_btn = RoundButton(
            btn_col, "启用代理", command=self._toggle_proxy,
            base=PRIMARY, width=btn_w, height=28, font_size=9)
        self.toggle_btn.pack(pady=(0, 4))

        self.test_btn = RoundButton(
            btn_col, "测试连接", command=self._test_connection,
            base=INFO, width=btn_w, height=28, font_size=9)
        self.test_btn.pack()

        rows = tk.Frame(card, bg=CARD_COLOR)
        rows.pack(side="left", fill="x", expand=True)

        row1 = tk.Frame(rows, bg=CARD_COLOR)
        row1.pack(fill="x", padx=(8, 0), pady=(6, 3))
        self.host_label = label(row1, "地址", size=9, color=LABEL_COLOR,
                                bg=CARD_COLOR, anchor="w")
        self.host_label.pack(side="left", padx=(0, 6))
        # 单个输入框：输入 IP 时自动插入分隔点，也支持域名 / IPv6
        self.host_entry = SmartHostEntry(
            row1, width=entry_w, height=27, radius=7,
            placeholder="IP / 域名 / IPv6",
            bg=CARD_COLOR, on_enter=self._toggle_proxy)
        self.host_entry.pack(side="left")
        # 默认打开时为空；仅当上一次「成功启用」过才回填那次配置
        _saved_host, _saved_port = self._saved_inputs()
        self._host_text = _saved_host
        self.host_entry.set(_saved_host)

        row2 = tk.Frame(rows, bg=CARD_COLOR)
        row2.pack(fill="x", padx=(8, 0), pady=(0, 6))
        self.port_label = label(row2, "端口", size=9, color=LABEL_COLOR,
                                bg=CARD_COLOR, anchor="w")
        self.port_label.pack(side="left", padx=(0, 6))
        self.port_entry = FlatEntry(row2, width=entry_w, height=27, radius=7,
                                    placeholder="1-65535",
                                    bg=CARD_COLOR, on_enter=self._toggle_proxy,
                                    digits_only=True)
        self.port_entry.pack(side="left")
        self.port_entry.set(_saved_port)
        # 地址/端口任一变化 -> 重算整体校验，刷新红框与按钮可用性
        self.host_entry.bind_key(lambda e: self._validate_live())
        self.port_entry.bind_key(lambda e: self._validate_live())

        # ── 信息卡片：归属地 + 延迟 ──
        info_card = tk.Frame(root, bg=CARD_COLOR)
        info_card.pack(fill="x", padx=margin, pady=(0, 4))
        info_inner = tk.Frame(info_card, bg=CARD_COLOR)
        info_inner.pack(fill="x", padx=9, pady=5)

        left_col = tk.Frame(info_inner, bg=CARD_COLOR)
        left_col.pack(side="left", anchor="n")
        self.geo_proxy_label = label(left_col, "代理: —", size=8,
                                     color=MUTED, bg=CARD_COLOR, anchor="w")
        self.geo_proxy_label.pack(anchor="w")
        self.geo_egress_label = label(left_col, "出口: —", size=8,
                                      color=MUTED, bg=CARD_COLOR, anchor="w")
        self.geo_egress_label.pack(anchor="w")

        right_col = tk.Frame(info_inner, bg=CARD_COLOR)
        right_col.pack(side="right", anchor="n")
        self.lat_tcp_label = label(right_col, "到代理: —", size=8,
                                   color=MUTED, bg=CARD_COLOR, anchor="e")
        self.lat_tcp_label.pack(anchor="e")
        self.lat_egress_label = label(right_col, "出口: —", size=8,
                                      color=MUTED, bg=CARD_COLOR, anchor="e")
        self.lat_egress_label.pack(anchor="e")

        # 左侧归属地文本过长时截断，保证右侧延迟列不被挤出窗口
        self._geo_max_px = (WIN_W - margin * 2 - 18
                            - max(self.lat_tcp_label.winfo_reqwidth(),
                                  self.lat_egress_label.winfo_reqwidth())
                            - 10)
        for lbl in (self.geo_proxy_label, self.geo_egress_label):
            lbl.configure(anchor="w", justify="left")

        # ── 底部开关区 ──
        # 第一行：绕过本地地址（左） + 最小化到托盘（右）
        switch_row = tk.Frame(root, bg=BG_COLOR)
        switch_row.pack(fill="x", padx=margin, pady=(1, 0))

        self.bypass_label = label(switch_row, "绕过本地地址", size=9,
                                  color=LABEL_COLOR, bg=BG_COLOR)
        self.bypass_label.pack(side="left", padx=(2, 5))
        self.bypass_switch = ToggleSwitch(
            switch_row, checked=self._cfg.get("bypass_local", "1") == "1",
            command=self._on_bypass_toggled, bg=BG_COLOR,
            width=SW_W, height=SW_H)
        self.bypass_switch.pack(side="left")
        self.bypass_switch.link_label(self.bypass_label, TEXT_COLOR, MUTED)

        self.tray_switch = ToggleSwitch(
            switch_row, checked=self._cfg.get("minimize_to_tray", "1") == "1",
            command=self._on_tray_toggled, bg=BG_COLOR,
            width=SW_W, height=SW_H)
        self.tray_switch.pack(side="right", padx=(0, 2))
        self.tray_label = label(switch_row, "最小化到托盘", size=9,
                                color=LABEL_COLOR, bg=BG_COLOR)
        self.tray_label.pack(side="right", padx=(0, 5))
        self.tray_switch.link_label(self.tray_label, TEXT_COLOR, MUTED)

        # 第二行：记录日志（左） + 日志设置（右）
        log_row = tk.Frame(root, bg=BG_COLOR)
        log_row.pack(fill="x", padx=margin, pady=(3, 0))

        self.log_label = label(log_row, "记录日志", size=9,
                               color=LABEL_COLOR, bg=BG_COLOR)
        self.log_label.pack(side="left", padx=(2, 5))
        self.log_switch = ToggleSwitch(
            log_row, checked=self._cfg.get("log_enabled", "0") == "1",
            command=self._on_log_toggled, bg=BG_COLOR,
            width=SW_W, height=SW_H)
        self.log_switch.pack(side="left")
        self.log_switch.link_label(self.log_label, TEXT_COLOR, MUTED)

        # 右侧：日志设置入口（改路径 / 打开日志）
        self.log_open_btn = LinkLabel(
            log_row, "打开日志", command=self._open_log,
            bg=BG_COLOR, font_size=8)
        self.log_open_btn.pack(side="right", padx=(0, 3))
        self.log_path_btn = LinkLabel(
            log_row, "日志位置", command=self._choose_log_path,
            bg=BG_COLOR, font_size=8)
        self.log_path_btn.pack(side="right", padx=(0, 8))

        footer = tk.Frame(root, bg=BG_COLOR)
        footer.pack(fill="x", padx=margin, pady=(3, 5))
        self.hint_label = label(footer, HINT_IDLE, size=8, color=MUTED,
                                bg=BG_COLOR, anchor="w")
        self.hint_label.pack(side="left")
        LinkLabel(footer, "Readme", command=self._show_readme,
                  bg=BG_COLOR).pack(side="right")

        # 立刻按当前输入校验一次：让「启用代理 / 测试连接」两个按钮
        # 在窗口出现的第一帧就是正确的灰度态，不必等 _refresh_status
        # 在 120ms 后才把它们同步过来（否则会看到按钮先亮后灰的闪动）。
        self._validate_live()

    # ═══════════════════════════════════════════
    #  提示条
    # ═══════════════════════════════════════════

    def _set_hint(self, text, color=None):
        self.hint_label.configure(text=text, fg=color or MUTED)

    def _flash_hint(self, text, color=None):
        if self._flash_job:
            try:
                self.root.after_cancel(self._flash_job)
            except (tk.TclError, ValueError):
                pass
        self._set_hint(text, color)
        self._flash_job = self.root.after(
            FLASH_MS, lambda: self._set_hint(HINT_IDLE))

    # ═══════════════════════════════════════════
    #  状态渲染
    # ═══════════════════════════════════════════

    def _refresh_status(self):
        enabled, _, server = get_current_proxy()
        self._enabled = enabled

        if enabled:
            host, port, _ = parse_proxy_server(server)
            self._proxy_host, self._proxy_port = host, port
            self.toggle_btn.set_text("取消代理")
            self.toggle_btn.set_base_color(DANGER)
            if host and not self._host_text:
                self._host_text = host
                self.host_entry.set(host)
            if port and not self.port_entry.get():
                self.port_entry.set(port)
            if host and port and self._tcp_ms is None:
                self._lookup_geo(host)
                self.root.after(60, lambda: self._start_probe(host, int(port)))
        else:
            self._proxy_host, self._proxy_port = "", ""
            self.toggle_btn.set_text("启用代理")
            self.toggle_btn.set_base_color(PRIMARY)
            self._tcp_ms = self._egress_ms = None
            self._egress_geo = {}
            self._proxy_geo = {}
            self._render_geo()
            self._render_latency()

        self._apply_edit_lock(enabled)
        self._validate_live()
        self._update_tray()

    def _apply_edit_lock(self, locked: bool):
        """启用代理时：锁定地址/端口，文字亮起（正在生效）
        未启用时：可编辑，文字转暗（尚未生效），视觉上一眼可辨
        """
        for w in (self.host_entry, self.port_entry):
            try:
                # 启用 -> locked（锁定 + 亮字）；未启用 -> dimmed（可编辑 + 暗字）
                w.set_mode("locked" if locked else "dimmed")
            except Exception:
                pass
        # 标签同步：锁定态更深，未启用态更浅
        tone = TEXT_COLOR if locked else INACTIVE_LABEL
        for lbl in (self.host_label, self.port_label):
            try:
                lbl.configure(fg=tone)
            except tk.TclError:
                pass

    def _render_geo(self):
        def fmt(geo, prefix):
            if not geo:
                return f"{prefix}: —"
            parts = [p for p in (geo.get("country", ""), geo.get("city", ""),
                                 geo.get("query", "")) if p]
            return f"{prefix}: {' / '.join(parts)}" if parts else f"{prefix}: 无数据"

        self.geo_proxy_label.configure(
            text=self._ellipsize(fmt(self._proxy_geo, "代理")),
            fg=TEXT_COLOR if self._proxy_geo else MUTED)
        self.geo_egress_label.configure(
            text=self._ellipsize(fmt(self._egress_geo, "出口")),
            fg=TEXT_COLOR if self._egress_geo else MUTED)

    def _ellipsize(self, text: str, font_size: int = 8) -> str:
        """按可用像素宽度截断文本，超出部分以 … 结尾"""
        limit = getattr(self, "_geo_max_px", None)
        if not limit or not text:
            return text
        try:
            from tkinter import font as tkfont
            f = tkfont.Font(family=FONT_FAMILY, size=font_size)
            if f.measure(text) <= limit:
                return text
            ell = "…"
            n = len(text)
            while n > 1 and f.measure(text[:n] + ell) > limit:
                n -= 1
            return text[:n] + ell
        except Exception:
            return text

    @staticmethod
    def _lat_color(ms, good, warn):
        if ms is None or ms <= 0:
            return ERROR_RED
        if ms < good:
            return SUCCESS_GREEN
        return WARNING_ORANGE if ms < warn else ERROR_RED

    def _render_latency(self):
        if self._tcp_ms is None:
            self.lat_tcp_label.configure(text="到代理: —", fg=MUTED)
        elif self._tcp_ms > 0:
            self.lat_tcp_label.configure(
                text=f"到代理: {self._tcp_ms:.0f}ms",
                fg=self._lat_color(self._tcp_ms, 100, 500))
        else:
            self.lat_tcp_label.configure(
                text=f"到代理: {error_text(self._tcp_ms)}", fg=ERROR_RED)

        if self._egress_ms is None:
            self.lat_egress_label.configure(text="出口: —", fg=MUTED)
        elif self._egress_ms > 0:
            self.lat_egress_label.configure(
                text=f"出口: {self._egress_ms:.0f}ms",
                fg=self._lat_color(self._egress_ms, 300, 1000))
        else:
            self.lat_egress_label.configure(
                text=f"出口: {error_text(self._egress_ms)}", fg=ERROR_RED)

    # ═══════════════════════════════════════════
    #  代理操作
    # ═══════════════════════════════════════════

    def _read_inputs(self):
        """读取并校验输入 -> (host, port) 或 None"""
        host = self._current_host()
        port = self.port_entry.get().strip()

        if not host:
            messagebox.showwarning("输入错误", "代理地址不能为空",
                                   parent=self.root)
            self.host_entry.focus()
            return None
        ok, msg = validate_host_live(host)
        if not ok:
            messagebox.showwarning("输入错误", msg, parent=self.root)
            self.host_entry.focus()
            self.host_entry.set_border_state(False)
            return None
        ok, msg = validate_port(port)
        if not ok:
            messagebox.showwarning("输入错误", msg, parent=self.root)
            self.port_entry.focus()
            self.port_entry.set_border_state(False)
            return None

        self.port_entry.set_border_state(True)
        self.host_entry.set_border_state(True)
        return host, port

    def _current_host(self) -> str:
        """读取主机输入：IPv4 分段框或通用文本（域名 / IPv6）"""
        raw = self.host_entry.get()
        return normalize_host(raw) if raw else ""

    def _on_tray_toggled(self, checked):
        self._flash_hint("关闭窗口时缩到托盘" if checked
                         else "关闭窗口时直接退出", MUTED)
        self._save_settings()

    # ═══════════════════════════════════════════
    #  操作日志
    # ═══════════════════════════════════════════

    def _on_log_toggled(self, checked):
        self.logger.set_enabled(checked)
        self._save_settings()
        if checked:
            self._flash_hint(f"日志已开启 → {os.path.basename(self.logger.path)}",
                             SUCCESS_GREEN)
        else:
            self.logger.info("日志记录已关闭")
            self._flash_hint("日志已关闭", MUTED)

    def _choose_log_path(self):
        """选择日志文件保存位置（默认 exe 同目录）"""
        from tkinter import filedialog
        current = os.path.dirname(self.logger.path) or default_log_dir()
        picked = filedialog.askdirectory(
            title="选择日志保存目录", initialdir=current,
            parent=self._readme_win if self._readme_alive() else self.root)
        if not picked:
            return
        self.logger.set_path(os.path.join(picked, "ProxyTool_log.txt"))
        self.logger.info(f"日志路径已改为 {self.logger.path}")
        self._save_settings()
        self._flash_hint(f"日志位置：{picked}", SUCCESS_GREEN)

    def _open_log(self):
        """用系统默认程序打开日志文件"""
        path = self.logger.path
        if not os.path.exists(path):
            # 尚未写过任何内容：若是开启状态，先落一条再打开
            if self.logger.enabled:
                self.logger.info("日志文件已创建")
        if not os.path.exists(path):
            messagebox.showinfo(
                "尚无日志", "日志文件还不存在。\n请先打开「记录日志」开关。",
                parent=self.root)
            return
        try:
            os.startfile(path)          # Windows
        except AttributeError:
            import subprocess
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([opener, path])
        except OSError as e:
            messagebox.showerror("无法打开", f"打开日志失败：{e}",
                                 parent=self.root)

    def _readme_alive(self) -> bool:
        w = getattr(self, "_readme_win", None)
        try:
            return bool(w is not None and w.winfo_exists())
        except tk.TclError:
            return False

    def _validate_live(self):
        """地址 + 端口一起实时校验。

        这是「红框」和「启用代理按钮可用性」的唯一判据 —— 两个输入框共用
        同一套逻辑，所以切焦点导致的重绘不会让已经判定为错的边框回弹。
        返回 (host_ok, port_ok)。
        """
        host_raw = self.host_entry.get()
        port_raw = self.port_entry.get().strip()

        # 未启用（可编辑）时才做实时红框提示；启用中锁定态一律正常边框
        editable = not self._enabled

        host_ok, _ = validate_host_live(host_raw) if host_raw else (False, "")
        port_ok, _ = validate_port(port_raw) if port_raw else (False, "")

        if editable:
            # 空输入不打红框（还没开始填），有内容且非法才标红
            self.host_entry.set_border_state(host_ok if host_raw else True)
            self.port_entry.set_border_state(port_ok if port_raw else True)

        # 全部校验通过才允许「启用代理」；取消态下按钮始终可用
        can_enable = bool(host_ok and port_ok)
        self.toggle_btn.set_enabled(True if self._enabled else can_enable)
        # 「测试连接」与「启用代理」同一套规则：
        #   · 未启用：地址 + 端口都合法才能点，否则灰度
        #   · 已启用：直接不可用（正在生效，无需再测）
        self._sync_test_btn(can_enable)
        return host_ok, port_ok

    def _sync_test_btn(self, inputs_ok: bool = None):
        """按当前状态刷新「测试连接」按钮的可用性与文案。

        · 代理已启用 -> 禁用（不可再测）
        · 探测进行中（文案为「检测中」）-> 保持禁用，别被校验回调误开
        · 其余情况 -> 与「启用代理」一致：地址 + 端口都合法才可点
        """
        if inputs_ok is None:
            host_ok, _ = validate_host_live(self.host_entry.get()) \
                if self.host_entry.get() else (False, "")
            port_ok, _ = validate_port(self.port_entry.get().strip()) \
                if self.port_entry.get().strip() else (False, "")
            inputs_ok = bool(host_ok and port_ok)
        # 探测进行中：不打断「检测中」状态
        if self.test_btn.get_text() == "检测中":
            return
        self.test_btn.set_enabled((not self._enabled) and inputs_ok)

    # 兼容旧调用名
    def _validate_port_live(self):
        self._validate_live()

    def _toggle_proxy(self):
        if self._enabled:
            self._disable_proxy()
        else:
            self._enable_proxy()

    def _enable_proxy(self):
        parsed = self._read_inputs()
        if not parsed:
            return
        host, port = parsed

        bypass = None
        if self.bypass_switch.is_checked():
            bypass = build_bypass(
                bypass_private_ip=True, extra_hosts=None)

        try:
            # 启用前快照，供关闭时还原用户原有配置
            self._orig_snapshot = snapshot_proxy_settings()
            pac = read_autoconfig_url()

            enable_proxy_registry(host, port, bypass, disable_pac=True)
            refresh_system()
            # 启用成功 —— 记录这次配置，下次打开软件回填
            self._host_text = host
            self._save_settings(remember_inputs=True)
            self._refresh_status()

            self.logger.ok(
                f"启用代理 {host}:{port}"
                f" · 绕过本地地址={'开' if bypass else '关'}"
                f" · 绕过项={len(bypass.split(';')) if bypass else 0}条"
                + (" · 原 PAC 已禁用" if pac else ""))
            self._flash_hint(f"✓ {host}:{port}", SUCCESS_GREEN)
            if pac:
                self._set_hint("注意：原有 PAC 脚本已暂时禁用", WARNING_ORANGE)

            try:
                port_int = int(port)
            except ValueError:
                port_int = None
            if port_int:
                self._lookup_geo(host)
                self.root.after(200, lambda: self._start_probe(host, port_int))
        except (PermissionError, OSError) as e:
            self.logger.error(f"启用代理失败 {host}:{port} — {type(e).__name__}: {e}")
            messagebox.showerror("错误", f"注册表写入失败：{e}", parent=self.root)

    def _disable_proxy(self):
        try:
            restore = (self._orig_snapshot
                       if has_restorable_snapshot(self._orig_snapshot) else None)
            disable_proxy_registry(restore)
            refresh_system()
            self._save_settings()
            self._refresh_status()
            self.logger.ok("取消代理" + ("（已还原原有设置）" if restore else ""))
            msg = "✓ 已禁用代理" + ("（原有设置已还原）" if restore else "")
            self._flash_hint(msg, LABEL_COLOR)
        except (PermissionError, OSError) as e:
            self.logger.error(f"取消代理失败 — {type(e).__name__}: {e}")
            self._refresh_status()
            messagebox.showerror("错误", f"取消代理失败：{e}", parent=self.root)

    def _clear_inputs(self):
        if self._enabled:
            return
        self.host_entry.clear()
        self.port_entry.clear()
        self.port_entry.set_border_state(True)
        self.host_entry.set_border_state(True)
        self._validate_live()
        self.logger.info("清空输入")
        self._flash_hint("已清空输入", MUTED)

    def _on_bypass_toggled(self, checked):
        # 文字亮/灰由 ToggleSwitch 的 link_label 自动处理，这里只给轻提示
        self.logger.info(f"绕过本地地址 {'开启' if checked else '关闭'}")
        self._flash_hint("已开启" if checked else "已关闭", MUTED)
        self._save_settings()

    # ═══════════════════════════════════════════
    #  延迟 / 归属地检测
    # ═══════════════════════════════════════════

    def _start_probe(self, host, port):
        if self._tester and self._tester.is_alive():
            self._tester.cancel()
        self._tcp_ms = self._egress_ms = None
        self._egress_geo = {}
        self.lat_tcp_label.configure(text="到代理: 检测中…", fg=MUTED)
        self.lat_egress_label.configure(text="出口: 检测中…", fg=MUTED)

        self._tester = LatencyTester(host, port, "HTTP", timeout=5.0)
        self._tester.start(
            on_result=lambda tcp, eg, geo, err: self._ui_queue.put(
                ("latency", tcp, eg, geo, err)))

    def _test_connection(self):
        # 代理已启用时不允许再测（按钮本身也是灰的，这里兜底）
        if self._enabled:
            return
        parsed = self._read_inputs()
        if not parsed:
            return
        host, port = parsed
        self.logger.info(f"测试连接 {host}:{port}")
        self.test_btn.set_enabled(False)
        self.test_btn.set_text("检测中")
        self._lookup_geo(host)
        self._start_probe(host, int(port))
        self.root.after(6000, self._reset_test_btn)

    def _reset_test_btn(self):
        """探测结束后恢复按钮：文案复位，可用性交给统一规则决定"""
        self.test_btn.set_text("测试连接")
        self._sync_test_btn()

    def _lookup_geo(self, host):
        if is_private_ip(host):
            self._proxy_geo = {"country": "内网地址", "query": host}
            self._render_geo()
            return
        resolved = resolve_host(host)
        target = resolved or host
        if target in self._geo_cache:
            self._proxy_geo = self._geo_cache[target]
            self._render_geo()
            return
        self.geo_proxy_label.configure(text="代理: 查询中…", fg=MUTED)

        GeoLookup(target).start(
            lambda data, err: self._ui_queue.put(("proxy_geo", data, err, target)))

    def _pump_queue(self):
        """把工作线程结果取回主线程渲染"""
        try:
            while True:
                item = self._ui_queue.get_nowait()
                if item[0] == "latency":
                    _, tcp, eg, geo, _err = item
                    self._tcp_ms, self._egress_ms, self._egress_geo = tcp, eg, geo
                    self._render_latency()
                    self._render_geo()
                    self._reset_test_btn()
                    self._update_tray()
                    self.logger.info(self._latency_log_text(tcp, eg, geo))
                elif item[0] == "proxy_geo":
                    _, data, err, target = item
                    if data:
                        self._geo_cache[target] = data
                        self._proxy_geo = data
                        self.logger.info(
                            f"代理归属地 {target} → "
                            f"{data.get('country', '')}/{data.get('city', '')}")
                    else:
                        self._proxy_geo = {"country": "查询失败", "city": err}
                        self.logger.warn(f"代理归属地查询失败 {target} — {err}")
                    self._render_geo()
        except queue.Empty:
            pass
        self.root.after(100, self._pump_queue)

    @staticmethod
    def _latency_log_text(tcp, eg, geo) -> str:
        """把延迟结果显示成适合写日志的一行文本"""
        def fmt(v, label):
            if v is None:
                return f"{label}=未测"
            if v <= 0:
                return f"{label}=失败({error_text(v)})"
            return f"{label}={v:.0f}ms"

        extra = ""
        if geo and geo.get("query"):
            extra = f" · 出口IP={geo['query']}"
        return f"延迟检测 {fmt(tcp, '到代理')} · {fmt(eg, '出口')}{extra}"

    # ═══════════════════════════════════════════
    #  系统托盘
    # ═══════════════════════════════════════════

    def _setup_tray(self):
        """Windows 原生托盘图标（ctypes 实现，无第三方依赖）"""
        try:
            from tray import TrayIcon
            self._tray = TrayIcon(
                icon_path=self._icon_path(),
                tooltip=self._tray_tooltip(),
                on_toggle=self._toggle_proxy_from_tray,
                on_show=self._show_window,
                on_copy=self._copy_info,
                on_about=self._show_readme,
                on_quit=self._quit)
            self._tray.start()
        except Exception:
            # 托盘不可用不应阻塞主功能
            self._tray = None

    def _icon_path(self):
        """应用图标路径（打包后从 _MEIPASS 取，源码模式取同目录）"""
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        for name in ("app.ico", "app.png"):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
        return ""

    def _apply_window_icon(self):
        """把 app.ico 设为窗口标题栏左上角图标（含任务栏）"""
        path = self._icon_path()
        if not path:
            return
        # 1) iconbitmap：Windows 下同时作用于标题栏与任务栏
        try:
            self.root.iconbitmap(default=path)
        except tk.TclError:
            try:
                self.root.iconbitmap(path)
            except tk.TclError:
                pass
        # 2) 同时用 iconphoto 兜底（部分 DPI/主题下 iconbitmap 会被忽略）
        try:
            from PIL import Image, ImageTk   # 可选，无则跳过
            img = Image.open(path)
            self._icon_photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass
        # 3) 通过 Win32 API 再设一次 AppUserModelID 与窗口图标，
        #    确保任务栏使用自定义图标而非默认 Tk 图标
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "ProxyTool.App.3")
        except Exception:
            pass


    def _tray_tooltip(self):
        if not self._enabled:
            return f"{APP_TITLE} — 已禁用代理"
        lines = [f"{APP_TITLE} — 已启用",
                 f"{self._proxy_host}:{self._proxy_port}"]
        if self._tcp_ms and self._tcp_ms > 0:
            lines.append(f"延迟 {self._tcp_ms:.0f}ms")
        return "\n".join(lines)

    def _update_tray(self):
        if not self._tray:
            return
        try:
            self._tray.update_tooltip(self._tray_tooltip())
            self._tray.update_menu_text("禁用代理" if self._enabled else "启用代理")
        except Exception:
            pass

    def _toggle_proxy_from_tray(self):
        self.root.after(0, self._toggle_proxy)

    def _copy_info(self):
        lines = [APP_TITLE]
        lines.append(f"状态: 已启用 {self._proxy_host}:{self._proxy_port}"
                     if self._enabled else "状态: 已禁用")
        if self._tcp_ms and self._tcp_ms > 0:
            lines.append(f"到代理延迟: {self._tcp_ms:.0f}ms")
        if self._egress_ms and self._egress_ms > 0:
            lines.append(f"出口延迟: {self._egress_ms:.0f}ms")
        if self._egress_geo.get("query"):
            lines.append(f"出口 IP: {self._egress_geo['query']}")

        def do_copy():
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))
            self._flash_hint("✓ 代理信息已复制", SUCCESS_GREEN)

        self.root.after(0, do_copy)

    # ═══════════════════════════════════════════
    #  Readme / 窗口事件 / 退出
    # ═══════════════════════════════════════════

    def _show_readme(self):
        """同一时刻只允许一个 Readme 窗口"""
        old = getattr(self, "_readme_win", None)
        if old is not None:
            try:
                if old.winfo_exists():
                    old.lift()
                    old.focus_set()
                    return
            except tk.TclError:
                pass
        self.root.after(0, self._build_readme_dialog)

    def _build_readme_dialog(self):
        """自建 Readme 对话框。

        尺寸：宽比主窗口略窄，高比主窗口略大（见 _readme_size）。
        结构：固定标题栏 + 可滚动内容区 + 底部提示，无关闭按钮 ——
              窗口自带标题栏的 X（以及 Esc）即可关闭。
        内容：分组折叠卡片，默认只展开「快速上手」，其余点击标题行展开。
        """
        win = tk.Toplevel(self.root)
        win.title(f"关于 {APP_NAME}")
        win.configure(bg=BG_COLOR)
        win.resizable(False, False)
        try:
            win.transient(self.root)
        except tk.TclError:
            pass
        path = self._icon_path()
        if path:
            try:
                win.iconbitmap(default=path)
            except tk.TclError:
                pass

        win_w, win_h = self._readme_size()

        # ── 最外层：卡片（与主窗口同色系） ──
        card = tk.Frame(win, bg=CARD_COLOR)
        card.pack(fill="both", expand=True, padx=8, pady=8)

        # ══════ 页头已取消（标题栏已显示应用名，省下的高度全给滚动内容区） ══════
        # 版本号与反馈邮箱一起放到内容区末尾，靠右对齐。

        # ══════ 可滚动内容区 ══════
        wrap = tk.Frame(card, bg=CARD_COLOR)
        wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(wrap, bg=CARD_COLOR, highlightthickness=0, bd=0)
        # 滚轮步长：每格约 26px，滚动更顺滑（默认 units 步长过小、顿感明显）
        canvas.configure(yscrollincrement=26)
        vbar = tk.Scrollbar(wrap, orient="vertical", command=canvas.yview,
                            width=9, bd=0, highlightthickness=0,
                            troughcolor=CARD_COLOR, bg=BORDER_COLOR,
                            activebackground=PRIMARY, relief="flat")
        canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=CARD_COLOR)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        body = tk.Frame(inner, bg=CARD_COLOR)
        body.pack(fill="both", expand=True, padx=13, pady=(9, 6))

        # 折行宽度：按画布实际宽度动态计算，避免初始估算不准导致文字被裁
        _wrap_refs = []

        def _apply_wrap(width):
            # 画布宽 - 左右内边距 - 项目符号缩进
            wl = max(140, int(width) - 13 * 2 - 22)
            for lbl in _wrap_refs:
                try:
                    lbl.configure(wraplength=wl)
                except tk.TclError:
                    pass

        def _on_canvas_configure(event):
            canvas.itemconfigure(inner_id, width=event.width)
            _apply_wrap(event.width)

        canvas.bind("<Configure>", _on_canvas_configure)
        inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # ══════ 折叠分组内容（手风琴：同时只展开一组） ══════
        sections = []
        for idx, (title, lines) in enumerate(self._readme_sections()):
            sec = self._readme_section(body, canvas, title, lines,
                                       expanded=(idx == 0),
                                       wrap_refs=_wrap_refs,
                                       extra=self._readme_section_extra(
                                           title, canvas))
            sections.append(sec)

        # 互斥展开：任意一组展开时，先折叠其它所有组
        def _activate(target):
            for sec in sections:
                if sec is not target:
                    sec.collapse()

        for sec in sections:
            sec.on_open = _activate

        # 首次按当前窗口宽度折行
        _apply_wrap(win_w - 16 - 9 - 26)

        # 反馈邮箱与版本号已移入「关于本工具」分组内（见 _readme_section_extra）

        # ══════ 固定页脚：只留滚动提示（关闭按钮已去掉，用标题栏 X / Esc） ══════
        tk.Frame(card, bg=BORDER_COLOR, height=1).pack(fill="x")
        foot = tk.Frame(card, bg=CARD_COLOR)
        foot.pack(fill="x", padx=13, pady=(6, 8))
        label(foot, "滚动查看更多 · Esc 关闭", size=8, color=MUTED,
              bg=CARD_COLOR, anchor="w").pack(side="left")

        # ── 滚轮：只在指针位于弹窗内时生效 ──
        # 关键：<Enter>/<Leave> 不冒泡，只绑 canvas/inner/body 时，
        # 指针一旦移到里面的折叠标题（Label）上就会触发 Leave → 解绑，
        # 于是「悬停在展开按钮上滚动没反应」。这里对整个子树逐层绑定，
        # 并用计数方式管理进入/离开，避免子控件之间移动时误解绑。
        _depth = {"n": 0}

        def _on_wheel(event):
            delta = event.delta
            if delta == 0:
                return "break"
            # 高分辨率滚轮（触控板）单次 delta 可能远小于 120，
            # 这时用 1 格保证仍有响应；普通鼠标按 120 的倍数折算。
            if abs(delta) >= 120:
                steps = -(delta // 120)
            else:
                steps = -1 if delta > 0 else 1
            steps = max(-4, min(4, int(steps)))
            canvas.yview_scroll(steps, "units")
            return "break"

        def _enter(_):
            _depth["n"] += 1
            if _depth["n"] == 1:
                canvas.bind_all("<MouseWheel>", _on_wheel)

        def _leave(_):
            _depth["n"] = max(0, _depth["n"] - 1)
            if _depth["n"] == 0:
                canvas.unbind_all("<MouseWheel>")

        def _bind_tree(widget):
            widget.bind("<Enter>", _enter, add="+")
            widget.bind("<Leave>", _leave, add="+")
            for child in widget.winfo_children():
                _bind_tree(child)

        # 等所有子控件都创建完再整体绑定（body 下已挂满折叠分组）
        win.after_idle(lambda: _bind_tree(canvas))

        # ── 定位：弹窗外框中心对齐主窗口外框中心 ──
        # Tk 的 winfo_rootx/rooty 返回「客户区」原点，不含边框与标题栏；
        # 直接用它算居中会出现固定偏移（本机实测 +8 / +31）。
        # 这里优先用 Win32 GetWindowRect 拿真正的窗口外框；
        # 非 Windows 平台退回 Tk 的客户区尺寸（macOS/Linux 无标题栏偏移问题较小）。
        win.update_idletasks()

        def _outer_rect(tkwin):
            """返回 (x, y, w, h) 外框坐标；失败时用 Tk 客户区兜底"""
            try:
                import ctypes
                from ctypes import wintypes
                hwnd = int(tkwin.frame(), 16)
                rc = wintypes.RECT()
                if ctypes.windll.user32.GetWindowRect(
                        ctypes.c_void_p(hwnd), ctypes.byref(rc)):
                    return (rc.left, rc.top,
                            rc.right - rc.left, rc.bottom - rc.top)
            except Exception:
                pass
            return (tkwin.winfo_rootx(), tkwin.winfo_rooty(),
                    tkwin.winfo_width(), tkwin.winfo_height())

        # 先把弹窗摆到屏幕外并 force 布局，拿到真实外框尺寸
        win.geometry(f"{win_w}x{win_h}+-32000+-32000")
        win.update_idletasks()
        _, _, dlg_ow, dlg_oh = _outer_rect(win)

        self.root.update_idletasks()
        rx, ry, rw, rh = _outer_rect(self.root)
        if rw <= 1 or rh <= 1:
            rw = max(rw, self.root.winfo_reqwidth())
            rh = max(rh, self.root.winfo_reqheight())

        cx = rx + rw // 2
        cy = ry + rh // 2
        x = cx - dlg_ow // 2
        y = cy - dlg_oh // 2
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(10, min(x, sw - dlg_ow - 10))
        y = max(10, min(y, sh - dlg_oh - 40))
        win.geometry(f"{win_w}x{win_h}+{x}+{y}")
        win.update_idletasks()

        win.bind("<Escape>", lambda e: self._close_readme())

        # 关闭时解绑全局滚轮，防止残留
        def _on_destroy(_):
            try:
                canvas.unbind_all("<MouseWheel>")
            except tk.TclError:
                pass
            self._readme_win = None

        win.bind("<Destroy>", _on_destroy, add="+")

        win.focus_set()
        self._readme_win = win

    def _close_readme(self):
        old = getattr(self, "_readme_win", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
            self._readme_win = None

    @staticmethod
    def _readme_size():
        """Readme 弹窗尺寸：宽比主窗口略窄，高比主窗口略大。

        主窗口 320 宽 —— 这里取 300 宽（两侧各收 10px）。
        高度：页头（应用名 + 版本 + 副标题）已取消，省下的空间全部让给
        滚动内容区，因此在原基础上再增高，一屏能多看 1~2 个折叠分组。
        同时受屏幕尺寸约束，小屏下自动收缩。
        """
        w = WIN_W - 20
        h = WIN_H + 150
        try:
            sw = tk._default_root.winfo_screenwidth()
            sh = tk._default_root.winfo_screenheight()
            w = min(w, sw - 60)
            h = min(h, sh - 120)
        except Exception:
            pass
        return int(w), int(h)

    @staticmethod
    def _readme_sections():
        """Readme 内容：按主题分组，每组 (标题, [要点...])"""
        return [
            ("快速上手", [
                "填入代理地址与端口（如 192.168.1.1 : 8080）",
                "地址与端口全部校验通过后，「启用代理」按钮才可点击",
                "点击按钮或按 Enter 切换代理；Esc 清空输入",
                "再次点击「取消代理」即恢复系统原有设置",
            ]),
            ("地址输入", [
                "支持 IPv4、域名（proxy.example.com）、IPv6（[::1]）",
                "输入 IP 自动补点分段：192168111 → 192.168.1.11",
                "TAB 逐段跳转：输到 192.168 按 TAB 自动补点并进入第 3 段",
                "走到第 4 段末尾后，TAB 才切换焦点到端口框",
                "字符白名单：只放行数字、字母与 . - _ : [ ]",
                "IPv4 必须 4 段且每段 0-255；缺段或越界都会标红",
            ]),
            ("端口与校验", [
                "示例端口 8080；只接受 0-9 数字，其他符号在按键落地前就被拒绝",
                "端口范围 1-65535，超出即时标红",
                "红框由内容决定，切换焦点不会让红框消失",
                "只要有一项不合法，「启用代理」就保持灰色禁用",
            ]),
            ("绕过本地地址", [
                "开启后自动写入私有网段，内网访问不经过代理",
                "覆盖 10.x / 172.16-63.x / 192.168.x / 127.x",
                "含 CGNAT（100.64-127.x）、链路本地 169.254.x",
                "含 IPv6 本机、ULA、链路本地与 *.local",
                "关闭代理时精确还原你原有的绕过列表",
            ]),
            ("状态与检测", [
                "代理归属地：查询代理服务器所在国家 / 城市",
                "出口归属地：查询经代理后对外呈现的 IP",
                "双段延迟：到代理的 TCP 延迟 + 出口 HTTP 往返",
                "归属地文本过长自动省略号裁切，不挤压延迟列",
                "「测试连接」按钮可在不启用代理时先探一次",
            ]),
            ("启用状态与记忆", [
                "启用后地址与端口转为只读且文字加深，防止误改",
                "未启用时可自由编辑，文字偏淡以示「尚未生效」",
                "只在成功启用后记住当次的地址与端口",
                "下次打开自动回填；从未成功启用过则保持空白",
                "最小化到托盘开关决定关闭窗口时缩到托盘还是退出",
            ]),
            ("关于本工具", [
                "纯 Python 标准库实现，零第三方依赖",
                "任何未处理异常都会写入日志文件便于定位",
            ]),
        ]

    def _readme_section_extra(self, title, canvas):
        """给指定分组返回一个「附加块构建函数」（没有则 None）。

        目前只有「关于本工具」需要：把反馈邮箱与版本号放在该分组正文
        末尾，整体靠右对齐 —— 取代原先固定页脚里那一小块。
        返回的函数由 _readme_section 用真正的父容器（content）调用，
        这样块一定排在本组正文的最后、且在折叠时一起隐藏。
        """
        if title != "关于本工具":
            return None

        hb = tkfont.Font(family=FONT_FAMILY, size=8, weight="bold",
                         slant="italic")
        # 保持引用，防止字体对象被 GC（Tk 会随之失效）
        self._feedback_font = hb

        def _build(parent):
            box = tk.Frame(parent, bg=CARD_COLOR)
            box.pack(fill="x", padx=(9, 20), pady=(5, 0))
            # 上分隔线
            tk.Frame(box, bg=BORDER_COLOR, height=1).pack(fill="x", pady=(0, 5))
            # 邮箱在上、版本号在下，整体右对齐
            tk.Label(box, text="rizona.cn@gmail.com", bg=CARD_COLOR,
                     fg=MAILTO_COLOR, font=hb, anchor="e").pack(
                fill="x", anchor="e")
            label(box, f"Version {VERSION}", size=8, color=MAILTO_COLOR,
                  bg=CARD_COLOR, anchor="e").pack(fill="x", anchor="e",
                                                  pady=(2, 0))
            return box

        return _build

    def _readme_section(self, parent, canvas, title, lines,
                        expanded=False, wrap_refs=None, extra=None):
        """渲染一个可折叠分组，返回一个可被外部控制的小句柄。

        句柄暴露：
          · on_open   —— 属性，赋值一个回调；本组被用户展开时调用（用于手风琴互斥）
          · collapse()—— 折叠本组（不触发 on_open）
          · expand()  —— 展开本组并滚动到顶部
        这样 _build_readme_dialog 就能把「同时只展开一组」的规则集中实现。

        wrap_refs：外部传入的列表，正文标签会登记进去，
                   画布宽度变化时统一重设 wraplength。
        extra：可选 —— 一个附加在正文末尾的自定义控件（如「关于本工具」
               里的反馈邮箱 + 版本块）。由 _readme_section_extra() 产出。
        """
        block = tk.Frame(parent, bg=CARD_COLOR)
        block.pack(fill="x", pady=(0, 4))

        # 标题行：单独一条可点击的浅色带，视觉上明确「可展开」
        strip = tk.Frame(block, bg=_SECTION_BG)
        strip.pack(fill="x")

        state = {"open": bool(expanded), "on_open": None}
        arrow = tk.Label(strip, text="", bg=_SECTION_BG, fg=PRIMARY,
                         font=(FONT_FAMILY, 8), cursor="hand2")
        arrow.pack(side="left", padx=(6, 4), pady=3)

        head = tk.Label(strip, text=title, bg=_SECTION_BG, fg=TEXT_COLOR,
                        font=(FONT_FAMILY, 9, "bold"),
                        anchor="w", cursor="hand2")
        head.pack(side="left", fill="x", expand=True, pady=3)

        content = tk.Frame(block, bg=CARD_COLOR)

        for it in lines:
            row = tk.Frame(content, bg=CARD_COLOR)
            row.pack(fill="x", pady=0)
            label(row, "·", size=8, color=PRIMARY,
                  bg=CARD_COLOR).pack(side="left", anchor="n",
                                      padx=(9, 4))
            txt = label(row, it, size=8, color=LABEL_COLOR, bg=CARD_COLOR,
                        anchor="w", justify="left")
            txt.pack(side="left", fill="x", expand=True, anchor="w")
            if wrap_refs is not None:
                wrap_refs.append(txt)

        # 附加自定义块（如「关于本工具」的反馈邮箱 + 版本号）
        # extra 是一个「构建函数」：由 _readme_section 提供 content 作为父容器，
        # 保证它按顺序留在本分组正文的最末尾。
        if callable(extra):
            extra(content)

        # ── 句柄 ──
        class _Section:
            """分组句柄：外部通过 on_open / collapse() / expand() 控制。"""
            title = ""
            count = 0

            @property
            def on_open(self):
                return self._state["on_open"]

            @on_open.setter
            def on_open(self, cb):
                self._state["on_open"] = cb

        sec = _Section()
        sec._state = state
        sec.title = title
        sec.count = len(lines)

        def _refresh_scroll():
            block.update_idletasks()
            try:
                canvas.configure(scrollregion=canvas.bbox("all"))
            except tk.TclError:
                pass

        def _set_open(open_it, notify):
            if state["open"] == open_it:
                return
            state["open"] = open_it
            if open_it:
                content.pack(fill="x", pady=(2, 4))
                arrow.configure(text="▼")
                if notify and callable(state["on_open"]):
                    state["on_open"](sec)          # 通知外部折叠其它组
            else:
                content.pack_forget()
                arrow.configure(text="▶")
            _refresh_scroll()

        def _expand(notify=True):
            _set_open(True, notify)
            # 展开后把本组滚动到视口顶部
            _refresh_scroll()
            try:
                canvas.update_idletasks()
                total = canvas.bbox("all")
                if total and total[3] > 0:
                    frac = block.winfo_y() / float(total[3])
                    canvas.yview_moveto(max(0.0, min(1.0, frac)))
            except tk.TclError:
                pass

        def _toggle(_=None):
            if state["open"]:
                _set_open(False, False)
            else:
                _expand(notify=True)

        sec.collapse = lambda: _set_open(False, False)
        sec.expand = lambda: _expand(notify=True)

        # 初始状态
        if state["open"]:
            content.pack(fill="x", pady=(2, 4))
            arrow.configure(text="▼")
        else:
            arrow.configure(text="▶")

        for w in (head, arrow, strip):
            w.bind("<Button-1>", _toggle)
        return sec


    def _show_window(self):
        self.root.after(0, self._do_show_window)

    def _do_show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_close(self):
        """关闭按钮：按「最小化到托盘」开关决定缩到托盘还是退出"""
        minimize = (self.tray_switch.is_checked()
                    if hasattr(self, "tray_switch") else True)
        if minimize and self._tray:
            self.root.withdraw()
        else:
            self._quit()

    def _quit(self):
        if self._tester and self._tester.is_alive():
            self._tester.cancel()
        # 退出时也把「成功启用过」的配置留存下来（未启用成功则记录不变）
        self._save_settings(remember_inputs=self._enabled)
        if self._tray:
            try:
                self._tray.stop()
            except Exception:
                pass
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass

    # ═══════════════════════════════════════════
    #  主循环
    # ═══════════════════════════════════════════

    def run(self):
        self.root.mainloop()
