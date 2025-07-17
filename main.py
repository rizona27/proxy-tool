import sys
import os
import winreg
import ctypes
import re
import atexit
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QLineEdit, QPushButton, QTextEdit, QMessageBox, QGroupBox,
                             QFrame, QGridLayout, QSizePolicy)
from PyQt5.QtGui import QFont, QPalette, QColor, QIcon, QIntValidator, QCursor
from PyQt5.QtCore import Qt, QSettings

def resource_path(relative_path):
    """获取资源的绝对路径，支持开发环境和打包后环境"""
    try:
        # PyInstaller创建临时文件夹时会设置_MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class IPLineEdit(QLineEdit):
    """自定义IP地址输入框，实现自动分段"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Microsoft YaHei", 10))
        self.setStyleSheet("""
            QLineEdit {
                background-color: #f7f9fc;
                color: #3a506b;
                border: 1px solid #d0d7e2;
                border-radius: 6px;
                padding: 8px 12px;
                height: 36px;
            }
            QLineEdit:focus {
                border: 1px solid #a5b8d1;
            }
        """)
        self.textChanged.connect(self.format_ip)
        
    def format_ip(self):
        """格式化IP地址，每3位自动添加点号"""
        text = self.text().replace(" ", "")
        
        # 移除多余的点号
        if '..' in text:
            text = text.replace('..', '.')
        
        # 限制输入为数字和点号
        cleaned = re.sub(r'[^\d\.]', '', text)
        
        # 自动分段逻辑
        parts = cleaned.split('.')
        new_parts = []
        for i, part in enumerate(parts):
            if i >= 4:  # 限制最多4段
                break
            if len(part) > 3:  # 每段最多3位数字
                new_parts.append(part[:3])
                if i < 3:
                    new_parts.append(part[3:])
            else:
                new_parts.append(part)
        
        # 重新组合IP
        formatted = '.'.join(new_parts[:4])
        
        if formatted != text:
            self.blockSignals(True)
            self.setText(formatted)
            self.blockSignals(False)
        
        # 设置最大长度
        if len(formatted) > 15:
            self.setText(formatted[:15])

class ProxyTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("代理切换工具")
        self.setFixedSize(480, 320)
        
        # 设置窗口图标 - 使用资源路径
        icon_path = resource_path("logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # 创建主控件
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        
        # 设置背景
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#f0f3f7"))
        self.setPalette(palette)
        
        # 主布局
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(15, 15, 15, 10)  # 调整边距
        self.main_layout.setSpacing(10)
        
        # 内容区域 - 使用网格布局
        self.grid_layout = QGridLayout()
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setHorizontalSpacing(8)  # 增加水平间距
        self.grid_layout.setVerticalSpacing(10)
        self.grid_layout.setColumnStretch(1, 1)  # 设置列拉伸因子
        self.main_layout.addLayout(self.grid_layout)
        
        # 代理地址标签
        ip_label = QLabel("代理地址：")
        ip_label.setFont(QFont("Microsoft YaHei", 10))
        ip_label.setStyleSheet("color: #5a6d8a; padding-right: 5px;")  # 添加右内边距
        ip_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.grid_layout.addWidget(ip_label, 0, 0)
        
        # 代理地址输入框
        self.ip_entry = IPLineEdit()
        self.ip_entry.setPlaceholderText("例如: 192.168.1.1")
        self.grid_layout.addWidget(self.ip_entry, 0, 1)
        
        # 设置代理按钮
        self.set_button = QPushButton("设置代理")
        self.set_button.setFont(QFont("Microsoft YaHei", 10))
        self.set_button.setFixedHeight(36)
        self.set_button.setMinimumWidth(80)
        self.set_button.setStyleSheet("""
            QPushButton {
                background-color: #5b7cfa;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 8px;
                margin-left: 10px;  /* 增加左外边距 */
            }
            QPushButton:hover {
                background-color: #4a6be5;
            }
            QPushButton:pressed {
                background-color: #3a5ad0;
            }
        """)
        self.set_button.setCursor(Qt.PointingHandCursor)
        self.set_button.clicked.connect(self.enable_proxy)
        self.grid_layout.addWidget(self.set_button, 0, 2)
        
        # 代理端口标签
        port_label = QLabel("代理端口：")
        port_label.setFont(QFont("Microsoft YaHei", 10))
        port_label.setStyleSheet("color: #5a6d8a; padding-right: 5px;")  # 添加右内边距
        port_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.grid_layout.addWidget(port_label, 1, 0)
        
        # 代理端口输入框
        self.port_entry = QLineEdit()
        self.port_entry.setFont(QFont("Microsoft YaHei", 10))
        self.port_entry.setStyleSheet(self.ip_entry.styleSheet())
        self.port_entry.setPlaceholderText("例如: 8080")
        
        # 设置端口验证器
        port_validator = QIntValidator(0, 99999, self.port_entry)
        self.port_entry.setValidator(port_validator)
        self.port_entry.setMaxLength(5)
        self.grid_layout.addWidget(self.port_entry, 1, 1)
        
        # 取消代理按钮
        self.disable_button = QPushButton("取消代理")
        self.disable_button.setFont(QFont("Microsoft YaHei", 10))
        self.disable_button.setFixedHeight(36)
        self.disable_button.setMinimumWidth(80)
        self.disable_button.setStyleSheet("""
            QPushButton {
                background-color: #ff7e5f;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 5px 8px;
                margin-left: 10px;  /* 增加左外边距 */
            }
            QPushButton:hover {
                background-color: #ee6d4f;
            }
            QPushButton:pressed {
                background-color: #dd5c3f;
            }
        """)
        self.disable_button.setCursor(Qt.PointingHandCursor)
        self.disable_button.clicked.connect(self.disable_proxy)
        self.grid_layout.addWidget(self.disable_button, 1, 2)
        
        # 操作结果区域 - 优化设计
        self.result_group = QGroupBox("操作结果")
        self.result_group.setStyleSheet("""
            QGroupBox {
                background-color: white;
                border-radius: 12px;
                padding: 2px;
                margin-top: 12px;
                border: none;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
                background-color: white;
                color: #4a6fa5;
                font-weight: bold;
                font-size: 11px;
            }
        """)
        
        self.result_layout = QVBoxLayout(self.result_group)
        self.result_layout.setContentsMargins(5, 12, 5, 5)  # 优化边距
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Microsoft YaHei", 9))
        self.result_text.setStyleSheet("""
            QTextEdit {
                background-color: white;
                color: #5a6d8a;
                border: none;
                border-radius: 6px;
                padding: 5px;
            }
        """)
        # 设置高度策略，允许根据需要扩展
        self.result_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.result_text.setMinimumHeight(50)  # 最小高度
        self.result_text.setMaximumHeight(80)  # 最大高度
        self.result_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # 禁用垂直滚动条
        self.result_layout.addWidget(self.result_text)
        
        self.main_layout.addWidget(self.result_group)
        
        # 状态信息布局
        self.status_layout = QHBoxLayout()
        self.status_layout.setContentsMargins(0, 10, 0, 0)  # 增加上边距
        self.main_layout.addLayout(self.status_layout)
        
        # 状态显示 - 左对齐
        self.status_label = QLabel()
        self.status_label.setFont(QFont("Microsoft YaHei", 9))
        self.status_layout.addWidget(self.status_label)
        
        # 添加弹性空间
        self.status_layout.addStretch()
        
        # ReadMe链接 - 右下角
        self.author_label = QLabel("ReadMe")
        self.author_label.setFont(QFont("Microsoft YaHei", 9))
        self.author_label.setStyleSheet("""
            color: #5b7cfa;
            text-decoration: underline;
        """)
        self.author_label.setCursor(QCursor(Qt.PointingHandCursor))
        self.author_label.mousePressEvent = self.show_info_dialog
        self.status_layout.addWidget(self.author_label)
        
        # 初始化状态
        self.update_status()
        
        # 加载保存的代理设置
        self.load_proxy_settings()
        
        # 在操作结果栏显示欢迎信息
        self.result_text.setHtml("""
            <div style='color:#5a6d8a; font-size:9pt; text-align:left; margin-top:0;'>
                请设置代理或取消当前代理
            </div>
        """)
    
    def show_info_dialog(self, event):
        """显示信息对话框"""
        info_html = """
        <div style='font-family: "Microsoft YaHei"; font-size: 10pt;'>
            <h3 style='color: #5b7cfa; text-align: center; margin: 5px 0 8px 0;'>代理快速切换工具</h3>
            
            <p style='color: #5a6d8a; margin: 3px 0;'><b>核心功能：</b></p>
            <ul style='color: #5a6d8a; margin: 3px 0 8px 0; padding-left: 15px;'>
                <li style='margin-bottom: 3px;'><b>即时配置</b>：输入代理地址和端口，一键切换，实时生效</li>
                <li style='margin-bottom: 3px;'><b>智能记忆</b>：自动保存上次设置，减少重复操作</li>
                <li style='margin-bottom: 3px;'><b>状态可视化</b>：底部实时展示当前代理状态</li>
            </ul>
            
            <p style='color: #5a6d8a; margin: 8px 0 3px 0;'>
                反馈与建议：
                <br><b style='color: #5b7cfa;'>rizona.cn@gmail.com</b>
            </p>
        </div>
        """
        
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("ReadMe")
        msg_box.setIcon(QMessageBox.NoIcon)
        msg_box.setTextFormat(Qt.RichText)
        msg_box.setText(info_html)
        
        # 设置对话框样式
        msg_box.setStyleSheet("""
            QMessageBox {
                background-color: #f0f3f7;
                min-width: 300px;
                max-width: 350px;
            }
            QLabel {
                min-height: 200px;
                padding: 8px;
            }
            QPushButton {
                min-width: 70px;
                padding: 4px;
            }
        """)
        
        # 移除标准按钮，只保留OK
        msg_box.setStandardButtons(QMessageBox.Ok)
        
        msg_box.exec_()
    
    def load_proxy_settings(self):
        """加载保存的代理设置"""
        try:
            settings = QSettings("ProxyTool", "Settings")
            saved_ip = settings.value("proxy_ip", "")
            saved_port = settings.value("proxy_port", "")
            
            if saved_ip and saved_port:
                self.ip_entry.setText(saved_ip)
                self.port_entry.setText(saved_port)
        except:
            pass
    
    def save_proxy_settings(self):
        """保存代理设置"""
        try:
            settings = QSettings("ProxyTool", "Settings")
            settings.setValue("proxy_ip", self.ip_entry.text().strip())
            settings.setValue("proxy_port", self.port_entry.text().strip())
        except:
            pass
    
    def update_status(self):
        """更新状态显示"""
        status, server = self.get_current_proxy()
        
        if status == "已启用":
            status_text = f"✓ 当前代理已启用: {server}"
            style = "color: #5b7cfa; font-weight: bold;"
        else:
            status_text = "✗ 当前代理已禁用"
            style = "color: #ff7e5f; font-weight: bold;"
        
        self.status_label.setText(status_text)
        self.status_label.setStyleSheet(style)
    
    def get_current_proxy(self):
        """获取当前代理设置"""
        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            )
            
            enabled, _ = winreg.QueryValueEx(reg_key, "ProxyEnable")
            status = "已启用" if enabled else "已禁用"
            
            try:
                server, _ = winreg.QueryValueEx(reg_key, "ProxyServer")
            except:
                server = "未设置"
            
            winreg.CloseKey(reg_key)
            return status, server
        except:
            return "未知", "无法获取"
    
    def enable_proxy(self):
        """启用代理"""
        ip = self.ip_entry.text().strip()
        port = self.port_entry.text().strip()
        
        # 验证IP地址格式
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            QMessageBox.warning(self, "输入错误", "请输入有效的IP地址格式（例如：192.168.1.1）")
            return
        
        # 验证IP地址各段数值
        ip_parts = ip.split('.')
        for part in ip_parts:
            if not 0 <= int(part) <= 255:
                QMessageBox.warning(self, "输入错误", "IP地址各段必须在0-255之间")
                return
        
        if not port:
            QMessageBox.warning(self, "输入错误", "请填写端口号")
            return
        
        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_WRITE
            )
            
            winreg.SetValueEx(reg_key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            proxy_server = f"{ip}:{port}"
            winreg.SetValueEx(reg_key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)
            winreg.CloseKey(reg_key)
            
            self.refresh_system()
            
            # 保存设置
            self.save_proxy_settings()
            
            # 更新结果
            html = f"""
            <div style='color:#5b7cfa; font-weight:bold; font-size:10pt;'>✓ 操作成功!</div>
            <div style='margin-top:3px; color:#5a6d8a; font-size:9pt;'>已启用代理: <b>{proxy_server}</b></div>
            """
            self.result_text.setHtml(html)
            
        except Exception as e:
            html = f"""
            <div style='color:#ff7e5f; font-weight:bold; font-size:10pt;'>✗ 操作失败</div>
            <div style='margin-top:3px; color:#5a6d8a; font-size:9pt;'>{str(e)}</div>
            """
            self.result_text.setHtml(html)
    
    def disable_proxy(self):
        """禁用代理"""
        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                0, winreg.KEY_WRITE
            )
            
            winreg.SetValueEx(reg_key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            winreg.CloseKey(reg_key)
            
            self.refresh_system()
            
            # 更新结果
            html = f"""
            <div style='color:#5b7cfa; font-weight:bold; font-size:10pt;'>✓ 操作成功!</div>
            <div style='margin-top:3px; color:#5a6d8a; font-size:9pt;'>已禁用代理</div>
            """
            self.result_text.setHtml(html)
            
        except Exception as e:
            html = f"""
            <div style='color:#ff7e5f; font-weight:bold; font-size:10pt;'>✗ 操作失败</div>
            <div style='margin-top:3px; color:#5a6d8a; font-size:9pt;'>{str(e)}</div>
            """
            self.result_text.setHtml(html)
    
    def refresh_system(self):
        """刷新资源管理器"""
        # 使用更安全的刷新方式
        INTERNET_OPTION_SETTINGS_CHANGED = 39
        INTERNET_OPTION_REFRESH = 37
        
        internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
        internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)
        
        # 更新UI状态
        self.update_status()

def is_admin():
    """检查管理员权限"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def run_as_admin():
    """以管理员权限运行"""
    # 获取当前可执行文件路径
    if getattr(sys, 'frozen', False):
        application_path = sys.executable
    else:
        application_path = sys.argv[0]
    
    # 使用ShellExecuteW请求管理员权限
    ctypes.windll.shell32.ShellExecuteW(None, "runas", application_path, "", None, 1)

if __name__ == "__main__":
    # 检查管理员权限
    if not is_admin():
        # 请求管理员权限
        run_as_admin()
        sys.exit(0)  # 正常退出当前实例
    
    app = QApplication(sys.argv)
    
    # 设置应用样式
    app.setStyle("Fusion")
    
    # 创建自定义调色板
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f0f3f7"))
    palette.setColor(QPalette.WindowText, QColor("#3a506b"))
    palette.setColor(QPalette.Base, QColor("#ffffff"))
    palette.setColor(QPalette.AlternateBase, QColor("#f7f9fc"))
    palette.setColor(QPalette.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ToolTipText, QColor("#3a506b"))
    palette.setColor(QPalette.Text, QColor("#3a506b"))
    palette.setColor(QPalette.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ButtonText, QColor("#3a506b"))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor("#5b7cfa"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
    
    # 设置全局字体
    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)
    
    window = ProxyTool()
    window.show()
    
    # 注册退出处理函数
    atexit.register(lambda: os._exit(0))
    
    sys.exit(app.exec_())