#!/usr/bin/env bash
# 一键启动:Web 服务(:8300)+ 可选的内网穿透(frp)。
#
# 用法:
#   ./start.sh              # 幂等:已在跑的组件自动跳过
#   ROOT=/path/to/repo ./start.sh
#
# 说明:
#   * 只负责起 HTTP 服务;转换用的引擎(venv/torch/模型)按 DEPLOY.md 装好即可;
#   * 若仓库同级有 frp/frpc.toml,会一并检查/拉起隧道,没有就跳过(不影响使用)。
set -uo pipefail

ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
PUBLIC_URL="${PUBLIC_URL:-}"

port_up() { ss -tln 2>/dev/null | grep -q ":$1 "; }
wait_http() {
  local url="$1" limit="$2" i
  for ((i = 0; i < limit / 3; i++)); do
    curl -s -m 3 -o /dev/null "$url" 2>/dev/null && return 0
    sleep 3
  done
  return 1
}

echo "========== 1/2 Web 服务(:8300) =========="
if port_up 8300; then
  echo "[paper2md] 已在运行,跳过"
else
  cd "$ROOT" || exit 1
  mkdir -p logs data
  setsid nohup ./run.sh > logs/server.log 2>&1 < /dev/null &
  echo "[paper2md] 启动中(等 /health)…"
  if wait_http "http://127.0.0.1:8300/health" 60; then
    echo "[paper2md] 就绪 ✓"
  else
    echo "[paper2md] 超时!查 $ROOT/logs/server.log" >&2
  fi
fi

echo "========== 2/2 内网穿透(frp,可选) =========="
if [ ! -d "$ROOT/../frp" ] && [ ! -d "$ROOT/frp" ]; then
  echo "[frp] 没有 frp 配置,跳过(本地/反代直接用 :8300)"
  frp_ok=0
fi
# 只匹配本项目配置的 frpc,别误伤同机上其他项目的 frpc
ours() {
  for pid in $(ps -eo pid,args | grep "[.]/frpc -c ./frpc.toml" | awk '{print $1}'); do
    cwd=$(readlink "/proc/$pid/cwd" 2>/dev/null)
    case "$cwd" in *OCR-LLM/frp*) echo "$pid";; esac
  done
}
if [ "${frp_ok:-1}" = 1 ] && [ -n "$(ours)" ]; then
  echo "[frp] 已在运行,跳过"
else
  cd "$ROOT/frp" || exit 1
  setsid nohup ./frpc -c ./frpc.toml > /tmp/frpc-ocr-translate.log 2>&1 < /dev/null &
  echo "[frp] 启动中…"
  ok=0
  for ((i = 0; i < 10; i++)); do
    sleep 3
    if grep -q "start proxy success" /tmp/frpc-ocr-translate.log 2>/dev/null; then ok=1; break; fi
  done
  if [ "$ok" = 1 ]; then
    echo "[frp] 隧道已连通 ✓"
  else
    echo "[frp] 未确认连通(服务端清理旧会话时会自动重试);查 /tmp/frpc-ocr-translate.log" >&2
  fi
fi

echo
echo "========== 状态汇总 =========="
port_up 8300 && echo "  PDF→MD 服务   :8300 ✓" || echo "  PDF→MD 服务   :8300 ✗"
[ "${frp_ok:-1}" = 1 ] && { [ -n "$(ours)" ] && echo "  frp 隧道           ✓" || echo "  frp 隧道           ✗"; }
echo
echo "本地访问: http://127.0.0.1:8300"
[ -n "$PUBLIC_URL" ] && echo "公网访问: $PUBLIC_URL"
