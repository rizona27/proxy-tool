@echo off
REM ══════════════════════════════════════════════════════════════
REM  代理切换工具 —— Windows 一键打包脚本 (.exe)
REM
REM  用法（在 Windows 上双击或命令行执行）：
REM      build_windows.bat
REM
REM  产物：
REM      dist\ProxyTool.exe
REM
REM  前置条件：
REM      · 已装 Python 3.10+（python.org 官方包，自带 tkinter）
REM      · pip install pyinstaller
REM ══════════════════════════════════════════════════════════════
setlocal

cd /d "%~dp0"

echo ══════════════════════════════════════════
echo  打包 代理切换工具 ^(Windows^)
echo ══════════════════════════════════════════

where python >nul 2>nul
if errorlevel 1 (
    echo [X] 未找到 python，请安装 python.org 官方包并加入 PATH
    exit /b 1
)

python -c "import tkinter" 2>nul
if errorlevel 1 (
    echo [X] 当前 Python 缺少 tkinter，请用 python.org 官方安装包
    exit /b 1
)

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [X] 未安装 PyInstaller，请执行: pip install pyinstaller
    exit /b 1
)

python -c "import version; print(version.VERSION)" > "%TEMP%\pt_ver.txt" 2>nul
set /p VERSION=<"%TEMP%\pt_ver.txt"
del "%TEMP%\pt_ver.txt" 2>nul

REM ── 第一次：目录式（exe 不自解压到 %%TEMP%%，误报率最低）──
echo · PyInstaller --clean 打包 ^(目录式^) ...
set "PT_ONEDIR=1"
python -m PyInstaller --clean --noconfirm ProxyTool.spec
if errorlevel 1 (
    echo [X] 目录式打包失败
    exit /b 1
)

REM ── 第二次：单文件（便携分发）──
echo · PyInstaller --clean 打包 ^(单文件^) ...
set "PT_ONEDIR="
python -m PyInstaller --clean --noconfirm ProxyTool.spec
if errorlevel 1 (
    echo [X] 单文件打包失败
    exit /b 1
)

echo.
echo ══════════════════════════════════════════
echo  ✓ 打包完成  ^(v%VERSION%^)
echo   目录式: dist\ProxyTool\ProxyTool.exe
echo   单文件: dist\ProxyTool.exe
echo ══════════════════════════════════════════
echo  误报说明：exe 未做数字签名，Defender 可能报
echo            PUA:AndroidOS/Styricka!MTB 等 ML 误报
echo            （产物内不含任何 Android/DEX 代码）。
echo    1) 优先分发目录式 dist\ProxyTool\ —— 不自解压，误报率最低
echo    2) 根治办法是代码签名证书，见 README「杀软误报」一节
echo    3) 提交误报: https://www.microsoft.com/en-us/wdsi/filesubmission
echo ══════════════════════════════════════════

endlocal
