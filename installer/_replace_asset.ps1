# ============================================================
# Release 资产替换（curl 实现）：删旧 exe → 传新 exe → 字节核验
# token 来源：GH_TOKEN 环境变量（OpenClaw 注入，需 repo 权限 classic PAT）
# 用法: powershell -File installer\_replace_asset.ps1 -AssetPath <exe> [-Tag v1.4.0]
# ============================================================
param(
  [Parameter(Mandatory=$true)][string]$AssetPath,
  [string]$Repo = "zhiying-platform/zhiying",
  [string]$Tag = "v1.4.0"
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $AssetPath)) { throw "asset not found: $AssetPath" }
$t = "$env:GH_TOKEN".Trim()
if (-not $t) { throw "GH_TOKEN 环境变量为空" }
$h = "Authorization: Bearer $t"

# 1) 查 release
$relJson = & curl.exe -s -H $h "https://api.github.com/repos/$Repo/releases/tags/$Tag"
$rel = $relJson | ConvertFrom-Json
if (-not $rel.id) { throw "release $Tag 不存在（先网页创建 release 或用 API 建）" }
Write-Host ("release: id={0} tag={1} assets={2}" -f $rel.id, $rel.tag_name, $rel.assets.Count)

# 2) 删同名旧资产
$assetName = Split-Path $AssetPath -Leaf
$old = $rel.assets | Where-Object { $_.name -eq $assetName }
if ($old) {
  $delCode = & curl.exe -s -o NUL -w "%{http_code}" -X DELETE -H $h $old.url
  Write-Host ("old asset deleted: HTTP {0}" -f $delCode)
  if ($delCode -ne "204") { throw "删除旧资产失败 HTTP $delCode" }
}

# 3) 上传新资产（curl --data-binary 二进制安全）
$uploadUrl = ($rel.upload_url -split '\{')[0]
$upCode = & curl.exe -s -o "$env:TEMP\zy_up.json" -w "%{http_code}" -X POST -H $h -H "Content-Type: application/octet-stream" --data-binary "@$AssetPath" "$uploadUrl`?name=$assetName"
if ($upCode -ne "201") {
  $errBody = Get-Content "$env:TEMP\zy_up.json" -Raw -ErrorAction SilentlyContinue
  throw "上传失败 HTTP $upCode : $($errBody.Substring(0,[math]::Min(200,$errBody.Length)))"
}
$upl = Get-Content "$env:TEMP\zy_up.json" -Raw | ConvertFrom-Json
Write-Host ("uploaded: {0} ({1} MB)" -f $upl.name, [math]::Round($upl.size/1MB,1))
Remove-Item "$env:TEMP\zy_up.json" -Force -ErrorAction SilentlyContinue

# 4) 字节级核验（统一大小写比较）
$rel2 = (& curl.exe -s -H $h "https://api.github.com/repos/$Repo/releases/tags/$Tag") | ConvertFrom-Json
$a2 = $rel2.assets | Where-Object { $_.name -eq $assetName }
$localSize = (Get-Item $AssetPath).Length
Write-Host ("verify: remote={0} local={1}" -f $a2.size, $localSize)
if ($a2.size -eq $localSize) { Write-Host "ASSET_REPLACED_OK" -ForegroundColor Green }
else { throw "字节不一致 remote=$($a2.size) local=$localSize" }
