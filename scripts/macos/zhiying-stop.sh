#!/bin/bash
# ============================================================
# 知映 zhiying — macOS 停止脚本（.app/Contents/Resources/zhiying-stop.sh）
# 停止后端服务（8600）与自建 PostgreSQL（若配置）
# ============================================================
set -uo pipefail

PORT="${ZHIYING_API_PORT:-8600}"

echo "停止知映服务（端口 $PORT）..."

# 结束占用端口的进程
PIDS="$(/usr/sbin/lsof -ti tcp:"$PORT" 2>/dev/null || true)"
if [ -n "$PIDS" ]; then
    # shellcheck disable=SC2086
    kill $PIDS 2>/dev/null || true
    sleep 2
    PIDS="$(/usr/sbin/lsof -ti tcp:"$PORT" 2>/dev/null || true)"
    if [ -n "$PIDS" ]; then
        # shellcheck disable=SC2086
        kill -9 $PIDS 2>/dev/null || true
    fi
    echo "[OK] 后端已停止"
else
    echo "[i] 后端未在运行"
fi

# 若是通过 macos-env 接入了自建 PostgreSQL，这里只提示不擅自杀
if [ -f "$HOME/Library/Application Support/zhiying/macos-env" ]; then
    echo "[i] 检测到 macos-env：自建数据库请自行管理（本脚本不终止外部 PG 实例）"
fi

echo "完成"
