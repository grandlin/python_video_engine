# 剪映自动剪辑工具 v0.1.2 - PowerShell 打包脚本
# 编码: UTF-8

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║     剪映自动剪辑工具 v0.1.2 - EXE 打包脚本                ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# 步骤 1: 清理旧文件
Write-Host "[步骤 1/5] 清理旧的构建文件..." -ForegroundColor Yellow
if (Test-Path "build") {
    Write-Host "  - 删除 build 目录..." -ForegroundColor Gray
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Write-Host "  - 删除 dist 目录..." -ForegroundColor Gray
    Remove-Item -Recurse -Force "dist"
}
Write-Host "  ✓ 清理完成" -ForegroundColor Green
Write-Host ""

# 步骤 2: 检查 Python
Write-Host "[步骤 2/5] 检查 Python 环境..." -ForegroundColor Yellow
try {
    $pythonVersion = python --version 2>&1
    Write-Host "  ✓ $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Python 未安装或不在 PATH 中" -ForegroundColor Red
    Write-Host "  请先安装 Python 3.11+" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
Write-Host ""

# 步骤 3: 检查依赖
Write-Host "[步骤 3/5] 检查依赖包..." -ForegroundColor Yellow

Write-Host "  - 检查 pyinstaller..." -ForegroundColor Gray
try {
    python -c "import pyinstaller" 2>$null
    Write-Host "  ✓ pyinstaller 已安装" -ForegroundColor Green
} catch {
    Write-Host "  ✗ pyinstaller 未安装，正在安装..." -ForegroundColor Yellow
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ 安装失败" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
    Write-Host "  ✓ pyinstaller 安装完成" -ForegroundColor Green
}

Write-Host "  - 检查 moviepy..." -ForegroundColor Gray
try {
    python -c "import moviepy" 2>$null
    Write-Host "  ✓ moviepy 已安装" -ForegroundColor Green
} catch {
    Write-Host "  ✗ moviepy 未安装" -ForegroundColor Red
    Write-Host "  请运行: pip install -r requirements.txt" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

Write-Host "  - 检查 tkinter..." -ForegroundColor Gray
try {
    python -c "import tkinter" 2>$null
    Write-Host "  ✓ tkinter 已安装" -ForegroundColor Green
} catch {
    Write-Host "  ✗ tkinter 未安装" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
Write-Host ""

# 步骤 4: 开始打包
Write-Host "[步骤 4/5] 开始打包 EXE（这可能需要几分钟）..." -ForegroundColor Yellow
Write-Host "  配置文件: build-v0.1.2-console.spec" -ForegroundColor Gray
Write-Host "  输出文件: dist\JianyingAutoEditor_v0.1.2.exe" -ForegroundColor Gray
Write-Host ""
Write-Host "  正在打包，请稍候..." -ForegroundColor Cyan
Write-Host ""

pyinstaller --clean --noconfirm build-v0.1.2-console.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ✗ 打包失败！" -ForegroundColor Red
    Write-Host "  请检查上面的错误信息" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
Write-Host ""
Write-Host "  ✓ 打包完成" -ForegroundColor Green
Write-Host ""

# 步骤 5: 验证结果
Write-Host "[步骤 5/6] 验证生成的文件..." -ForegroundColor Yellow
if (-not (Test-Path "dist\JianyingAutoEditor_v0.1.2.exe")) {
    Write-Host "  ✗ EXE 文件未找到" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}

$fileInfo = Get-Item "dist\JianyingAutoEditor_v0.1.2.exe"
$fileSizeMB = [math]::Round($fileInfo.Length / 1MB, 2)
Write-Host "  ✓ EXE 文件已生成" -ForegroundColor Green
Write-Host "  文件路径: dist\JianyingAutoEditor_v0.1.2.exe" -ForegroundColor Gray
Write-Host "  文件大小: $fileSizeMB MB" -ForegroundColor Gray
Write-Host ""

# 步骤 6: 启动冒烟测试
Write-Host "[步骤 6/6] 启动冒烟测试（10 秒）..." -ForegroundColor Yellow
try {
    $p = Start-Process -FilePath "dist\JianyingAutoEditor_v0.1.2.exe" -PassThru
    Start-Sleep -Seconds 10
    if ($p.HasExited) {
        Write-Host "  ✗ EXE 启动后提前退出，疑似仍有启动错误" -ForegroundColor Red
        Read-Host "按回车键退出"
        exit 1
    }
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Write-Host "  ✓ 冒烟测试通过（可正常拉起）" -ForegroundColor Green
} catch {
    Write-Host "  ✗ 冒烟测试失败: $($_.Exception.Message)" -ForegroundColor Red
    Read-Host "按回车键退出"
    exit 1
}
Write-Host ""

# 完成
Write-Host "╔════════════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║                    打包成功完成！                          ║" -ForegroundColor Green
Write-Host "╚════════════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "生成的文件:" -ForegroundColor Cyan
Write-Host "  dist\JianyingAutoEditor_v0.1.2.exe" -ForegroundColor White
Write-Host ""
Write-Host "特性:" -ForegroundColor Cyan
Write-Host "  ✓ 带控制台窗口，显示工作进度" -ForegroundColor White
Write-Host "  ✓ 支持完整视频模式（文案+配音+剪映草稿）" -ForegroundColor White
Write-Host "  ✓ 支持纯混剪模式（无文案无配音，直接MP4）" -ForegroundColor White
Write-Host "  ✓ 单文件 EXE，无需安装" -ForegroundColor White
Write-Host "  ✓ 批量生成 1-10 个视频" -ForegroundColor White
Write-Host ""
Write-Host "下一步:" -ForegroundColor Cyan
Write-Host "  1. 测试 EXE: 双击 dist\JianyingAutoEditor_v0.1.2.exe" -ForegroundColor White
Write-Host "  2. 检查控制台窗口是否显示" -ForegroundColor White
Write-Host "  3. 测试生成视频功能" -ForegroundColor White
Write-Host ""
Read-Host "按回车键退出"
