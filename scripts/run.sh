#!/bin/bash
# 起服务：必须单 worker（MLX 单设备；多 worker 每个进程各自加载 ~0.7GB）。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${LAYA_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"   # 可用 LAYA_PY 覆盖
HOST="${LAYA_API_HOST:-127.0.0.1}"
PORT="${LAYA_API_PORT:-8765}"
LOG_LEVEL="${LAYA_LOG_LEVEL:-info}"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export LAYA_MODEL="${LAYA_MODEL:-multilingual}"
export LAYA_WARM_ON_START="${LAYA_WARM_ON_START:-1}"

echo "laya-decision-api → http://$HOST:$PORT  (python=$PY model=$LAYA_MODEL)"
exec "$PY" -m uvicorn laya_api.server:app --host "$HOST" --port "$PORT" \
  --workers 1 --log-level "$LOG_LEVEL" --timeout-keep-alive 30
