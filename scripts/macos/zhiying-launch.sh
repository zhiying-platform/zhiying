#!/bin/bash
# ============================================================
# 知映 zhiying — macOS 启动入口（.app/Contents/MacOS/zhiying）
# Finder 双击启动：环境准备 -> 托盘/后台服务 -> 就绪后开浏览器
# ============================================================
set -uo pipefail

CONTENTS="$(cd "$(dirname "$0")/.." && pwd)"
APP_HOME="$CONTENTS"
RUNTIME="$CONTENTS/runtime"

export ZHIYING_HOME="$APP_HOME"
export ZHIYING_DATA="$HOME/Library/Application Support/zhiying"
export ZHIYING_WEB_DIST="$CONTENTS/web"
export ZHIYING_API_PORT="${ZHIYING_API_PORT:-8600}"

mkdir -p "$ZHIYING_DATA"

# 日志（无终端时便于排查）
LOG="$ZHIYING_DATA/app.log"
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') 启动 ==="

# 单实例：服务已在跑则只打开页面
if /usr/bin/curl -sf -m 2 "http://127.0.0.1:$ZHIYING_API_PORT/api/health" >/dev/null 2>&1; then
    echo "服务已在运行，仅打开页面"
    /usr/bin/open "http://127.0.0.1:$ZHIYING_API_PORT"
    exit 0
fi

PY="$RUNTIME/bin/python3"
[ -x "$PY" ] || { echo "错误: 找不到运行时 $PY"; osascript -e 'display alert "知映安装不完整" message "运行时缺失，请重新安装"' 2>/dev/null; exit 1; }

# macOS 版为「精简模式」：不含嵌入式 PostgreSQL。
# 若用户自建 PG，可通过 $ZHIYING_DATA/macos-env 写 ZHIYING_DB_* 变量接入知识库。
if [ -f "$ZHIYING_DATA/macos-env" ]; then
    # shellcheck disable=SC1090
    . "$ZHIYING_DATA/macos-env"
fi

# 托盘常驻（pystray 需 pyobjc；缺失时 tray.py 自动退化为后台服务）
exec "$PY" -m zhiying.tray
