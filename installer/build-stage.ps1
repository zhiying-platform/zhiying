# ============================================================
# zhiying Windows 离线安装包构建管线
# 布局: stage\python(embeddable, 含 Lib\site-packages 标准布局) + zhiying + web + pg
# 产出 stage 后由 ISCC 编译 setup.iss
# 实测修正: ._pth 最小化 / site-packages 进 python\Lib / zhiying-src.pth 三级向上
# ============================================================
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$root = Split-Path $PSScriptRoot -Parent
$ins = "$root\installer"
$stage = "$ins\stage"
$web = Join-Path (Split-Path $root -Parent) "zhiying-web"

Set-Location $root

Write-Host "=== 1) 清理旧 stage（保留 pg）==="
foreach ($d in @("python", "site-packages", "web")) {
    if (Test-Path "$stage\$d") { Remove-Item -Recurse -Force "$stage\$d" }
}

Write-Host "=== 2) Python embeddable 解压 ==="
New-Item -ItemType Directory -Force -Path "$stage\python" | Out-Null
tar -xf "$ins\runtime\python-embed.zip" -C "$stage\python"
if (-not (Test-Path "$stage\python\python.exe")) { throw "python.exe 未解出" }

# 版本号单一来源：VERSION 拷到 Lib\（__init__._read_version 读 parents[2]\VERSION，安装环境即 Lib\）
New-Item -ItemType Directory -Force -Path "$stage\python\Lib" | Out-Null   # embeddable zip 平铺无 Lib\，先建目录（fix: v1.4.0 构建首次重跑暴露）
Copy-Item "$root\VERSION" "$stage\python\Lib\VERSION" -Force

# ._pth 最小化（embeddable 隔离模式），路径交给 site/.pth 接管
$pthLines = @('python312.zip', '.', 'import site')
$pthContent = [string]::Join("`r`n", $pthLines) + "`r`n"
[IO.File]::WriteAllText("$stage\python\python312._pth", $pthContent, [System.Text.Encoding]::ASCII)
Write-Host "python embeddable: $([int]((Get-ChildItem $stage\python -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)) MB（._pth 最小化）"

Write-Host "=== 3) 核心依赖预装到 python\Lib\site-packages（标准布局，.pth 扫描才生效）==="
$spDir = "$stage\python\Lib\site-packages"
New-Item -ItemType Directory -Force -Path $spDir | Out-Null
$corePkgs = @(
    "yt-dlp>=2026.10.26", "PyYAML>=6.0", "requests>=2.31", "imageio-ffmpeg>=0.5",
    "scenedetect>=0.7.3", "psycopg[binary]>=3.3", "fastapi>=0.160",
    "uvicorn[standard]>=0.54", "mcp>=2.3", "opencv-python-headless>=4.8", "jieba>=0.42", "pywin32",
    "pystray>=0.19", "Pillow>=10"
)
# 注意：重复构建时 --target 已存在会告警「Target directory already exists」，
# 在 $ErrorActionPreference=Stop 下会被当作错误中止构建；用 --upgrade 幂等覆盖。
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& "$root\.venv\Scripts\python.exe" -m pip install -q --upgrade --no-index --find-links "$ins\wheels" --target "$spDir" @corePkgs 2>&1 | Select-Object -Last 2
$pipExit = $LASTEXITCODE
$ErrorActionPreference = $prevEap
if ($pipExit -ne 0) { throw "pip 安装依赖失败（exit=$pipExit）" }
if ($LASTEXITCODE -ne 0) { throw "pip --target 失败" }
Write-Host "site-packages: $([int]((Get-ChildItem $spDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)) MB"

Write-Host "=== 4) zhiying 源码包 → site-packages\zhiying（与依赖平级，免 .pth 相对路径坑）==="
robocopy "$root\src\zhiying" "$spDir\zhiying" /E /XD __pycache__ /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 失败 code=$LASTEXITCODE" }
Write-Host "zhiying 包: 已装入 site-packages"

Write-Host "=== 4b) 裁剪 PostgreSQL：移除 pgAdmin 4 / StackBuilder（GUI 工具，知映不用）==="
foreach ($junk in @("pgAdmin 4", "StackBuilder")) {
    $p = "$stage\pg\$junk"
    if (Test-Path $p) {
        $n = (Get-ChildItem $p -Recurse -File -ErrorAction SilentlyContinue).Count
        Remove-Item -Recurse -Force $p
        Write-Host "  已移除 $junk（$n 个文件）"
    }
}
# 清理无用的大体积文档
Get-ChildItem "$stage\pg" -Recurse -File -Include "*.pdb","LICENSES.chromium.html" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
$pgFiles = (Get-ChildItem "$stage\pg" -Recurse -File -ErrorAction SilentlyContinue)
Write-Host "  PG 剩 $($pgFiles.Count) 个文件 / $([int](($pgFiles | Measure-Object Length -Sum).Sum / 1MB)) MB"

Write-Host "=== 4c) 清理 stage 中的 __pycache__ / .pyc（运行时自动重建，减文件数）==="
$pyc = Get-ChildItem $stage -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue
$pycCount = ($pyc | ForEach-Object { (Get-ChildItem $_.FullName -File -ErrorAction SilentlyContinue).Count } | Measure-Object -Sum).Sum
$pyc | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "  已移除 $($pyc.Count) 个 __pycache__ 目录（约 $pycCount 个 .pyc）"

Write-Host "=== 5) 前端 dist ==="
if (-not (Test-Path "$web\dist\index.html")) { throw "前端 dist 缺失，先 npm run build" }
# 必须用 /MIR 镜像：Copy-Item 是合并复制，会积累旧 hash 文件名的 chunk，
# 导致安装包里新旧两套 JS 并存、页面加载到旧版（实测：设置页字段名修复进不了包）
robocopy "$web\dist" "$stage\web" /MIR /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "前端 dist 镜像失败 code=$LASTEXITCODE" }
Write-Host "web: $([int]((Get-ChildItem $stage\web -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)) MB"

Write-Host "=== 6) 环境自检（导入探针，含 zhiying 自身）==="
# 探针：jieba 等第三方包打 SyntaxWarning 到 stderr，Stop 模式会当错误中断 -> 抑制警告 + 临时 Continue
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$probe = & "$stage\python\python.exe" -W ignore -c "import fastapi, uvicorn, yt_dlp, cv2, psycopg, jieba, yaml, requests, mcp, pystray, PIL, zhiying.tray; print('imports-ok')" 2>&1
$ErrorActionPreference = $prevEap
Write-Host "导入探针: $probe"
if ("$probe" -notmatch "imports-ok") { throw "核心依赖导入失败" }

$total = (Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
Write-Host ("=== stage 合计: {0} MB，进入 ISCC 编译 ===" -f [int]$total)
