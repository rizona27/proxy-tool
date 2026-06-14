"""自定义 IP 地址输入框 — 自动分段格式化"""
import re
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtGui import QFont
from styles import INPUT_STYLE


class IPLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Microsoft YaHei", 10))
        self.setStyleSheet(INPUT_STYLE)
        self.textChanged.connect(self.format_ip)

    def format_ip(self):
        """格式化 IP 地址：每 3 位数字自动添加点号（修复分段索引偏移 bug）"""
        text = self.text().replace(" ", "")

        # 移除多余点号
        while '..' in text:
            text = text.replace('..', '.')

        # 仅保留数字和点号
        cleaned = re.sub(r'[^\d.]', '', text)

        # 按点号拆段，每段超过 3 位则按 3 位切分，最多 4 段
        parts = cleaned.split('.')
        new_parts = []
        for part in parts:
            for j in range(0, len(part), 3):
                if len(new_parts) >= 4:
                    break
                new_parts.append(part[j:j + 3])
            if len(new_parts) >= 4:
                break

        formatted = '.'.join(new_parts[:4])

        if formatted != self.text():
            self.blockSignals(True)
            self.setText(formatted)
            self.blockSignals(False)

        if len(formatted) > 15:
            self.setText(formatted[:15])
