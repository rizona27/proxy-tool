"""莫兰迪色系 (Morandi) 样式常量"""

# ── 莫兰迪色板 ──
BG_COLOR = "#edeae4"              # 暖灰白 (窗口背景)
TEXT_COLOR = "#4a4947"            # 暖深灰 (主文字)
LABEL_COLOR = "#8a8885"           # 中灰 (标签/次要文字)
MUTED = "#b5b3ae"                 # 浅灰 (占位/禁用)

PRIMARY = "#8b9eb0"               # 灰蓝 (设置代理)
PRIMARY_HOVER = "#99acbd"
PRIMARY_PRESSED = "#7d90a3"

DANGER = "#c4a0a0"               # 灰粉 (取消代理)
DANGER_HOVER = "#d0b0b0"
DANGER_PRESSED = "#b89090"

INFO = "#9aada0"                  # 灰绿 (测试连接)
INFO_HOVER = "#a7b9ad"
INFO_PRESSED = "#8c9f92"

SUCCESS_GREEN = "#8baa8b"         # 灰绿 (延迟优)
WARNING_ORANGE = "#c4b88a"        # 灰金 (延迟中)
ERROR_RED = "#c49090"             # 灰红 (延迟差)

BORDER_COLOR = "#d5d1cb"          # 边框
BORDER_FOCUS = "#8b9eb0"          # 聚焦边框
INPUT_BG = "#faf8f5"              # 输入框背景
WHITE = "#faf8f5"

# ── 输入框 ──
INPUT_STYLE = f"""
    QLineEdit {{
        background-color: {INPUT_BG};
        color: {TEXT_COLOR};
        border: 1px solid {BORDER_COLOR};
        border-radius: 8px;
        padding: 5px 10px;
        height: 30px;
    }}
    QLineEdit:focus {{
        border: 1px solid {BORDER_FOCUS};
    }}
"""

# ── 按钮样式 ──
def action_btn_style(base: str, hover: str, pressed: str) -> str:
    return f"""
        QPushButton {{
            background-color: {base};
            color: white;
            border: none;
            border-radius: 8px;
            padding: 6px 2px;
            min-height: 30px;
            font-size: 10pt;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:pressed {{ background-color: {pressed}; }}
    """
