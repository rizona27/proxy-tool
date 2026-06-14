# 代理切换工具 (Proxy Tool)

Windows 平台 HTTP 代理一键切换工具。莫兰迪色系界面，支持系统托盘、归属地查询、延迟检测。

## 功能

- **一键切换**：输入 IP 和端口，点击按钮或按 Enter 切换代理状态
- **系统托盘**：最小化/关闭缩到托盘，右键菜单一键切换，双击恢复窗口
- **归属地查询**：自动查询代理服务器 IP 的国家、城市
- **出口 IP 检测**：通过代理访问公网，显示实际出口 IP 及归属地
- **双段延迟**：TCP 到代理延迟 + HTTP 代理出口延迟
- **记忆配置**：自动保存上次使用的代理地址和端口

## 系统要求

- Windows 10/11（64 位）
- 无需安装 Python 环境（已打包为 exe）

## 使用方式

### 打包版（推荐）

| 版本 | 文件 | 说明 |
|------|------|------|
| 单文件 | `ProxyTool.exe` | 单个 exe，拷贝即用 |
| 便携版 | `ProxyTool_portable/` | 文件夹模式，启动更快 |

双击运行，首次启动请求管理员权限（修改系统代理需要）。

### 源码运行

```bash
pip install PyQt5
python main.py
```

## 界面

```
┌──────────────────────────────────────┐
│ 代理地址: [______________] [测试连接] │
│ 代理端口: [______________] [设置代理] │
│           ☑ 最小化到托盘             │
│                                      │
│ 代理: 中国/北京/1.2.3.4     到代理: 45ms
│ 出口: 美国/LA/5.6.7.8      出口: 224ms
│                                      │
│ ✓ 已启用: 1.2.3.4:8080      ReadMe  │
└──────────────────────────────────────┘
```

## 快捷键

| 按键 | 功能 |
|------|------|
| Enter | 切换代理（启用/禁用） |
| Esc | 清空输入 |

## 技术实现

- **GUI**：PyQt5 (Fusion 风格)
- **代理设置**：Windows 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings`
- **归属地**：ip-api.com 免费 API（异步）
- **延迟**：TCP socket + urllib HTTP 往返测时（独立线程）
- **打包**：PyInstaller

## 模块结构

```
proxy-tool/
├── main.py              # 入口 + 管理员提权
├── main_window.py       # 主窗口 UI + 逻辑
├── styles.py            # 莫兰迪色系样式常量
├── ip_line_edit.py      # IP 地址自动分段输入框
├── latency_tester.py    # TCP + HTTP 出口延迟检测线程
├── proxy_core.py        # 注册表读写 + 归属地辅助
└── logo.ico             # 图标
```

## 打包

```bash
pip install pyinstaller
pyinstaller ProxyTool.spec
```

产出：
- `dist/ProxyTool.exe` — 单文件版 (~39 MB)
- `dist/ProxyTool_portable/` — 文件夹版 (~99 MB)

## 反馈

rizona.cn@gmail.com

---

**版本**: 2.0 | **许可**: MIT
