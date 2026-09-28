#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
#  代理切换工具 —— macOS 一键打包脚本（.app + .dmg）
#
#  用法（在 macOS 上执行）：
#      chmod +x build_macos.sh
#      ./build_macos.sh
#
#  产物：
#      dist/代理切换工具.app
#      dist/代理切换工具 v1.01.dmg
#
#  前置条件：
#      · macOS 11+，已装 python3（推荐 python.org 官方包，自带 tkinter）
#      · pip install pyinstaller
#      · 系统自带 sips / iconutil / hdiutil（无需额外安装）
#
#  说明：
#      必须在本机 macOS 上打包 —— PyInstaller 不支持跨平台编译，
#      Windows/Linux 无法产出 macOS 可执行文件。
# ══════════════════════════════════════════════════════════════
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="代理切换工具"
VERSION="$(python3 -c 'import version; print(version.VERSION)' 2>/dev/null || echo 1.01)"
VOL_NAME="${APP_NAME} v${VERSION}"
DMG_PATH="dist/${VOL_NAME}.dmg"

echo "══════════════════════════════════════════"
echo " 打包 ${APP_NAME} v${VERSION} (macOS)"
echo "══════════════════════════════════════════"

# ── 1. 环境检查 ─────────────────────────────────────────────
command -v python3 >/dev/null || { echo "✗ 未找到 python3"; exit 1; }
python3 -c 'import tkinter' 2>/dev/null || {
    echo "✗ 当前 python3 缺少 tkinter。"
    echo "  请改用 python.org 官方安装包（含 tcl/tk），或"
    echo "  brew install python-tk"
    exit 1
}
python3 -m PyInstaller --version >/dev/null 2>&1 || {
    echo "✗ 未安装 PyInstaller，请执行： pip3 install pyinstaller"
    exit 1
}

# ── 2. 生成 app.icns（从 app.ico / app.png 转换） ────────────
make_icns() {
    if [ -f app.icns ] && [ -f app.png ] && [ app.icns -nt app.ico ]; then
        echo "· app.icns 已是最新，跳过"
        return
    fi
    echo "· 生成 app.icns …"

    # 2a. 先确保有高分辨率 PNG 源（sips 对 .ico 支持不稳，
    #     用纯标准库脚本从 ico 里抽出内嵌的 256x256 PNG）
    if [ ! -f app.png ] && [ -f app.ico ]; then
        python3 tools_ico2png.py || true
    fi

    ICONSET="build/AppIcon.iconset"
    rm -rf "$ICONSET"
    mkdir -p "$ICONSET"

    SRC=""
    [ -f app.png ] && SRC="app.png"
    if [ -z "$SRC" ]; then
        echo "  ⚠ 没有 app.png / app.ico，将使用系统默认图标"
        return 1
    fi

    # 标准 iconset 规格
    for spec in "16 icon_16x16" "32 icon_16x16@2x" "32 icon_32x32" \
                "64 icon_32x32@2x" "128 icon_128x128" "256 icon_128x128@2x" \
                "256 icon_256x256" "512 icon_256x256@2x" "512 icon_512x512" \
                "1024 icon_512x512@2x"; do
        set -- $spec
        size="$1"; name="$2"
        sips -z "$size" "$size" "$SRC" --out "$ICONSET/${name}.png" >/dev/null 2>&1 || true
    done

    iconutil -c icns "$ICONSET" -o app.icns
    echo "  ✓ app.icns"
}
make_icns || true

# ── 3. PyInstaller 打包 .app ────────────────────────────────
echo "· PyInstaller 打包 .app …"
rm -rf build dist
python3 -m PyInstaller --clean --noconfirm ProxyTool-macos.spec

APP_BUNDLE="dist/${APP_NAME}.app"
[ -d "$APP_BUNDLE" ] || { echo "✗ 打包失败：未生成 $APP_BUNDLE"; exit 1; }
echo "  ✓ $APP_BUNDLE"

# ── 4. 去掉隔离属性（本机自签场景），按需签名 ───────────────
xattr -cr "$APP_BUNDLE" 2>/dev/null || true
# 如需正式签名，取消下一行注释并替换证书名：
# codesign --deep --force --sign "Developer ID Application: Your Name (TEAMID)" "$APP_BUNDLE"

# ── 5. 制作 .dmg ────────────────────────────────────────────
echo "· 制作 .dmg …"
STAGE="build/dmg_stage"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP_BUNDLE" "$STAGE/"
ln -s /Applications "$STAGE/Applications"     # 拖拽安装提示

hdiutil create -volname "$VOL_NAME" \
    -srcfolder "$STAGE" \
    -ov -format UDZO \
    "$DMG_PATH"

echo
echo "══════════════════════════════════════════"
echo " ✓ 打包完成"
echo "   APP : $APP_BUNDLE"
echo "   DMG : $DMG_PATH"
echo "   体积: $(du -h "$DMG_PATH" | cut -f1)"
echo "══════════════════════════════════════════"
echo
echo "提示：未签名版本首次打开会被 Gatekeeper 拦下。"
echo "     解决办法：右键 →「打开」→ 确认；或执行"
echo "     xattr -cr \"/Applications/${APP_NAME}.app\""
