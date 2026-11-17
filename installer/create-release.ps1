# ============================================================
# GitHub Release 发布：创建 Release + 上传安装包
# 前置：
#   1) $env:GITHUB_TOKEN = fine-grained PAT（过期 <=366 天，本仓 Contents: Read and write）
#      注意：zhiying-platform 组织禁止过期 >366 天的 fine-grained PAT（403 会提示调整 lifetime）
#   2) tag 已推送：git push origin <tag>
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File installer\create-release.ps1
#   可选参数：-Tag v1.4.0 -Name "V1.4.0 xxx" -Body "更新说明" -Asset <exe 路径>
# ============================================================
param(
  [string]$Repo = "zhiying-platform/zhiying",
  [string]$Tag = "v1.3.0",
  [string]$Name = "",
  [string]$Body = "",
  [string]$Asset = ""
)
$ErrorActionPreference = "Stop"
if (-not $env:GITHUB_TOKEN) { throw "缺少 GITHUB_TOKEN 环境变量（fine-grained PAT，<=366 天）" }
$headers = @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json" }
if (-not $Asset) { $Asset = "$PSScriptRoot\Output\zhiying-setup.exe" }
if (-not (Test-Path $Asset)) { throw "安装包不存在: $Asset" }
if (-not $Name) { $Name = $Tag }

# 1) Release 是否已存在（按 tag 查）
$rel = $null
try { $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/tags/$Tag" -Headers $headers } catch {}
if ($rel) {
  Write-Host "Release $Tag 已存在: $($rel.html_url)"
} else {
  $payload = @{ tag_name = $Tag; name = $Name; body = $Body; draft = $false; prerelease = $false } | ConvertTo-Json
  $rel = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/$Repo/releases" -Headers $headers -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($payload))
  Write-Host "Release 已创建: $($rel.html_url)"
}

# 2) 上传资产（同名旧资产先删）
$assetName = Split-Path $Asset -Leaf
$old = $rel.assets | Where-Object { $_.name -eq $assetName }
if ($old) { Invoke-RestMethod -Method Delete -Uri $old.url -Headers $headers | Out-Null; Write-Host "已删除旧资产 $assetName" }
$uploadUrl = ($rel.upload_url -split '\{')[0]
$bytes = [IO.File]::ReadAllBytes($Asset)
Invoke-RestMethod -Method Post -Uri "$uploadUrl?name=$assetName" -Headers @{ Authorization = "Bearer $env:GITHUB_TOKEN"; Accept = "application/vnd.github+json"; "Content-Type" = "application/octet-stream" } -Body $bytes -TimeoutSec 1800 | Out-Null
Write-Host "资产已上传: $assetName ($([math]::Round($bytes.Length/1MB,1)) MB)"
Write-Host "完成: https://github.com/$Repo/releases/latest"
