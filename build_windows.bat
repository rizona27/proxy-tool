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

echo · PyInstaller --clean 打包 ...
if defined PT_ONEDIR (
    echo   分发形态：目录式 ^(dist\ProxyTool\^)  —— 误报率更低
) else (
    echo   分发形态：单文件 ^(dist\ProxyTool.exe^)
    echo   若被 Defender 拦截，试试: set PT_ONEDIR=1 ^&^& build_windows.bat
)
python -m PyInstaller --clean --noconfirm ProxyTool.spec
if errorlevel 1 (
    echo [X] 打包失败
    exit /b 1
)

echo.
echo ══════════════════════════════════════════
echo  ✓ 打包完成
if defined PT_ONEDIR (
    echo   产物: dist\ProxyTool\ProxyTool.exe  ^(v%VERSION%^)
) else (
    echo   产物: dist\ProxyTool.exe  ^(v%VERSION%^)
)
echo ══════════════════════════════════════════
echo  提示：本 exe 未做数字签名，Windows 可能提示
echo        「未知发布者」或被 Defender 启发式拦截。
echo        根治办法是加代码签名证书；临时办法是提交误报：
echo        https://www.microsoft.com/en-us/wdsi/filesubmission
echo ══════════════════════════════════════════

endlocal
