# ============================================================
# 知映 zhiying — 安装包一键构建（支持两种模式）
#
# 用法:
#   powershell -File installer\build-installer.ps1                # 正式发布（最大压缩）
#   powershell -File installer\build-installer.ps1 -Fast          # 迭代自测（大件不压缩，快 5 倍）
#   powershell -File installer\build-installer.ps1 -SkipStage     # 只重打包（stage 未变时）
#   powershell -File installer\build-installer.ps1 -Version 1.3.0 # 指定版本（默认读 VERSION 文件）
#
# 模式对比（实测）:
#   正式: 编译 370s → 安装包 141MB → 用户安装 69s
#   快速: 编译  68s → 安装包 540MB → 用户安装 ~100s（仅供内部自测，不对外发布）
#
# 前置物料（首次构建需一次性准备，之后复用）:
#   installer\runtime\python-embed.zip   python.org 官方 embeddable 3.12
#   installer\runtime\pg-binaries.zip    EDB PostgreSQL 18 zip
#   installer\runtime\pgvector-087-src\  pgvector 源码（已 nmake 编译出 vector.dll）
#   installer\wheels\                    pip download 的离线 wheels
# ============================================================
param(
    [switch]$Fast,
    [switch]$SkipStage,
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = "D:\projectMenu\zhiying"
$ins = "$root\installer"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"

# ---------- 版本：单一来源 VERSION 文件 ----------
if (-not $Version) {
    $vf = "$root\VERSION"
    if (Test-Path $vf) { $Version = (Get-Content $vf -Raw).Trim() }
    else { throw "缺少 VERSION 文件，且未指定 -Version" }
}
# 校验语义化版本
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "版本号格式非法: $Version（应为 x.y.z）" }

Write-Host "=== 知映安装包构建 ==="
Write-Host "  版本    : $Version"
Write-Host "  模式    : $(if ($Fast) { '快速（大件不压缩，仅自测）' } else { '正式（最大压缩）' })"
Write-Host "  stage   : $(if ($SkipStage) { '跳过组装（复用现有）' } else { '重新组装' })"
Write-Host ""

# ---------- 1) 安装后脚本组 ----------
if (-not $SkipStage) {
    Write-Host ">>> [1/4] 生成安装后脚本组"
    powershell -NoProfile -ExecutionPolicy Bypass -File "$ins\gen-scripts.ps1"
    if ($LASTEXITCODE -ne 0) { throw "gen-scripts 失败" }

    Write-Host ">>> [2/4] 组装 stage"
    powershell -NoProfile -ExecutionPolicy Bypass -File "$ins\build-stage.ps1"
    if ($LASTEXITCODE -ne 0) { throw "build-stage 失败" }

    Write-Host ">>> [3/4] pgvector 装入 stage"
    $pgv = "$ins\runtime\pgvector-087-src"
    if (Test-Path "$pgv\vector.dll") {
        Copy-Item "$pgv\vector.dll" "$ins\stage\pg\lib\" -Force
        Get-ChildItem "$pgv\sql" -Filter "vector--*.sql" |
            Copy-Item -Destination "$ins\stage\pg\share\extension\" -Force
        Copy-Item "$pgv\vector.control" "$ins\stage\pg\share\extension\" -Force -ErrorAction SilentlyContinue
        Write-Host "    vector.dll + 迁移 SQL 已装入"
    } else {
        Write-Warning "    pgvector 未编译，知识库组件将缺扩展（先跑 build-pgvector.bat）"
    }
} else {
    Write-Host ">>> [1-3/4] 跳过 stage 组装（-SkipStage），仅同步后端源码"
    if (-not (Test-Path "$ins\stage\python\python.exe")) { throw "stage 不存在，不能使用 -SkipStage" }
    # 关键：即使用 -SkipStage，也必须把最新源码同步进 stage，否则打出旧代码
    $spDir = "$ins\stage\python\Lib\site-packages"
    robocopy "$root\src\zhiying" "$spDir\zhiying" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
    Get-ChildItem "$spDir\zhiying" -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "    源码已同步（src\zhiying → stage site-packages）"
}

# ---------- 4) ISCC 打包 ----------
Write-Host ">>> [4/4] ISCC 打包"
$outName = if ($Fast) { "zhiying-setup-dev" } else { "zhiying-setup" }
$isccArgs = @(
    "/DMyAppVersion=$Version",
    "/DOutputName=$outName",
    $(if ($Fast) { "/DFastBuild=1" } else { "" }),
    "$ins\setup.iss"
) | Where-Object { $_ -ne "" }

$sw = [Diagnostics.Stopwatch]::StartNew()
& $iscc @isccArgs 2>&1 | Select-Object -Last 4
$sw.Stop()
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败" }

$out = Get-ChildItem "$ins\Output" -Filter "$outName.exe" | Select-Object -First 1
Write-Host ""
Write-Host ("=== 完成: {0}（{1} MB，编译 {2} 秒）===" -f $out.Name, [int]($out.Length / 1MB), [int]$sw.Elapsed.TotalSeconds)
Write-Host "    路径: $($out.FullName)"
if ($Fast) { Write-Host "    ⚠ 这是自测包（体积大），不可对外发布" }
