# ============================================================
# 知映 zhiying — 发布批次一键编排器（release.ps1）
#
# 串起安装包发布批次的全部固定步骤，
# 消除手工遗漏面：前端陈旧 dist、stage/web 新旧哈希混放、VERSION 五处联动、陈旧 pyc、
# ISCC 后台超时截断、ProductVersion 未核验。
#
# 用法:
#   powershell -File installer\release.ps1                          # 当前 VERSION，全量构建
#   powershell -File installer\release.ps1 -Version 1.3.3           # 升版 + 构建
#   powershell -File installer\release.ps1 -Fast                    # 快速自测包（-dev 后缀，不对外）
#   powershell -File installer\release.ps1 -SkipTag                 # 不打 git tag（默认打）
#   powershell -File installer\release.ps1 -NoBuildFrontend         # 前端 dist 未变时跳过 npm build
#
# 前置:
#   - 前端仓在 <repo>\..\zhiying-web（npm run build 可用）
#   - gen-scripts.ps1 / build-stage.ps1 / setup.iss 就位（本目录）
#   - ISCC 在 %LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe
#
# 步骤一览:
#   [1/8] 前端 npm run build（可 -NoBuildFrontend 跳过）
#   [2/8] 版本号五处联动校验/升版（VERSION/pyproject/setup.iss/__init__ 回退值）
#   [3/8] stage 组装：gen-scripts + build-stage + pgvector 装入 + 后端源码同步
#         （直接调组装脚本，不经 build-installer.ps1——它内嵌 ISCC，会在 web 同步前编译出旧前端包）
#   [4/8] stage/web 镜像同步（先清后拷，防新旧哈希资产混放）
#   [5/8] site-packages 陈旧 pyc 清理 + VERSION/回退值核验
#   [6/8] ISCC 编译（前台等待；只编译这一次，web 已就位）
#   [7/8] 产物核验：ProductVersion == 目标版本、体积合理性、时间戳、Output 清洁
#   [8/8] git 提交（仅版本有变时）+ tag（可 -SkipTag 跳过）
# ============================================================
param(
    [string]$Version = "",
    [switch]$Fast,
    [switch]$SkipTag,
    [switch]$NoBuildFrontend
)

$ErrorActionPreference = "Continue"   # PS5.1 陷阱：原生命令 stderr 经 2>&1 包装成 ErrorRecord，EAP=Stop 会误杀；所有原生命令调用点均有显式 $LASTEXITCODE 检查，关键不变量在步骤 [5/7] 复验
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$root = Split-Path $PSScriptRoot -Parent
$webRepo = Join-Path (Split-Path $root -Parent) "zhiying-web"
$iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
$swTotal = [Diagnostics.Stopwatch]::StartNew()

function Step($n, $msg) { Write-Host ""; Write-Host ">>> [$n] $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK $msg" -ForegroundColor Green }
function Info($msg) { Write-Host "    - $msg" }

# ---------- 版本来源 ----------
if (-not $Version) {
    $Version = (Get-Content "$root\VERSION" -Raw).Trim()
    if (-not $Version) { throw "VERSION 文件为空，且未指定 -Version" }
}
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "版本号格式非法: $Version" }
Write-Host "=== 知映发布批次编排 v$Version $(if ($Fast) {'（快速自测包）'} else {'（正式包）'}) ==="

# ---------- [1/8] 前端构建 ----------
Step "1/8" "前端 npm run build"
if ($NoBuildFrontend) {
    Info "跳过（-NoBuildFrontend），沿用现有 dist"
    if (-not (Test-Path "$webRepo\dist\index.html")) { throw "dist\index.html 不存在，不能跳过前端构建" }
} else {
    if (-not (Test-Path "$webRepo\package.json")) { throw "前端仓不存在: $webRepo" }
    Push-Location $webRepo
    try {
        npm run build 2>&1 | Where-Object { $_ -notmatch '^npm notice' } | Select-Object -Last 3
        if ($LASTEXITCODE -ne 0) { throw "npm run build 失败（退出码 $LASTEXITCODE）" }
        Ok "前端构建完成"
        $idx = Get-Item "$webRepo\dist\index.html" -ErrorAction SilentlyContinue
        if ($idx -and $idx.LastWriteTime -ge (Get-Date).AddMinutes(-10)) {
            Info "dist\index.html 时间戳已更新（$($idx.LastWriteTime.ToString('HH:mm:ss'))）"
        } else { Write-Warning "    dist\index.html 时间戳未更新（可能构建缓存），请人工确认" }
    } finally { Pop-Location }
}

# ---------- [2/8] 版本号五处联动 ----------
Step "2/8" "版本号联动（目标 $Version）"
$verChanges = @()

