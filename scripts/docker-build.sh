#!/bin/bash
# 远程构建镜像（本机没有 Docker 时，把仓库拷到服务器执行同样这条命令即可）。
# 用法：bash scripts/docker-build.sh [TAG] [额外 docker build 参数...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-laya-decision-api:latest}"
shift || true

echo "构建 $TAG（远程/服务器上用同一命令）"
# 想用"已装好 torch 的官方基础镜像"就加：
#   --build-arg BASE_IMAGE=pytorch/pytorch:<ver>-... --build-arg RUN_BASE_IMAGE=<同一个>
docker build \
  --build-arg PIP_INDEX_URL_BUILD="${PIP_INDEX_URL_BUILD:-https://pypi.tuna.tsinghua.edu.cn/simple}" \
  --build-arg TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}" \
  --build-arg BASE_IMAGE="${BASE_IMAGE:-python:3.12-slim-bookworm}" \
  --build-arg RUN_BASE_IMAGE="${RUN_BASE_IMAGE:-python:3.12-slim-bookworm}" \
  -t "$TAG" "$@" "$ROOT"

docker images "$TAG"
echo
echo "冒烟（不挂权重会以 EX_CONFIG=78 退出，属预期）："
echo "  docker run --rm $TAG python -c \"import fastapi, uvicorn, laya; print('deps ok')\""
