@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║     剪映自动剪辑工具 v0.1.2 - EXE 打包脚本                ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

:: 步骤 1: 清理旧文件
echo [步骤 1/5] 清理旧的构建文件...
if exist build (
    echo   - 删除 build 目录...
    rmdir /s /q build
)
if exist dist (
    echo   - 删除 dist 目录...
    rmdir /s /q dist
)
if exist *.spec.bak (
    echo   - 删除备份文件...
    del /q *.spec.bak
)
echo   ✓ 清理完成
echo.

:: 步骤 2: 检查 Python
echo [步骤 2/5] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ Python 未安装或不在 PATH 中
    echo   请先安装 Python 3.11+
    pause
    exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do set PYTHON_VERSION=%%i
echo   ✓ %PYTHON_VERSION%
echo.

:: 步骤 3: 检查依赖
echo [步骤 3/5] 检查依赖包...
echo   - 检查 pyinstaller...
python -c "import pyinstaller" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ pyinstaller 未安装
    echo   正在安装 pyinstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo   ✗ 安装失败
        pause
        exit /b 1
    )
)
echo   ✓ pyinstaller 已安装

echo   - 检查 moviepy...
python -c "import moviepy" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ moviepy 未安装
    echo   请运行: pip install -r requirements.txt
    pause
    exit /b 1
)
echo   ✓ moviepy 已安装

echo   - 检查 tkinter...
python -c "import tkinter" >nul 2>&1
if %errorlevel% neq 0 (
    echo   ✗ tkinter 未安装
    pause
    exit /b 1
)
echo   ✓ tkinter 已安装
echo.

:: 步骤 4: 开始打包
echo [步骤 4/5] 开始打包 EXE（这可能需要几分钟）...
echo   配置文件: build-v0.1.2-console.spec
echo   输出文件: dist\JianyingAutoEditor_v0.1.2.exe
echo.
echo   正在打包，请稍候...
echo.

pyinstaller --clean --noconfirm build-v0.1.2-console.spec

if %errorlevel% neq 0 (
    echo.
    echo   ✗ 打包失败！
    echo   请检查上面的错误信息
    pause
    exit /b 1
)
echo.
echo   ✓ 打包完成
echo.

# 步骤 5: 验证结果
echo [步骤 5/6] 验证生成的文件...
if not exist "dist\JianyingAutoEditor_v0.1.2.exe" (
    echo   ✗ EXE 文件未找到
    pause
    exit /b 1
)

for %%A in ("dist\JianyingAutoEditor_v0.1.2.exe") do set FILE_SIZE=%%~zA
set /a FILE_SIZE_MB=!FILE_SIZE! / 1048576
echo   ✓ EXE 文件已生成
echo   文件路径: dist\JianyingAutoEditor_v0.1.2.exe
echo   文件大小: !FILE_SIZE_MB! MB
echo.

:: 步骤 6: 启动冒烟测试
echo [步骤 6/6] 启动冒烟测试（10 秒）...
start "" /b "dist\JianyingAutoEditor_v0.1.2.exe"
timeout /t 10 /nobreak >nul
tasklist | findstr /i "JianyingAutoEditor_v0.1.2.exe" >nul
if %errorlevel% neq 0 (
    echo   ✗ EXE 启动后提前退出，疑似仍有启动错误
    pause
    exit /b 1
)
taskkill /f /im JianyingAutoEditor_v0.1.2.exe >nul 2>&1
echo   ✓ 冒烟测试通过（可正常拉起）
echo.

:: 完成
echo ╔════════════════════════════════════════════════════════════╗
echo ║                    打包成功完成！                          ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo 生成的文件:
echo   dist\JianyingAutoEditor_v0.1.2.exe
echo.
echo 特性:
echo   ✓ 带控制台窗口，显示工作进度
echo   ✓ 支持完整视频模式（文案+配音+剪映草稿）
echo   ✓ 支持纯混剪模式（无文案无配音，直接MP4）
echo   ✓ 单文件 EXE，无需安装
echo   ✓ 批量生成 1-10 个视频
echo.
echo 下一步:
echo   1. 测试 EXE: 双击 dist\JianyingAutoEditor_v0.1.2.exe
echo   2. 检查控制台窗口是否显示
echo   3. 测试生成视频功能
echo.
pause
