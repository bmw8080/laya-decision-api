#!/bin/bash
# 起容器（挂权重目录 + 环境变量文件）。
# 用法：bash scripts/docker-run.sh [TAG]
#       PLATFORM=linux/arm64 bash scripts/docker-run.sh <tag>   # 镜像架构与宿主不同时显式指定
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-laya-decision-api:latest}"
MODELS="${LAYA_MODELS_HOST:-/opt/laya-models}"
NAME="${LAYA_CONTAINER_NAME:-laya-api}"
PORT="${LAYA_API_PORT:-8765}"
PLATFORM="${PLATFORM:-}"

[ -f "$ROOT/.env.docker" ] || { echo "缺 $ROOT/.env.docker（照 .env.docker.example 复制一份）" >&2; exit 1; }

IMG_ARCH="$(docker image inspect --format '{{.Architecture}}' "$TAG" 2>/dev/null || echo unknown)"
case "$(uname -m)/$IMG_ARCH" in
  arm64/amd64|x86_64/arm64|aarch64/amd64|amd64/arm64)
    echo "警告：镜像架构 $IMG_ARCH 与宿主 $(uname -m) 不同，需要模拟层（慢），或重建匹配镜像" >&2;;
esac

PLATFORM_ARGS=()
[ -n "$PLATFORM" ] && PLATFORM_ARGS=(--platform "$PLATFORM")

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  "${PLATFORM_ARGS[@]}" \
  --env-file "$ROOT/.env.docker" \
  -v "$MODELS:/models:ro" \
  -p "127.0.0.1:$PORT:$PORT" \
  "$TAG"

sleep 3
echo "容器内架构：$(docker exec "$NAME" uname -m 2>/dev/null || echo '（容器未起来）')  | 镜像架构：$IMG_ARCH"
docker logs --tail 20 "$NAME"
echo
echo "健康检查：curl -s http://127.0.0.1:$PORT/healthz"
