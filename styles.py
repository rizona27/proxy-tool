"""莫兰迪色系 (Morandi) 样式常量 — 纯标准库，无第三方依赖"""

# ── 莫兰迪色板 ──
BG_COLOR = "#edeae4"              # 暖灰白 (窗口背景)
CARD_COLOR = "#f8f6f2"            # 卡片背景
TEXT_COLOR = "#4a4947"            # 暖深灰 (主文字)
LABEL_COLOR = "#8a8885"           # 中灰 (标签/次要文字)
MUTED = "#b5b3ae"                 # 浅灰 (占位/禁用)
INACTIVE_TEXT = "#a9a7a2"         # 未启用时代理地址/端口的文字色（比 LABEL 更淡）
INACTIVE_LABEL = "#a29f9b"        # 未启用时「地址/端口」标签色

PRIMARY = "#8b9eb0"               # 灰蓝 (设置代理)
PRIMARY_HOVER = "#99acbd"
PRIMARY_PRESSED = "#7d90a3"

DANGER = "#c4a0a0"                # 灰粉 (取消代理)
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
LOCKED_BG = "#f2efe9"             # 锁定态输入框背景（略深，表示不可编辑）
WHITE = "#ffffff"
KNOB_EDGE = "#dfdfd8"             # 药丸开关滑块描边（模拟投影）
TRACK_OFF = "#d2cfc9"             # 开关关闭态轨道
TRACK_ON = PRIMARY                # 开关开启态轨道

# 反馈邮箱：低饱和莫兰迪灰紫（比 LABEL 略暖，不刺眼）
MAILTO_COLOR = "#9a8fa2"

# ── 字体 ──
FONT_FAMILY = "Microsoft YaHei UI"

# ── 尺寸 ──
WIN_W = 320
WIN_H = 200
RADIUS = 8                        # 卡片圆角
BTN_RADIUS = 7                    # 按钮圆角

# ── 动画 ──
ANIM_MS = 130                     # 开关滑动动画
FLASH_MS = 1800                   # 提示条停留时长


def lighten(hex_color: str, amount: float = 0.12) -> str:
    """把颜色向白色混合，返回十六进制字符串（用于悬停态）"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r + (255 - r) * amount)
    g = int(g + (255 - g) * amount)
    b = int(b + (255 - b) * amount)
    return f"#{r:02x}{g:02x}{b:02x}"


def darken(hex_color: str, amount: float = 0.12) -> str:
    """把颜色向黑色混合，返回十六进制字符串（用于按下态）"""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r = int(r * (1 - amount))
    g = int(g * (1 - amount))
    b = int(b * (1 - amount))
    return f"#{r:02x}{g:02x}{b:02x}"
