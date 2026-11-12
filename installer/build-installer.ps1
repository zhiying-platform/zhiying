# ============================================================
# 知映 zhiying Windows 安装包一键构建总入口
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File installer\build-installer.ps1
# 步骤: 1) gen-scripts（安装后脚本组） 2) build-stage（组装 stage） 3) ISCC（压缩打包）
# 前置（首次）: installer\runtime\ 下需有 python-embed.zip 与 pg-binaries.zip（见 README）
#              wheels: .venv python -m pip download -d installer\wheels -r installer\req-binary.txt
#              加 jieba/setuptools/pywin32 sdist 补齐（见 git log）
# ============================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ins = "D:\projectMenu\zhiying\installer"

Write-Host ">>> [1/3] 生成安装后脚本组"
powershell -NoProfile -ExecutionPolicy Bypass -File "$ins\gen-scripts.ps1"
if ($LASTEXITCODE -ne 0) { throw "gen-scripts 失败" }

Write-Host ">>> [2/3] 组装 stage"
powershell -NoProfile -ExecutionPolicy Bypass -File "$ins\build-stage.ps1"
if ($LASTEXITCODE -ne 0) { throw "build-stage 失败" }

Write-Host ">>> [2b/3] pgvector 装入 stage（若已编译）"
if (Test-Path "$ins\runtime\pgvector-087-src\vector.dll") {
    Copy-Item "$ins\runtime\pgvector-087-src\vector.dll" "$ins\stage\pg\lib\" -Force
    Get-ChildItem "$ins\runtime\pgvector-087-src\sql" -Filter "vector--*.sql" |
        Copy-Item -Destination "$ins\stage\pg\share\extension\" -Force
    Copy-Item "$ins\runtime\pgvector-087-src\vector.control" "$ins\stage\pg\share\extension\" -Force -ErrorAction SilentlyContinue
    Write-Host "pgvector: vector.dll + 43 个迁移 SQL 已装入"
} else {
    Write-Warning "pgvector 未编译，知识库组件将缺扩展（先跑 build-pgvector.bat）"
}

Write-Host ">>> [3/3] ISCC 打包"
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" "$ins\setup.iss"
if ($LASTEXITCODE -ne 0) { throw "ISCC 失败" }

$out = Get-ChildItem "$ins\Output" -Filter "*.exe" | Select-Object -First 1
Write-Host ("=== 完成: {0} ({1} MB) ===" -f $out.Name, [int]($out.Length / 1MB))