# VERSION 文件（ASCII 纯文本）
$cur = (Get-Content "$root\VERSION" -Raw).Trim()
if ($cur -ne $Version) { Set-Content "$root\VERSION" -Value $Version -NoNewline -Encoding ASCII; $verChanges += "VERSION"; Ok "VERSION → $Version" }
else { Info "VERSION 已是 $Version" }

# 其余三处（正则替换，replacement 用固定字符串避免 $ 序列歧义）
$verFiles = @(
    @{ Path = "$root\pyproject.toml";          Old = 'version = "[\d.]+"';          New = 'version = "<V>"' },
    @{ Path = "$root\installer\setup.iss";     Old = '#define MyAppVersion "[\d.]+"'; New = '#define MyAppVersion "<V>"' },
    @{ Path = "$root\src\zhiying\__init__.py"; Old = 'return "[\d.]+"';             New = 'return "<V>"' }
)
foreach ($vf in $verFiles) {
    $txt = Get-Content $vf.Path -Raw -Encoding UTF8
    $new = $txt -replace $vf.Old, ($vf.New -replace '<V>', $Version)
    if ($new -ne $txt) {
        Set-Content $vf.Path -Value $new -Encoding UTF8 -NoNewline
        $verChanges += (Split-Path $vf.Path -Leaf)
        Ok "$(Split-Path $vf.Path -Leaf) → $Version"
    } else {
        if ($txt -notmatch [regex]::Escape(($vf.New -replace '<V>', $Version))) {
            throw "$($vf.Path) 未找到版本占位模式（$($vf.Old)），人工检查"
        }
        Info "$(Split-Path $vf.Path -Leaf) 已是 $Version"
    }
}
$hasVerChange = ($verChanges.Count -gt 0)

# ---------- [3/8] stage 组装（不经 build-installer.ps1，避免其内嵌 ISCC 提前编译）----------
Step "3/8" "stage 组装：gen-scripts + build-stage + pgvector 装入 + 后端源码同步"
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\gen-scripts.ps1" 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { throw "gen-scripts 失败（退出码 $LASTEXITCODE）" }
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\build-stage.ps1" 2>&1 | Select-Object -Last 4
if ($LASTEXITCODE -ne 0) { throw "build-stage 失败（退出码 $LASTEXITCODE）" }
Ok "gen-scripts + build-stage 完成"

# pgvector 装入（与 build-installer.ps1 [3/4] 同逻辑）
$pgv = "$root\installer\runtime\pgvector-087-src"
if (Test-Path "$pgv\vector.dll") {
    Copy-Item "$pgv\vector.dll" "$root\installer\stage\pg\lib\" -Force
    Get-ChildItem "$pgv\sql" -Filter "vector--*.sql" |
        Copy-Item -Destination "$root\installer\stage\pg\share\extension\" -Force
    Copy-Item "$pgv\vector.control" "$root\installer\stage\pg\share\extension\" -Force -ErrorAction SilentlyContinue
    Ok "pgvector vector.dll + 迁移 SQL 已装入"
} else {
    Write-Warning "    pgvector 未编译（vector.dll 缺失），知识库组件将缺扩展"
}

# 后端源码同步（robocopy：退出码 0-7 均为成功，>=8 才是错误）
$spDir = "$root\installer\stage\python\Lib\site-packages"
robocopy "$root\src\zhiying" "$spDir\zhiying" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 源码同步失败（退出码 $LASTEXITCODE）" }
Ok "后端源码已同步（src\zhiying → stage site-packages）"

# ---------- [4/8] stage/web 镜像同步 ----------
Step "4/8" "stage/web 镜像同步（先清后拷，防新旧哈希资产混放）"
$stageWeb = "$root\installer\stage\web"
$dist = "$webRepo\dist"
if (-not (Test-Path "$dist\index.html")) { throw "前端 dist\index.html 不存在" }
if (Test-Path "$stageWeb.old") { Remove-Item "$stageWeb.old" -Recurse -Force }
if (Test-Path $stageWeb) { Rename-Item $stageWeb "web.old" -Force }
New-Item -ItemType Directory -Force -Path $stageWeb | Out-Null
Copy-Item "$dist\*" $stageWeb -Recurse -Force
if (Test-Path "$stageWeb.old") { Remove-Item "$stageWeb.old" -Recurse -Force }
$fCount = (Get-ChildItem $stageWeb -Recurse -File).Count
Ok "dist → stage/web 已镜像（$fCount 文件）"

