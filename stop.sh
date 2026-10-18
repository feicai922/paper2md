#!/usr/bin/env bash
# 停止本服务:UI(:8300)+ frp 隧道 + 残留的 PaddleX 转换子进程。
# 可重复执行;没在运行的组件自动跳过。
#
# 用法:
#   ./stop.sh                     # 全停
#   ./stop.sh --keep-frontend     # 只停转换子进程,保留 UI 与 frp
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRP_DIR="${FRP_DIR:-$(cd "$HERE/../frp" && pwd)}"
KEEP_FRONTEND=0
[ "${1:-}" = "--keep-frontend" ] && KEEP_FRONTEND=1

kill_port() {
  local port="$1"
  for pid in $(ss -tlnp 2>/dev/null | grep -E ":$port[[:space:]]" | grep -oE "pid=[0-9]+" | cut -d= -f2 | sort -u); do
    echo "  终止端口 $port 上的进程 (pid $pid)"
    kill "$pid" 2>/dev/null
  done
}

if [ "$KEEP_FRONTEND" = 1 ]; then
  echo "========== UI / frp:保留 =========="
else
  echo "========== 停止 UI(:8300) =========="
  kill_port 8300

  echo "========== 停止 frp 内网穿透 =========="
  # 命令里通常是相对路径(./frpc -c ./frpc.toml),所以按 cwd 判断
  for pid in $(pgrep -f "[f]rpc .*frpc[.]toml" 2>/dev/null); do
    if [ "$(readlink "/proc/$pid/cwd" 2>/dev/null)" = "$FRP_DIR" ]; then
      echo "  终止 frpc (pid $pid)"
      kill "$pid" 2>/dev/null
    fi
  done
fi

echo "========== 清理转换子进程(占显存的 Paddle) =========="
# 只匹配本项目的转换脚本,避免误伤别人的 paddle 进程
pkill -TERM -f "pdf2m[d].py" 2>/dev/null
sleep 2

echo "========== 复查 =========="
sleep 2
if [ "$KEEP_FRONTEND" = 1 ]; then
  left=$(ss -tln 2>/dev/null | grep -E ":(8300)[[:space:]]")
else
  left=$(ss -tln 2>/dev/null | grep -E ":(8300)[[:space:]]")
fi
if [ -z "$left" ]; then
  echo "  端口: 已释放 ✓"
else
  echo "  端口仍占用:" >&2
  echo "$left" >&2
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "  当前各卡显存占用:"
  nvidia-smi --query-gpu=index,memory.used --format=csv,noheader 2>/dev/null | sed 's/^/    GPU /'
fi
echo "完成。"
