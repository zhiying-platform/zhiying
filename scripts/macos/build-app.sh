#!/bin/bash
# ============================================================
# 知映 zhiying — macOS .app 组装（跨平台可验证，不依赖 macOS 专有命令）
#
# 用法:
#   ./build-app.sh <OUT_DIR> <REPO_ROOT> <PY_RUNTIME_DIR> <WEB_DIST_DIR>
#
# 参数:
#   OUT_DIR         输出目录（会创建 zhiying.app）
#   REPO_ROOT       后端仓库根（取 src/zhiying、scripts/macos）
#   PY_RUNTIME_DIR  解压好的 Python 运行时根（含 bin/python3、lib/python3.12）
#   WEB_DIST_DIR    前端 dist 目录
#
# 说明:
#   - 本脚本只做「文件树组装」，不含 hdiutil（打包 dmg 见 make-dmg.sh）
#   - 因此可在 Windows(Git Bash)/Linux 上跑回归，验证路径与结构
# ============================================================
set -euo pipefail

OUT_DIR="${1:?用法: build-app.sh <OUT_DIR> <REPO_ROOT> <PY_RUNTIME_DIR> <WEB_DIST_DIR>}"
REPO_ROOT="${2:?缺少 REPO_ROOT}"
PY_RUNTIME_DIR="${3:?缺少 PY_RUNTIME_DIR}"
WEB_DIST_DIR="${4:?缺少 WEB_DIST_DIR}"

VERSION="${ZHIYING_VERSION:-1.2.0}"

APP="$OUT_DIR/zhiying.app"
CONTENTS="$APP/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RES_DIR="$CONTENTS/Resources"
RT_DIR="$CONTENTS/runtime"
SP_DIR="$RT_DIR/lib/python3.12/site-packages"

log() { printf '  [build-app] %s\n' "$*"; }

# ---------- 0) 前置校验 ----------
[ -x "$PY_RUNTIME_DIR/bin/python3" ] || { echo "错误: 缺少 $PY_RUNTIME_DIR/bin/python3"; exit 1; }
[ -f "$WEB_DIST_DIR/index.html" ]    || { echo "错误: 缺少 $WEB_DIST_DIR/index.html"; exit 1; }
[ -f "$REPO_ROOT/src/zhiying/api.py" ] || { echo "错误: 缺少 src/zhiying/api.py"; exit 1; }

log "清理旧产物"
rm -rf "$APP"
mkdir -p "$MACOS_DIR" "$RES_DIR" "$SP_DIR"

# ---------- 1) Python 运行时 ----------
log "复制 Python 运行时"
cp -R "$PY_RUNTIME_DIR"/. "$RT_DIR"/

# ---------- 2) 后端源码（含 assets 图标） ----------
log "安装 zhiying 包"
mkdir -p "$SP_DIR/zhiying"
cp -R "$REPO_ROOT/src/zhiying"/. "$SP_DIR/zhiying"/
find "$SP_DIR/zhiying" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

# ---------- 3) 前端 ----------
log "复制前端 dist"
mkdir -p "$CONTENTS/web"
cp -R "$WEB_DIST_DIR"/. "$CONTENTS/web"/

# ---------- 4) 启动/停止脚本 ----------
log "生成启动脚本"
cp "$REPO_ROOT/scripts/macos/zhiying-launch.sh" "$MACOS_DIR/zhiying"
chmod +x "$MACOS_DIR/zhiying"
cp "$REPO_ROOT/scripts/macos/zhiying-stop.sh" "$RES_DIR/zhiying-stop.sh"
chmod +x "$RES_DIR/zhiying-stop.sh"

# ---------- 5) Info.plist ----------
log "生成 Info.plist ($VERSION)"
cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>zhiying</string>
    <key>CFBundleDisplayName</key><string>知映 zhiying</string>
    <key>CFBundleIdentifier</key><string>platform.zhiying.app</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleExecutable</key><string>zhiying</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>LSUIElement</key><false/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# ---------- 6) 图标（有 ico 则转 icns，无则跳过） ----------
if [ -f "$SP_DIR/zhiying/assets/zhiying.ico" ] && command -v sips >/dev/null 2>&1; then
    log "生成 AppIcon.icns"
    ICONSET="$OUT_DIR/AppIcon.iconset"
    rm -rf "$ICONSET"; mkdir -p "$ICONSET"
    for sz in 16 32 64 128 256 512; do
        sips -s format png -z $sz $sz "$SP_DIR/zhiying/assets/zhiying.ico" \
             --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null 2>&1 || true
        d=$((sz*2))
        sips -s format png -z $d $d "$SP_DIR/zhiying/assets/zhiying.ico" \
             --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null 2>&1 || true
    done
    iconutil -c icns "$ICONSET" -o "$RES_DIR/AppIcon.icns" 2>/dev/null || log "icns 生成跳过"
    rm -rf "$ICONSET"
else
    log "跳过图标（非 macOS 或无 ico）"
fi

# ---------- 7) 结构自检 ----------
log "结构自检"
fail=0
for p in \
    "$MACOS_DIR/zhiying" \
    "$CONTENTS/Info.plist" \
    "$CONTENTS/web/index.html" \
    "$RT_DIR/bin/python3" \
    "$SP_DIR/zhiying/api.py" \
    "$SP_DIR/zhiying/tray.py" \
    "$RES_DIR/zhiying-stop.sh"
do
    if [ -e "$p" ]; then :; else echo "  ✗ 缺失: $p"; fail=1; fi
done
[ "$fail" -eq 0 ] || { echo "结构自检失败"; exit 1; }

# 可执行位
[ -x "$MACOS_DIR/zhiying" ] || { echo "错误: 启动脚本无执行权限"; exit 1; }

# Info.plist 基本合法性
grep -q "CFBundleExecutable" "$CONTENTS/Info.plist" || { echo "错误: Info.plist 异常"; exit 1; }

log "完成: $APP"
log "总大小: $(du -sh "$APP" 2>/dev/null | cut -f1 || echo '未知')"
exit 0
