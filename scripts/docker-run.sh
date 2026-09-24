#!/bin/bash
# 起容器（挂权重目录 + 环境变量文件）。
# 用法：bash scripts/docker-run.sh [TAG]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-laya-decision-api:latest}"
MODELS="${LAYA_MODELS_HOST:-/opt/laya-models}"
NAME="${LAYA_CONTAINER_NAME:-laya-api}"
PORT="${LAYA_API_PORT:-8765}"

[ -f "$ROOT/.env.docker" ] || { echo "缺 $ROOT/.env.docker（照 .env.docker.example 复制一份）" >&2; exit 1; }

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  --env-file "$ROOT/.env.docker" \
  -v "$MODELS:/models:ro" \
  -p "127.0.0.1:$PORT:$PORT" \
  "$TAG"

sleep 3
docker logs --tail 20 "$NAME"
echo
echo "健康检查：curl -s http://127.0.0.1:$PORT/healthz"
