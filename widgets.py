"""自绘控件库 — Tkinter Canvas 上实现莫兰迪风格的圆角按钮 / 输入框 / 开关

全部基于标准库 tkinter，零第三方依赖。
"""
import tkinter as tk

from styles import (
    BG_COLOR, CARD_COLOR, TEXT_COLOR, LABEL_COLOR, MUTED,
    PRIMARY, BORDER_COLOR, BORDER_FOCUS, INPUT_BG, LOCKED_BG,
    FONT_FAMILY, BTN_RADIUS, ANIM_MS, TRACK_OFF, WHITE, ERROR_RED,
    KNOB_EDGE, INACTIVE_TEXT, lighten, darken,
)


def draw_round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kwargs):
    """在 Canvas 上绘制圆角矩形，返回 item id"""
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    points = [
        x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundButton(tk.Canvas):
    """圆角按钮：悬停/按下自动配色，支持禁用态与加载态"""

    def __init__(self, parent, text, command=None, base=PRIMARY,
                 width=84, height=32, font_size=10, radius=BTN_RADIUS,
                 bg=None, fg=WHITE):
        super().__init__(parent, width=width, height=height,
                         bg=bg or BG_COLOR, highlightthickness=0, bd=0)
        self._text = text
        self._command = command
        self._base = base
        self._width = width
        self._height = height
        self._font = (FONT_FAMILY, font_size)
        self._radius = radius
        self._fg = fg
        self._state = "normal"          # normal | hover | pressed | disabled
        self._shape = None
        self._label = None
        self._build()
        self._bind_events()

    # ── 构建 ──

    def _build(self):
        self._shape = draw_round_rect(
            self, 1, 1, self._width - 1, self._height - 1, self._radius,
            fill=self._base, outline="")
        self._label = self.create_text(
            self._width / 2, self._height / 2, text=self._text,
            fill=self._fg, font=self._font)

    def _bind_events(self):
        for seq, handler in (
            ("<Enter>", self._on_enter),
            ("<Leave>", self._on_leave),
            ("<ButtonPress-1>", self._on_press),
            ("<ButtonRelease-1>", self._on_release),
        ):
            self.bind(seq, handler)

    # ── 交互 ──

    def _color_for_state(self):
        if self._state == "disabled":
            return MUTED
        if self._state == "hover":
            return lighten(self._base)
        if self._state == "pressed":
            return darken(self._base, 0.18)
        return self._base

    def _refresh(self):
        if self._shape:
            self.itemconfig(self._shape, fill=self._color_for_state())
        cursor = "hand2" if self._state != "disabled" else "arrow"
        try:
            self.configure(cursor=cursor)
        except tk.TclError:
            pass

    def _on_enter(self, _):
        if self._state != "disabled":
            self._state = "hover"
            self._refresh()

    def _on_leave(self, _):
        if self._state != "disabled":
            self._state = "normal"
            self._refresh()

    def _on_press(self, _):
        if self._state != "disabled":
            self._state = "pressed"
            self._refresh()

    def _on_release(self, event):
        if self._state == "disabled":
            return
        self._state = "hover"
        self._refresh()
        # 仅当松开时仍在按钮范围内才触发
        if 0 <= event.x <= self._width and 0 <= event.y <= self._height:
            if self._command:
                self._command()

    # ── 公开 API ──

    def set_text(self, text):
        self._text = text
        if self._label:
            self.itemconfig(self._label, text=text)

    def get_text(self) -> str:
        return self._text

    def is_enabled(self) -> bool:
        return self._state != "disabled"

    def set_base_color(self, color):
        self._base = color
        if self._state == "normal":
            self._refresh()

    def set_enabled(self, enabled: bool):
        self._state = "normal" if enabled else "disabled"
        self._refresh()


class FlatEntry(tk.Canvas):
    """圆角扁平输入框：自绘边框，内嵌 Entry 实现真正的文本编辑与光标

    支持三种状态：
      normal    普通可编辑
      dimmed    可编辑但文字变暗（表示当前未生效）
      locked    锁定不可编辑，文字高亮（表示当前生效中）
    """

    def __init__(self, parent, width=200, height=32, radius=8,
                 placeholder="", font_size=10, bg=None, on_enter=None,
                 digits_only=False):
        super().__init__(parent, width=width, height=height,
                         bg=bg or BG_COLOR, highlightthickness=0, bd=0)
        self._width = width
        self._height = height
        self._radius = radius
        self._placeholder = placeholder
        self._font = (FONT_FAMILY, font_size)
        self._focused = False
        self._mode = "normal"
        self._error_state = False       # 内容非法时置 True，焦点切换不影响
        self._shape = draw_round_rect(
            self, 1, 1, width - 1, height - 1, radius,
            fill=INPUT_BG, outline=BORDER_COLOR)
        self._entry = tk.Entry(
            self, bd=0, highlightthickness=0, relief="flat",
            bg=INPUT_BG, fg=TEXT_COLOR, font=self._font,
            insertbackground=TEXT_COLOR)
        self.create_window(11, height / 2, window=self._entry,
                           anchor="w", width=width - 22, height=height - 12)
        self._entry.bind("<FocusIn>", self._on_focus_in)
        self._entry.bind("<FocusOut>", self._on_focus_out)
        if on_enter:
            self._entry.bind("<Return>", lambda e: on_enter())
        if digits_only:
            # 端口输入：只允许 0-9，其余符号在落地前就被拒绝
            self._entry.configure(
                validate="key",
                validatecommand=(self.register(
                    lambda proposed: proposed == "" or proposed.isdigit()),
                    "%P"))
        self._show_placeholder()

    # ── 占位符 ──

    def _text_color(self):
        """按当前模式返回输入文字颜色

        locked  启用中：最亮，突出「正在生效」
        dimmed  未启用：偏暗，提示「尚未生效」
        normal  可编辑：正常正文色
        """
        if self._mode == "locked":
            return TEXT_COLOR
        if self._mode == "dimmed":
            return INACTIVE_TEXT
        return TEXT_COLOR

    def _show_placeholder(self):
        if not self._entry.get() and self._placeholder:
            self._insert_raw(self._placeholder)
            self._entry.configure(fg=MUTED)
            self._placeholder_shown = True
        else:
            self._placeholder_shown = False

    def _insert_raw(self, text: str):
        """写入文本但绕过 validate 校验（占位符含 - / 空格等字符）"""
        vcmd = self._entry.cget("validatecommand")
        was = self._entry.cget("validate")
        try:
            if was and was != "none":
                self._entry.configure(validate="none")
            self._entry.insert(0, text)
        finally:
            if was and was != "none":
                self._entry.configure(validate=was,
                                      validatecommand=vcmd)

    def _hide_placeholder(self):
        if getattr(self, "_placeholder_shown", False):
            self._entry.delete(0, tk.END)
            self._entry.configure(fg=self._text_color())
            self._placeholder_shown = False

    # ── 焦点 ──

    def _on_focus_in(self, _):
        if self._mode == "locked":
            return
        self._focused = True
        # 焦点态只在「当前内容合法」时才改用强调色；
        # 已判定为非法的输入必须保持红框，不能因为点进点出就洗白。
        if not getattr(self, "_error_state", False):
            self.itemconfig(self._shape, outline=BORDER_FOCUS)
        self._hide_placeholder()

    def _on_focus_out(self, _):
        self._focused = False
        if self._mode != "locked":
            # 失焦时同样尊重错误态
            if getattr(self, "_error_state", False):
                self.itemconfig(self._shape, outline=ERROR_RED)
            else:
                self.itemconfig(self._shape, outline=BORDER_COLOR)

    # ── 公开 API ──

    def get(self) -> str:
        if getattr(self, "_placeholder_shown", False):
            return ""
        return self._entry.get().strip()

    def set(self, text: str):
        was_placeholder = getattr(self, "_placeholder_shown", False)
        if was_placeholder:
            self._entry.delete(0, tk.END)
            self._placeholder_shown = False
        self._entry.delete(0, tk.END)
        if text:
            # 程序化写入绕过输入校验（恢复配置时不应被 validate 挡住）
            self._insert_raw(text)
        if not self.get():
            self._placeholder_shown = False
            self._show_placeholder()
        else:
            self._entry.configure(fg=self._text_color())

    def clear(self):
        self._entry.delete(0, tk.END)
        if self._focused and self._mode != "locked":
            self._entry.configure(fg=self._text_color())
        else:
            self._placeholder_shown = False
            self._show_placeholder()

    def focus(self):
        if self._mode == "locked":
            return
        self._entry.focus_set()

    def set_border_color(self, color):
        self.itemconfig(self._shape, outline=color)

    def bind_key(self, handler):
        """绑定按键事件（用于实时校验等）"""
        self._entry.bind("<KeyRelease>", lambda e: handler(e), add="+")

    def set_border_state(self, ok: bool):
        """把边框设成「正常 / 错误」两种状态色。

        同时记录错误态 —— 焦点获得/失去时会据此决定是否保留红框，
        避免「鼠标点到别的框红框就消失」。
        """
        self._error_state = not ok
        color = BORDER_COLOR if ok else ERROR_RED
        if ok and self._focused and self._mode != "locked":
            color = BORDER_FOCUS
        self.itemconfig(self._shape, outline=color)

    # ── 状态控制 ──

    def set_mode(self, mode: str):
        """mode: 'normal' | 'dimmed' | 'locked'"""
        self._mode = mode
        if mode == "locked":
            self._entry.configure(state="readonly",
                                  readonlybackground=LOCKED_BG,
                                  fg=TEXT_COLOR)
            # 锁定态（代理生效中）不该带着编辑期的红框
            self._error_state = False
            self.itemconfig(self._shape, fill=LOCKED_BG,
                            outline=BORDER_COLOR)
            try:
                self.configure(cursor="arrow")
                self._entry.configure(cursor="arrow")
            except tk.TclError:
                pass
        else:
            self._entry.configure(state="normal", fg=self._text_color(),
                                  bg=INPUT_BG)
            self.itemconfig(
                self._shape, fill=INPUT_BG,
                outline=(ERROR_RED if getattr(self, "_error_state", False)
                         else (BORDER_FOCUS if self._focused
                               else BORDER_COLOR)))
            try:
                self.configure(cursor="xterm")
                self._entry.configure(cursor="xterm")
            except tk.TclError:
                pass

    def set_editable(self, editable: bool, highlight_locked=True):
        """启用时锁定，禁用时可编辑。
        highlight_locked=False 时锁定态也用暗文字。
        """
        if editable:
            self.set_mode("normal")
        else:
            self.set_mode("locked" if highlight_locked else "dimmed")


class SmartHostEntry(FlatEntry):
    """单一输入框，输入 IPv4 时自动插入分隔点。

    规则：
      · 连续输入数字到第 3 位（或输入 1 位 >2）时，自动补一个 "."
      · TAB / → 在 IPv4 模式下跳到下一个段；在最后一段时 TAB 才交给
        下一个控件（端口输入框）
      · 只允许输入合法字符：数字、字母、`.`、`-`、`_`、`:`、`[`、`]`
        （覆盖 域名 / IPv6 的合法字符集），其余符号一律拒绝
      · 手输小数点始终有效，不会被格式化逻辑吞掉
      · 退格可正常删除，不会反复重插点号
    """

    # 合法字符集：数字 + 字母 + 域名/IPv6 允许的标点
    _ALLOWED = set(
        "0123456789"
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        ".-_:[]"
    )

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self._fmt_guard = False
        # 输入过滤：在字符真正落进 Entry 之前就拦掉非法符号
        self._entry.configure(validate="key",
                              validatecommand=(self.register(self._on_validate), "%P"))
        self._entry.bind("<KeyRelease>", self._on_key_release, add="+")
        # TAB 由我们自己处理（跳到下一段 / 最后一段才切控件）
        self._entry.bind("<Tab>", self._on_tab, add="+")
        self._entry.bind("<Shift-Tab>", self._on_shift_tab, add="+")

    # ── 输入过滤 ──

    def _on_validate(self, proposed: str) -> bool:
        """只放行合法字符（域名 / IPv6 / IPv4 的字符集）"""
        return all(ch in self._ALLOWED for ch in proposed)

    # ── IPv4 分段辅助 ──

    def _is_ipv4_mode(self) -> bool:
        """当前内容是否应视为 IPv4（纯数字与点）"""
        raw = self._entry.get()
        return bool(raw) and all(ch.isdigit() or ch == "." for ch in raw)

    def _current_segment(self) -> int:
        """光标所在段号（0 起）。

        例：'10.' 光标在末尾(3) -> 1（第 2 段，即刚补出的空段）
            '10'  光标在末尾(2) -> 0
        """
        raw = self._entry.get()
        cur = self._entry.index(tk.INSERT)
        pos = 0
        for i, seg in enumerate(raw.split(".")):
            end = pos + len(seg)
            if cur <= end:
                return i
            pos = end + 1
        return max(0, raw.count("."))

    # ── 事件 ──

    def _on_tab(self, event):
        """TAB：IPv4 模式下逐段前进，走到第 4 段末尾才切到下一控件。

        光标在段内时 -> 跳到本段末尾之后的下一段首；
        已在末段 -> 才把焦点交给端口输入框。
        """
        if self._mode == "locked":
            return None
        raw = self._entry.get()
        if raw and all(ch.isdigit() or ch == "." for ch in raw):
            completed = self._tab_advance()
            if completed:
                return "break"          # 还在 IPv4 内，阻止焦点切换
        self._entry.tk_focusNext().focus_set()
        return "break"

    def _tab_advance(self) -> bool:
        """TAB 前进一段。返回 True 表示仍停留在本输入框内。

        判据：看「当前段」在整体中的位置
          · 第 1-3 段：跳到下一段首（必要时补点）
          · 第 4 段，或当前段为空 -> 返回 False，交给 TAB 切到端口输入框
        """
        raw = self._entry.get()
        if not raw:
            return False
        # 非 IPv4 内容（域名 / IPv6）不做分段推进
        if any(not (ch.isdigit() or ch == ".") for ch in raw):
            return False
        cur = self._entry.index(tk.INSERT)
        seg_i = self._current_segment()
        seg_text = raw.split(".")[seg_i] if seg_i < len(raw.split(".")) else ""

        # 已在第 4 段 -> 交给 TAB 切控件
        if seg_i >= 3:
            return False

        # 光标后面已有现成的点：直接跳过去
        dot = raw.find(".", cur)
        if dot != -1:
            self._entry.icursor(dot + 1)
            return True

        # 当前段为空且已在末尾（如 "10." 光标在最后）—— 没有内容可推进，
        # 让 TAB 去切控件，避免重复补点形成死循环
        if seg_text == "" and cur >= len(raw):
            return False

        new = raw + "."
        self._fmt_guard = True
        try:
            self._entry.delete(0, tk.END)
            self._insert_raw(new)
            self._entry.icursor(len(new))
        finally:
            self._fmt_guard = False
        return True

    def _on_shift_tab(self, event):
        """Shift+TAB：反向跳到上一个段首；已在最前则退回上一控件"""
        if self._mode == "locked":
            return None
        if self._is_ipv4_mode():
            raw = self._entry.get()
            cur = self._entry.index(tk.INSERT)
            prev = raw.rfind(".", 0, max(0, cur - 1))
            if prev != -1:
                self._entry.icursor(prev + 1)
                return "break"
        self._entry.tk_focusPrev().focus_set()
        return "break"

    def _autodots(self):
        """把当前输入按 IPv4 习惯格式化：满 3 位自动补点、超长自动切段。

        返回 (新文本, 是否变化)。仅在纯数字/点内容下生效。
        """
        raw = self._entry.get()
        if not raw:
            return raw, False
        if any(not (ch.isdigit() or ch == ".") for ch in raw):
            return raw, False

        # 连续点号归一：用户手输的点若紧跟在自动补的点之后，去掉多余那个。
        # 例如自动补点得到 "192." 后又手输 "." -> 归一为 "192."
        while ".." in raw:
            raw = raw.replace("..", ".")
        collapsed = raw
        if not collapsed:
            return "", True

        # 已有 4 段（3 个点）时不再补点，避免把合法输入改坏
        if collapsed.count(".") >= 3:
            segs = collapsed.split(".")
            norm = []
            for seg in segs:
                while len(seg) > 3:
                    norm.append(seg[:3])
                    seg = seg[3:]
                norm.append(seg)
            formatted = ".".join(norm[:4])
            return formatted, formatted != self._entry.get()

        # 按点号拆分，逐段规范
        segs = collapsed.split(".")
        norm = []
        for seg in segs:
            # 单段超过 3 位：前 3 位成一段，余下顺延
            while len(seg) > 3:
                norm.append(seg[:3])
                seg = seg[3:]
            norm.append(seg)

        # 末段若满 3 位则补点继续；第 2/3/4 段首位为 3-9 时
        # 不可能再组成 <=255 的三位数，也可直接补点
        formatted = ".".join(norm[:4])
        if len(norm) < 4 and norm:
            last = norm[-1]
            # 末段为空，说明用户刚手输了点号（或自动补的点）——保持不清空
            if last != "":
                if len(last) == 3:
                    formatted += "."
                elif (len(last) == 1 and last.isdigit() and int(last) > 2
                      and len(norm) > 1):
                    formatted += "."

        return formatted, formatted != self._entry.get()

    def _on_key_release(self, event):
        if self._fmt_guard or self._mode == "locked":
            return
        # 退格 / 删除 / 方向键后也走一次格式化：用户删掉自动补的 "." 再重输时，
        # 需要按当前段数重新判定是否补点，否则会停在半截状态。
        if event.keysym in ("BackSpace", "Delete"):
            formatted, changed = self._autodots()
            if changed:
                self._fmt_guard = True
                try:
                    pos = self._entry.index(tk.INSERT)
                    pos = max(1, min(pos, len(formatted)))
                    self._entry.delete(0, tk.END)
                    if formatted:
                        self._insert_raw(formatted)
                    self._entry.icursor(pos)
                    self._entry.configure(fg=self._text_color())
                finally:
                    self._fmt_guard = False
            return
        if event.keysym in ("Left", "Right", "Home", "End", "Tab",
                            "ISO_Left_Tab", "Up", "Down"):
            return
        formatted, changed = self._autodots()
        if changed:
            self._fmt_guard = True
            try:
                pos = min(len(formatted), 60)
                self._entry.delete(0, tk.END)
                if formatted:
                    self._insert_raw(formatted)
                self._entry.icursor(pos)
                self._entry.configure(fg=self._text_color())
            finally:
                self._fmt_guard = False

    def get_raw(self) -> str:
        """返回未 strip 的原始内容（占位符状态返回空）"""
        if getattr(self, "_placeholder_shown", False):
            return ""
        return self._entry.get()


class ToggleSwitch(tk.Canvas):
    """iOS 风格药丸开关：胶囊轨道 + 圆形滑块 + 滑动动画。

    轨道用单条 smooth 多边形绘制真胶囊（左右端各一个 180° 半圆，
    半径严格 = 半高），避免「半圆 + 矩形」拼接在过渡处留下直角接缝。
    滑块是完美圆形，带一圈极浅描边模拟投影。
    """

    # 胶囊轮廓采样点：左右各取 8 个点拟合半圆，smooth 后即为标准胶囊
    _ARC_STEPS = 9

    def __init__(self, parent, checked=False, command=None,
                 width=46, height=26, bg=None, linked_labels=None,
                 track_on=None, track_off=None):
        super().__init__(parent, width=width, height=height,
                         bg=bg or BG_COLOR, highlightthickness=0, bd=0)
        self._width = width
        self._height = height
        self._checked = bool(checked)
        self._command = command
        self._anim_id = None
        self._pos = 1.0 if checked else 0.0
        self._linked = list(linked_labels or [])
        self._track_on = track_on or PRIMARY
        self._track_off = track_off or TRACK_OFF

        # ── 胶囊轨道：单条 smooth 路径 ──
        self._cap = self.create_polygon(
            self._capsule_points(), smooth=True, splinesteps=24,
            fill=self._track_color(), outline="")

        # ── 圆形滑块（极浅描边，模拟 iOS 的投影感）──
        self._knob = self.create_oval(0, 0, 0, 0, fill=WHITE,
                                      outline=KNOB_EDGE, width=1)
        self._draw_knob(self._pos)

        self.bind("<Button-1>", self._on_click)
        try:
            self.configure(cursor="hand2")
        except tk.TclError:
            pass
        self._apply_linked()

    # ── 几何 ──

    def _track_color(self):
        return self._track_on if self._checked else self._track_off

    def _capsule_points(self):
        """生成标准胶囊的轮廓点：左半圆 + 右半圆，半径 = 半高"""
        import math
        w, h = self._width, self._height
        r = h / 2.0
        cy = r
        pts = []
        # 左半圆：从正上方 (r,0) 逆时针到正下方 (r,h)
        for i in range(self._ARC_STEPS + 1):
            a = math.pi / 2 + math.pi * i / self._ARC_STEPS
            pts.extend([r + r * math.cos(a), cy + r * math.sin(a)])
        # 右半圆：从正下方 (w-r,h) 逆时针回到正上方 (w-r,0)
        for i in range(self._ARC_STEPS + 1):
            a = -math.pi / 2 + math.pi * i / self._ARC_STEPS
            pts.extend([(w - r) + r * math.cos(a), cy + r * math.sin(a)])
        return pts

    # 滑块直径 / 轨道高度 —— iOS 原生约 0.56，这里取更纤细的 0.52
    KNOB_RATIO = 0.52

    def _knob_geom(self):
        """返回 (半径, 左端中心x, 右端中心x)

        滑块直径取轨道高度的 KNOB_RATIO（0.52）—— 四周留白充足，
        轨道内侧能明显看到一圈底色，视觉上更纤细接近 iOS 原生。
        """
        r = self._height * (self.KNOB_RATIO / 2.0)
        r = max(1.0, r)
        left = self._height / 2               # 左半圆圆心 x
        right = self._width - self._height / 2
        return r, left, right

    def _knob_center(self, pos):
        r, left, right = self._knob_geom()
        x = left + pos * (right - left)
        return x, self._height / 2, r

    def _move_knob(self, pos, animate=True):
        if animate:
            start, target = self._pos, pos
            steps = 10

            def step(i):
                if i > steps:
                    self._pos = target
                    return
                t = i / steps
                eased = 1 - (1 - t) ** 3       # iOS 式减速曲线
                self._draw_knob(start + (target - start) * eased)
                self._anim_id = self.after(ANIM_MS // steps,
                                           lambda: step(i + 1))

            step(1)
        else:
            self._draw_knob(pos)

    def _draw_knob(self, pos):
        cx, cy, r = self._knob_center(pos)
        self.coords(self._knob, cx - r, cy - r, cx + r, cy + r)

    def _on_click(self, _):
        self.toggle()

    def toggle(self):
        self.set(not self._checked, notify=True)

    def link_label(self, widget, active_color, idle_color):
        """把一个标签绑定到开关状态：开=active_color，关=idle_color"""
        self._linked.append((widget, active_color, idle_color))
        self._apply_linked()

    def _apply_linked(self):
        for widget, active, idle in self._linked:
            try:
                widget.configure(fg=active if self._checked else idle)
            except tk.TclError:
                pass

    def set(self, checked, notify=False):
        checked = bool(checked)
        if checked == self._checked and self._anim_id is None:
            return
        self._checked = checked
        if self._anim_id:
            try:
                self.after_cancel(self._anim_id)
            except (tk.TclError, ValueError):
                pass
            self._anim_id = None
        self.itemconfig(self._cap, fill=self._track_color())
        self._move_knob(1.0 if checked else 0.0)
        self._apply_linked()
        if notify and self._command:
            self._command(checked)

    def is_checked(self) -> bool:
        return self._checked

    # 兼容旧调用名
    @property
    def _cap_l(self):
        return self._cap

    @property
    def _bar(self):
        return self._cap


class StatusDot(tk.Canvas):
    """状态圆点指示器（支持外描边环，提高小尺寸下的辨识度）"""

    def __init__(self, parent, size=9, color=MUTED, bg=None, ring=None):
        pad = 2 if ring else 0
        box = size + pad * 2
        super().__init__(parent, width=box, height=box,
                         bg=bg or CARD_COLOR, highlightthickness=0, bd=0)
        self._dot = self.create_oval(pad, pad, pad + size, pad + size,
                                     fill=color, outline=ring or "")

    def set_color(self, color):
        self.itemconfig(self._dot, fill=color)


class LinkLabel(tk.Label):
    """下划线链接样式的标签"""

    def __init__(self, parent, text, command=None, color=None, bg=None,
                 font_size=9):
        from styles import PRIMARY
        color = color or PRIMARY
        super().__init__(parent, text=text, fg=color, bg=bg or BG_COLOR,
                         font=(FONT_FAMILY, font_size, "underline"),
                         cursor="hand2")
        self._normal = color
        self.bind("<Button-1>", lambda e: command() if command else None)
        self.bind("<Enter>", lambda e: self.configure(fg=darken(color, 0.15)))
        self.bind("<Leave>", lambda e: self.configure(fg=self._normal))


def label(parent, text, size=9, color=None, bg=None, bold=False, **kw):
    """快捷创建标签"""
    return tk.Label(
        parent, text=text, bg=bg or BG_COLOR,
        fg=color or LABEL_COLOR,
        font=(FONT_FAMILY, size, "bold" if bold else "normal"), **kw)
