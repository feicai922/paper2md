#!/usr/bin/env bash
# 启动 Web 服务(只跑 UI + 编排,不装 torch/paddle;转换由引擎子进程完成)。
#
# 依赖:FastAPI + PyMuPDF(见 requirements.txt)。
#
# 解释器优先级:
#   1) 环境变量 OT_PYTHON
#   2) 本目录 .venv/bin/python
#   3) 系统 python3
# 缺依赖会自动 pip install -r requirements.txt。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${OT_PYTHON:-}" ]; then
  PY="$OT_PYTHON"
elif [ -x "$APP_DIR/.venv/bin/python" ]; then
  PY="$APP_DIR/.venv/bin/python"
else
  PY="$(command -v python3 || true)"
fi

if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "[paper2md] 找不到 python3(可建 .venv 或用 OT_PYTHON 指定)" >&2
  exit 1
fi
if ! "$PY" -c "import fitz, fastapi, uvicorn" 2>/dev/null; then
  echo "[paper2md] 缺少依赖,正在安装 requirements.txt…"
  "$PY" -m pip install -q -r "$APP_DIR/requirements.txt"
fi

cd "$APP_DIR"
echo "[paper2md] python = $PY"
echo "[paper2md] 监听   = ${OT_HOST:-0.0.0.0}:${OT_PORT:-8300}"
exec "$PY" -m uvicorn app.main:app \
  --host "${OT_HOST:-0.0.0.0}" \
  --port "${OT_PORT:-8300}" \
  --log-level info
