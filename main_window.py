"""主窗口：单切换按钮 + 系统托盘 + 紧凑布局"""
import json
import os
import re
import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QGridLayout, QSizePolicy,
    QShortcut, QSystemTrayIcon, QMenu, QAction, QCheckBox,
)
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon, QIntValidator, QCursor, QKeySequence
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply

from styles import (
    BG_COLOR, TEXT_COLOR, MUTED, PRIMARY, DANGER, INFO,
    SUCCESS_GREEN, WARNING_ORANGE, ERROR_RED, LABEL_COLOR,
    INPUT_STYLE, action_btn_style,
)
from ip_line_edit import IPLineEdit
from latency_tester import LatencyTester
from proxy_core import (
    get_current_proxy, enable_proxy_registry, disable_proxy_registry,
    refresh_system, parse_proxy_server,
    is_private_ip, make_geo_request, parse_geo_response,
)

LABEL_W = 64
BTN_W = 78


class ProxyTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("代理切换工具")
        self.setFixedSize(400, 240)

        icon_path = self._resource_path("logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.geo_cache = {}
        self._proxy_enabled = False
        self.latency_tester = None
        self._test_check_count = 0
        self._test_timer = None

        self.nm = QNetworkAccessManager(self)
        self.nm.finished.connect(self.on_geo_finished)

        self.setup_ui()
        self.setup_tray(icon_path)
        self.load_settings()
        self.update_status()
        self._center_on_screen()

    @staticmethod
    def _resource_path(relative_path):
        try:
            base_path = sys._MEIPASS
        except AttributeError:
            base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            frame = self.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            self.move(frame.topLeft())

    # ═══════════════════════════════════════════════════
    #  界面
    # ═══════════════════════════════════════════════════

    def setup_ui(self):
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(BG_COLOR))
        self.setPalette(palette)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 6)
        main_layout.setSpacing(5)

        # ── 网格 ──
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(7)
        grid.setColumnStretch(1, 1)

        # 行 0: 代理地址 + 测试连接
        ip_label = QLabel("代理地址：")
        ip_label.setFont(QFont("Microsoft YaHei", 10))
        ip_label.setStyleSheet(f"color: {LABEL_COLOR};")
        ip_label.setFixedWidth(LABEL_W)
        ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(ip_label, 0, 0)

        self.ip_entry = IPLineEdit()
        self.ip_entry.setPlaceholderText("例如: 192.168.1.1")
        self.ip_entry.returnPressed.connect(self.toggle_proxy)
        grid.addWidget(self.ip_entry, 0, 1)

        self.test_button = QPushButton("测试连接")
        self.test_button.setFont(QFont("Microsoft YaHei", 10))
        self.test_button.setFixedWidth(BTN_W)
        self.test_button.setStyleSheet(action_btn_style(INFO, "#a7b9ad", "#8c9f92"))
        self.test_button.setCursor(Qt.PointingHandCursor)
        self.test_button.clicked.connect(self.on_test_connection)
        grid.addWidget(self.test_button, 0, 2)

        # 行 1: 代理端口 + 切换按钮
        port_label = QLabel("代理端口：")
        port_label.setFont(QFont("Microsoft YaHei", 10))
        port_label.setStyleSheet(f"color: {LABEL_COLOR};")
        port_label.setFixedWidth(LABEL_W)
        port_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(port_label, 1, 0)

        self.port_entry = QLineEdit()
        self.port_entry.setFont(QFont("Microsoft YaHei", 10))
        self.port_entry.setStyleSheet(INPUT_STYLE)
        self.port_entry.setPlaceholderText("例如: 8080")
        self.port_entry.setValidator(QIntValidator(1, 65535))
        self.port_entry.setMaxLength(5)
        self.port_entry.returnPressed.connect(self.toggle_proxy)
        grid.addWidget(self.port_entry, 1, 1)

        self.toggle_btn = QPushButton("设置代理")
        self.toggle_btn.setFont(QFont("Microsoft YaHei", 10))
        self.toggle_btn.setFixedWidth(BTN_W)
        self.toggle_btn.setStyleSheet(action_btn_style(PRIMARY, "#99acbd", "#7d90a3"))
        self.toggle_btn.setCursor(Qt.PointingHandCursor)
        self.toggle_btn.clicked.connect(self.toggle_proxy)
        grid.addWidget(self.toggle_btn, 1, 2)

        # 行 2: 托盘选项
        opt_row = QHBoxLayout()
        opt_row.setContentsMargins(LABEL_W + 6, 0, 0, 0)

        self.tray_cb = QCheckBox("最小化到托盘")
        self.tray_cb.setFont(QFont("Microsoft YaHei", 9))
        self.tray_cb.setStyleSheet(f"color: {LABEL_COLOR};")
        self.tray_cb.setChecked(True)
        opt_row.addWidget(self.tray_cb)

        opt_row.addStretch()
        grid.addLayout(opt_row, 2, 0, 1, 3)

        main_layout.addLayout(grid)

        # ── 信息栏：左归属地(双行) + 右延迟(双行) 水平对齐 ──
        info_layout = QHBoxLayout()
        info_layout.setContentsMargins(0, 2, 0, 0)
        info_layout.setSpacing(8)

        geo_stack = QVBoxLayout()
        geo_stack.setSpacing(0)
        geo_stack.setContentsMargins(0, 0, 0, 0)

        self.geo_proxy_label = QLabel("")
        self.geo_proxy_label.setFont(QFont("Microsoft YaHei", 8))
        self.geo_proxy_label.setStyleSheet(f"color: {LABEL_COLOR};")
        self.geo_proxy_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        geo_stack.addWidget(self.geo_proxy_label)

        self.geo_egress_label = QLabel("")
        self.geo_egress_label.setFont(QFont("Microsoft YaHei", 8))
        self.geo_egress_label.setStyleSheet(f"color: {LABEL_COLOR};")
        self.geo_egress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        geo_stack.addWidget(self.geo_egress_label)

        info_layout.addLayout(geo_stack, 1)

        latency_stack = QVBoxLayout()
        latency_stack.setSpacing(0)
        latency_stack.setContentsMargins(0, 0, 0, 0)

        self.latency_tcp_label = QLabel("")
        self.latency_tcp_label.setFont(QFont("Microsoft YaHei", 8))
        self.latency_tcp_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        latency_stack.addWidget(self.latency_tcp_label)

        self.latency_egress_label = QLabel("")
        self.latency_egress_label.setFont(QFont("Microsoft YaHei", 8))
        self.latency_egress_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        latency_stack.addWidget(self.latency_egress_label)

        info_layout.addLayout(latency_stack)
        main_layout.addLayout(info_layout)

        # ── 状态栏 ──
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 2, 0, 0)

        self.status_label = QLabel("")
        self.status_label.setFont(QFont("Microsoft YaHei", 9))
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()

        self.readme_label = QLabel("ReadMe")
        self.readme_label.setFont(QFont("Microsoft YaHei", 9))
        self.readme_label.setStyleSheet(f"color: {PRIMARY}; text-decoration: underline;")
        self.readme_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.readme_label.mousePressEvent = self.show_info_dialog
        status_layout.addWidget(self.readme_label)

        main_layout.addLayout(status_layout)

        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.clear_inputs)

    # ═══════════════════════════════════════════════════
    #  系统托盘
    # ═══════════════════════════════════════════════════

    def setup_tray(self, icon_path: str):
        self.tray_icon = QSystemTrayIcon(self)
        if os.path.exists(icon_path):
            self.tray_icon.setIcon(QIcon(icon_path))
        else:
            self.tray_icon.setIcon(self.style().standardIcon(
                self.style().SP_ComputerIcon))
        self.tray_icon.setToolTip("代理切换工具 - 已禁用")

        tray_menu = QMenu()

        self.tray_toggle_action = QAction("启用代理", tray_menu)
        self.tray_toggle_action.triggered.connect(self.toggle_proxy)
        tray_menu.addAction(self.tray_toggle_action)

        tray_menu.addSeparator()

        show_action = QAction("显示主窗口", tray_menu)
        show_action.triggered.connect(self._show_window)
        tray_menu.addAction(show_action)

        quit_action = QAction("退出", tray_menu)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    # ═══════════════════════════════════════════════════
    #  快捷操作
    # ═══════════════════════════════════════════════════

    def clear_inputs(self):
        self.ip_entry.clear()
        self.port_entry.clear()
        self.geo_proxy_label.clear()
        self.geo_egress_label.clear()
        self.latency_tcp_label.clear()
        self.latency_egress_label.clear()

    # ═══════════════════════════════════════════════════
    #  持久化
    # ═══════════════════════════════════════════════════

    def load_settings(self):
        try:
            s = QSettings("ProxyTool", "Settings")
            ip = s.value("proxy_ip", "")
            port = s.value("proxy_port", "")
            if ip:
                self.ip_entry.setText(ip)
            if port:
                self.port_entry.setText(port)
            self.tray_cb.setChecked(True)
        except (TypeError, OSError):
            pass

    def save_settings(self):
        try:
            s = QSettings("ProxyTool", "Settings")
            s.setValue("proxy_ip", self.ip_entry.text().strip())
            s.setValue("proxy_port", self.port_entry.text().strip())
            s.setValue("close_to_tray", self.tray_cb.isChecked())
        except (TypeError, OSError):
            pass

    # ═══════════════════════════════════════════════════
    #  代理操作
    # ═══════════════════════════════════════════════════

    def update_status(self):
        status, server = get_current_proxy()
        self._proxy_enabled = (status == "已启用")

        if self._proxy_enabled:
            ip, port, _ = parse_proxy_server(server)
            text = f"✓ 已启用: {ip}:{port}"
            style = f"color: {PRIMARY}; font-weight: bold;"

            self.toggle_btn.setText("取消代理")
            self.toggle_btn.setStyleSheet(
                action_btn_style(DANGER, "#d0b0b0", "#b89090"))
            self.tray_toggle_action.setText("禁用代理")
            self.tray_icon.setToolTip(f"代理切换工具 - 已启用: {ip}:{port}")
        else:
            text = "✗ 已禁用"
            style = f"color: {DANGER}; font-weight: bold;"

            self.toggle_btn.setText("设置代理")
            self.toggle_btn.setStyleSheet(
                action_btn_style(PRIMARY, "#99acbd", "#7d90a3"))
            self.tray_toggle_action.setText("启用代理")
            self.tray_icon.setToolTip("代理切换工具 - 已禁用")

        self.status_label.setText(text)
        self.status_label.setStyleSheet(style)

    def toggle_proxy(self):
        """切换代理状态"""
        if self._proxy_enabled:
            self._disable_proxy()
        else:
            self._enable_proxy()

    def _enable_proxy(self):
        ip = self.ip_entry.text().strip()
        port = self.port_entry.text().strip()

        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            QMessageBox.warning(self, "输入错误", "请输入有效的IP地址格式")
            return
        for part in ip.split('.'):
            if not 0 <= int(part) <= 255:
                QMessageBox.warning(self, "输入错误", "IP各段须在0-255之间")
                return
        if not port or not (1 <= int(port) <= 65535):
            QMessageBox.warning(self, "输入错误", "端口号须在1-65535之间")
            return

        try:
            proxy_server = enable_proxy_registry(ip, port, "HTTP")
            refresh_system()
            self.save_settings()
            self.update_status()

            self.lookup_geo(ip)
            self.test_latency(ip, int(port))
        except (PermissionError, OSError) as e:
            self._show_error(f"注册表写入失败: {e}")

    def _disable_proxy(self):
        try:
            disable_proxy_registry()
            refresh_system()
            self.save_settings()
            self.update_status()
            self.geo_proxy_label.clear()
            self.geo_egress_label.clear()
            self.latency_tcp_label.clear()
            self.latency_egress_label.clear()
        except (PermissionError, OSError) as e:
            self.update_status()
            self._show_error(f"取消代理失败: {e}")

    # ═══════════════════════════════════════════════════
    #  归属地
    # ═══════════════════════════════════════════════════

    def lookup_geo(self, ip: str):
        if is_private_ip(ip):
            self.display_geo({"country": "内网地址", "city": "", "query": ""})
            return
        if ip in self.geo_cache:
            self.display_geo(self.geo_cache[ip])
            return

        self.geo_proxy_label.setText("代理: 查询中...")
        self.geo_proxy_label.setStyleSheet(f"color: {MUTED};")
        self.nm.get(make_geo_request(ip))

    def on_geo_finished(self, reply: QNetworkReply):
        try:
            if reply.error() != QNetworkReply.NoError:
                self.display_geo({"country": "查询失败", "city": reply.errorString(), "query": ""})
                return
            data = parse_geo_response(bytes(reply.readAll()))
            if data.get("status") == "fail":
                self.display_geo({"country": "查询失败", "city": data.get("message", ""), "query": ""})
                return
            ip = data.get("query", "")
            if ip:
                self.geo_cache[ip] = data
            self.display_geo(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.display_geo({"country": "解析失败", "city": "", "query": ""})
        except Exception:
            self.display_geo({"country": "查询异常", "city": "", "query": ""})
        finally:
            reply.deleteLater()

    def display_geo(self, data: dict):
        country = data.get("country", "")
        city = data.get("city", "")
        ip = data.get("query", "")
        parts = [p for p in [country, city, ip] if p]
        if parts:
            self.geo_proxy_label.setText("代理: " + " / ".join(parts))
            self.geo_proxy_label.setStyleSheet(f"color: {TEXT_COLOR};")
        else:
            self.geo_proxy_label.setText("代理: 无数据")
            self.geo_proxy_label.setStyleSheet(f"color: {MUTED};")

    # ═══════════════════════════════════════════════════
    #  延迟
    # ═══════════════════════════════════════════════════

    def test_latency(self, ip: str, port: int):
        if self.latency_tester and self.latency_tester.isRunning():
            self.latency_tester.cancel()
            self.latency_tester.wait(500)

        self.latency_tcp_label.setText("到代理: 检测中...")
        self.latency_tcp_label.setStyleSheet(f"color: {MUTED};")
        self.latency_egress_label.setText("出口: 检测中...")
        self.latency_egress_label.setStyleSheet(f"color: {MUTED};")
        self.geo_egress_label.clear()

        self.latency_tester = LatencyTester(ip, port, "HTTP", timeout=5, parent=self)
        self.latency_tester.result_ready.connect(self.on_latency_result)
        self.latency_tester.finished.connect(self._cleanup_latency)
        self.latency_tester.start()

    def on_latency_result(self, tcp_ms: float, egress_ms: float,
                          egress_geo: dict, error: str):
        if tcp_ms > 0:
            color = SUCCESS_GREEN if tcp_ms < 100 else (
                WARNING_ORANGE if tcp_ms < 500 else ERROR_RED)
            self.latency_tcp_label.setText(
                f'<span style="color:{color};">到代理: {tcp_ms:.0f}ms</span>')
        else:
            err_map = {-1: "超时", -2: "拒绝", -3: "不可达", -4: "失败"}
            self.latency_tcp_label.setText(
                f'<span style="color:{ERROR_RED};">到代理: {err_map.get(tcp_ms, "失败")}</span>')

        if egress_ms > 0:
            color = SUCCESS_GREEN if egress_ms < 300 else (
                WARNING_ORANGE if egress_ms < 1000 else ERROR_RED)
            self.latency_egress_label.setText(
                f'<span style="color:{color};">出口: {egress_ms:.0f}ms</span>')
            if egress_geo:
                country = egress_geo.get("country", "")
                city = egress_geo.get("city", "")
                exit_ip = egress_geo.get("query", "")
                eparts = [p for p in [country, city, exit_ip] if p]
                if eparts:
                    self.geo_egress_label.setText("出口: " + " / ".join(eparts))
                    self.geo_egress_label.setStyleSheet(f"color: {TEXT_COLOR};")
        elif egress_ms < 0:
            self.latency_egress_label.setText(
                f'<span style="color:{ERROR_RED};">出口: 失败</span>')

    def _cleanup_latency(self):
        if self.latency_tester:
            self.latency_tester.deleteLater()
            self.latency_tester = None

    # ═══════════════════════════════════════════════════
    #  测试连接
    # ═══════════════════════════════════════════════════

    def on_test_connection(self):
        ip = self.ip_entry.text().strip()
        port = self.port_entry.text().strip()
        if not ip or not port:
            QMessageBox.warning(self, "输入不完整", "请先填写代理地址和端口")
            return
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            QMessageBox.warning(self, "输入错误", "请输入有效的IP地址格式")
            return
        port_int = int(port)
        if not (1 <= port_int <= 65535):
            QMessageBox.warning(self, "输入错误", "端口号须在1-65535之间")
            return

        self.test_button.setEnabled(False)
        self.test_button.setText("...")

        self.lookup_geo(ip)
        self.test_latency(ip, port_int)

        self._test_check_count = 0
        self._test_timer = self.startTimer(200)

    def timerEvent(self, event):
        if not hasattr(self, '_test_timer') or self._test_timer is None:
            return
        self._test_check_count += 1
        geo_done = not self.geo_proxy_label.text().endswith("查询中...")
        lat_done = (not self.latency_tcp_label.text().endswith("检测中...") and
                    not self.latency_egress_label.text().endswith("检测中..."))
        if geo_done and lat_done or self._test_check_count > 30:
            self.killTimer(self._test_timer)
            self._test_timer = None
            self.test_button.setEnabled(True)
            self.test_button.setText("测试连接")
            self.test_button.setFocus()

    # ═══════════════════════════════════════════════════
    #  ReadMe
    # ═══════════════════════════════════════════════════

    def show_info_dialog(self, event):
        html = """
        <div style='font-family:"Microsoft YaHei";font-size:10pt;'>
            <h3 style="color:#8b9eb0;text-align:center;margin:3px 0 8px 0;">代理快速切换工具</h3>
            <p style="color:#8a8885;margin:1px 0;">输入代理地址和端口，一键切换</p>
            <p style="color:#8a8885;margin:1px 0;">自动查询代理归属地 + 出口 IP</p>
            <p style="color:#8a8885;margin:1px 0;">到代理延迟 + 出口延迟双段检测</p>
            <p style="color:#8a8885;margin:1px 0;">最小化 / 关闭可缩到托盘，右键一键切换</p>
            <p style="color:#8a8885;margin:1px 0;">Enter 切换 | Esc 清空</p>
            <p style="color:#8a8885;margin:8px 0 2px 0;">
                反馈：<b style="color:#8b9eb0;">rizona.cn@gmail.com</b>
            </p>
        </div>"""
        msg = QMessageBox(self)
        msg.setWindowTitle("ReadMe")
        msg.setIcon(QMessageBox.NoIcon)
        msg.setTextFormat(Qt.RichText)
        msg.setText(html)
        msg.setStandardButtons(QMessageBox.Ok)
        msg.adjustSize()
        # 严格居中于主窗口
        sh = msg.sizeHint()
        geo = self.frameGeometry()
        msg.move(geo.x() + (geo.width() - sh.width()) // 2,
                 geo.y() + (geo.height() - sh.height()) // 2)
        msg.exec_()

    # ═══════════════════════════════════════════════════
    #  窗口事件
    # ═══════════════════════════════════════════════════

    def changeEvent(self, event):
        if event.type() == event.WindowStateChange and self.isMinimized():
            if self.tray_cb.isChecked():
                self.hide()
                event.ignore()
                return
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.tray_cb.isChecked():
            self.hide()
            event.ignore()
        else:
            if self.latency_tester and self.latency_tester.isRunning():
                self.latency_tester.cancel()
                self.latency_tester.wait(1500)
            self.tray_icon.hide()
            event.accept()

    def _show_error(self, message: str):
        QMessageBox.critical(self, "错误", message)