# ---------- [5/8] pyc 清理 + VERSION 核验 ----------
Step "5/8" "site-packages pyc 清理 + VERSION/回退值核验"
Get-ChildItem $spDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Ok "site-packages __pycache__ 已全清"
Copy-Item "$root\VERSION" "$root\installer\stage\python\Lib\VERSION" -Force
$stageVer = (Get-Content "$root\installer\stage\python\Lib\VERSION" -Raw).Trim()
if ($stageVer -ne $Version) { throw "stage Lib\VERSION = $stageVer ≠ $Version" }
$initVer = (Select-String -Path "$spDir\zhiying\__init__.py" -Pattern 'return "([\d.]+)"').Matches[0].Groups[1].Value
if ($initVer -ne $Version) { throw "stage __init__ 回退值 = $initVer ≠ $Version" }
Ok "stage VERSION + __init__ 回退值 = $Version"

# ---------- [6/8] ISCC 编译（前台等待，只编这一次）----------
Step "6/8" "ISCC 编译（正式 LZMA 全量约 5-6 分钟）"
if (-not (Test-Path $iscc)) { throw "ISCC 不存在: $iscc" }
$outName = if ($Fast) { "zhiying-setup-dev" } else { "zhiying-setup" }
$oldExe = Get-Item "$root\installer\Output\$outName.exe" -ErrorAction SilentlyContinue
if ($oldExe) { Remove-Item $oldExe.FullName -Force; Info "已删旧产物（时间戳核验用）" }
$isccArgs = @("/DMyAppVersion=$Version", "/DOutputName=$outName")
if ($Fast) { $isccArgs += "/DFastBuild=1" }
$isccArgs += "$PSScriptRoot\setup.iss"
$sw = [Diagnostics.Stopwatch]::StartNew()
& $iscc @isccArgs 2>&1 | Select-Object -Last 4
$sw.Stop()
if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败（退出码 $LASTEXITCODE）" }
Ok "编译完成（$([int]$sw.Elapsed.TotalSeconds) 秒）"

# ---------- [7/8] 产物核验 ----------
Step "7/8" "产物核验"
$out = Get-Item "$root\installer\Output\$outName.exe" -ErrorAction SilentlyContinue
if (-not $out) { throw "产物不存在: $outName.exe" }
$pv = "$($out.VersionInfo.ProductVersion)".Trim()   # exe 资源字段带尾随填充空格，必须 Trim 后再比
if ($pv -ne $Version) { throw "ProductVersion = '$pv' ≠ $Version（打包注入失败）" }
Ok "ProductVersion = $pv"
$mb = [math]::Round($out.Length / 1MB, 1)
if (-not $Fast -and $mb -lt 100) { throw "正式包体积 $mb MB 异常偏小（后台超时截断事故特征）" }
Ok "体积 $mb MB"
if ($out.LastWriteTime -lt (Get-Date).AddMinutes(-15)) { throw "产物时间戳异常: $($out.LastWriteTime)" }
Ok "时间戳 $($out.LastWriteTime.ToString('HH:mm:ss'))"
Get-ChildItem "$root\installer\Output" -Filter "*-dev.exe" -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne "$outName.exe" } |
    ForEach-Object { Write-Warning "    Output 残留自测包: $($_.Name)（确认后手动删）" }

# ---------- [8/8] git 提交 + tag ----------
Step "8/8" "git 提交 + tag"
Push-Location $root
try {
    if ($hasVerChange) {
        git add VERSION pyproject.toml installer/setup.iss src/zhiying/__init__.py
        git commit -m "chore: 版本 →$Version（release.ps1 编排构建）" | Select-Object -First 2
        git push origin develop 2>&1 | Out-Null
        Ok "版本提交已推送"
    } else { Info "版本号无变化，跳过提交" }
    if (-not $SkipTag) {
        $tag = "v$Version"
        if (git tag -l $tag) { Info "tag $tag 已存在，跳过" }
        else {
            git tag -a $tag -m "V$Version 发布批次（release.ps1 编排构建）"
            git push origin $tag 2>&1 | Out-Null
            Ok "tag $tag 已推送"
        }
    } else { Info "跳过 tag（-SkipTag）" }
} finally { Pop-Location }

$swTotal.Stop()
Write-Host ""
Write-Host ("=== 发布批次构建完成: {0}（{1} MB，总耗时 {2} 分 {3} 秒）===" -f $out.Name, $mb, [int]$swTotal.Elapsed.TotalMinutes, $swTotal.Elapsed.Seconds) -ForegroundColor Green
Write-Host "    产物: $($out.FullName)"
if (-not $Fast) {
    Write-Host "    下一步（人工）: GitHub Releases → Draft new release → 选 tag v$Version → 填写说明 → 上传本 exe"
    Write-Host "    （也可用 GitHub API/CLI 上传资产，需具备 release 写权限的 token）"
}
