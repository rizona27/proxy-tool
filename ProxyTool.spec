# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 瘦身版

体积优化策略：
  1. 排除 Qt / numpy / PIL / 科学计算等全部未使用的大体积第三方模块
  2. 只保留 tkinter + 本项目源码所需的标准库
  3. UPX 压缩二进制（需 upx.exe 在同目录）
  4. 单文件模式，无控制台窗口

注意：
  不要排除项目实际用到的标准库（json / urllib.request / traceback /
  ipaddress / winreg / queue / socket / threading / subprocess / re 等），
  否则打包后运行时会直接 ImportError。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))

# ── 版本号：从唯一的 version.py 读取，改那一处即可 ──
try:
    from version import VERSION, VERSION_TUPLE, APP_NAME  # noqa: E402
except Exception:                                     # pragma: no cover
    VERSION, VERSION_TUPLE, APP_NAME = "0.0.0", (0, 0, 0, 0), "ProxyTool"

block_cipher = None

# ── 排除清单：只排除确定未使用的「第三方重型库」 ──
#
# 重要教训：不要排除标准库！
# urllib.request 的依赖链会用到 email / http / ssl / hashlib / logging /
# uuid / base64 / zlib 等；一旦排除，定时弹出的
# 「Failed to obtain/convert traceback!」就是它们导致的 ImportError。
# PyInstaller 本身只打包被真实引用的模块，标准库留着几乎不占体积。
EXCLUDES = [
    # Qt 全家桶（旧版用的 PyQt5，现在完全不再需要）
    "PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken2", "shiboken6",
    # 科学计算 / 数据处理
    "numpy", "scipy", "pandas", "matplotlib", "sympy",
    # 图像处理
    "PIL", "Pillow", "cv2",
    # 构建 / 测试工具链（运行时完全用不到）
    "setuptools", "pkg_resources", "pip", "wheel",
    "unittest", "pydoc", "doctest", "pdb",
    "lib2to3", "idlelib", "turtledemo", "curses",
    # 重型且未使用的标准库运行时（与 urllib 依赖链无关）
    "sqlite3", "multiprocessing", "concurrent", "asyncio",
    "lzma", "bz2", "xml", "xmlrpc",
    # 第三方托盘库（已改用 ctypes 自实现）
    "win32com", "pythoncom", "pywin32", "pystray",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("app.ico", "."),
        # 版本号模块与倒序日志模块要随包一起进去（运行时 import）
        ("version.py", "."),
        ("oplog.py", "."),
        # 跨平台系统层（注册表 / networksetup 等平台差异都收在这里）
        ("platform_ops.py", "."),
    ],
    hiddenimports=[
        "tkinter", "tkinter.ttk", "tkinter.font", "tkinter.messagebox",
        "ipaddress", "winreg",
        # urllib 依赖链（静态分析可能漏掉动态导入的部分）
        "urllib.request", "urllib.error", "urllib.parse",
        "email", "email.message", "email.parser", "email.feedparser",
        "email.utils", "email._policybase", "email.encoders",
        "http", "http.client", "http.cookiejar",
        "ssl", "_ssl", "hashlib", "logging", "uuid",
        "base64", "binascii", "zlib", "socket", "select",
        "tempfile", "shutil", "copyreg", "random", "collections",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── exe 版本资源（属性页 → 详细信息） ──
# version= 需要的是 PyInstaller 的 VSVersionInfo 对象，不是普通元组
try:
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
        StringStruct, VarFileInfo, VarStruct,
    )

    _v = VERSION_TUPLE
    _ver = f"{_v[0]}.{_v[1]}.{_v[2]}.{_v[3]}"
    version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=_v, prodvers=_v, mask=0x3f, flags=0x0,
            OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("080404B0", [
                StringStruct("CompanyName", APP_NAME),
                StringStruct("FileDescription", f"{APP_NAME} v{VERSION}"),
                StringStruct("FileVersion", _ver),
                StringStruct("InternalName", "ProxyTool"),
                StringStruct("LegalCopyright", "Copyright (c) 2026"),
                StringStruct("OriginalFilename", "ProxyTool.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", VERSION),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0804, 1200])]),
        ],
    )
except Exception:                                # pragma: no cover
    version_info = None

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ProxyTool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["vcruntime140.dll", "python3*.dll"],
    runtime_tmpdir=None,
    console=False,                 # 无控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="app.ico",
    # ── 版本资源：exe 属性页里显示的版本号，来自 version.py ──
    version=version_info,
)
