# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 —— macOS (.app)

用法（必须在 macOS 上执行）：
    pip install pyinstaller
    pyinstaller --clean --noconfirm ProxyTool-macos.spec
    # 产物：dist/代理切换工具.app

与 Windows 版 ProxyTool.spec 的差异：
  · BUNDLE 段把可执行文件包成 .app（macOS 应用束）
  · 图标用 app.icns（Windows 用 app.ico）
  · 无版本资源段（VSVersionInfo 是 Windows 专有）
  · 排除清单相同（不引入任何第三方重型库）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))

try:
    from version import VERSION, APP_NAME
except Exception:
    VERSION, APP_NAME = "0.0.0", "ProxyTool"

block_cipher = None

EXCLUDES = [
    "PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken2", "shiboken6",
    "numpy", "scipy", "pandas", "matplotlib", "sympy",
    "cv2",
    "setuptools", "pkg_resources", "pip", "wheel",
    "unittest", "pydoc", "doctest", "pdb",
    "lib2to3", "idlelib", "turtledemo", "curses",
    "sqlite3", "multiprocessing", "concurrent", "asyncio",
    "lzma", "bz2", "xml", "xmlrpc",
    # Windows 专有（macOS 上不存在，显式排除避免收集警告）
    "win32com", "pythoncom", "pywin32", "winreg",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        # 图标（macOS 用 .icns；同时带上 PNG 以便 Tk iconphoto）
        ("app.icns", "."),
        ("app.png", "."),
        # 版本号模块等随包一起进去（运行时 import）
        ("version.py", "."),
        ("oplog.py", "."),
        ("platform_ops.py", "."),
    ],
    hiddenimports=[
        "tkinter", "tkinter.ttk", "tkinter.font", "tkinter.messagebox",
        "ipaddress",
        "urllib.request", "urllib.error", "urllib.parse",
        "email", "email.message", "email.parser", "email.feedparser",
        "email.utils", "email._policybase", "email.encoders",
        "http", "http.client", "http.cookiejar",
        "ssl", "_ssl", "hashlib", "logging", "uuid",
        "base64", "binascii", "zlib", "socket", "select",
        "tempfile", "shutil", "copyreg", "random", "collections",
        # macOS 系统代理读写依赖
        "subprocess", "fcntl",
        # 可选托盘（装了才打进包；没装也无妨，运行时优雅降级）
        "rumps", "pystray", "PIL", "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    upx=False,                 # macOS 上不建议 UPX（会出现签名/加载问题）
    runtime_tmpdir=None,
    console=False,             # 无控制台（.app 双击即用）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,          # 需要通用二进制时可设 "universal2"
    codesign_identity=None,    # 如需签名填 "Developer ID Application: ..."
    entitlements_file=None,
    icon="app.icns",
)

app = BUNDLE(
    exe,
    name=f"{APP_NAME}.app",
    icon="app.icns",
    bundle_identifier="cn.rizona.proxytool",
    version=VERSION,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # 定位「系统设置」用途：无网络权限需求，但声明更清晰
        "NSRequiresAquaSystemAppearance": False,
    },
)
