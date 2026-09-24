#!/bin/bash
# 构建镜像（本机没有 Docker 时，把仓库拷到服务器执行同一条命令即可）。
#
# 用法：bash scripts/docker-build.sh [TAG] [额外 docker build 参数...]
#
# 架构（重要）：
#   镜像架构 = 构建机架构。Apple Silicon 上构建出来的是 linux/arm64，推到 x86_64 服务器会
#   `exec format error`。按目标机器选一种做法：
#     1) 在目标机器上直接构建（推荐，最快，无模拟层）
#     2) 跨架构构建：PLATFORM=linux/amd64 bash scripts/docker-build.sh <tag>
#        —— 需要 docker buildx（BuildKit），首次要 `docker run --privileged --rm tonistiigi/binfmt --install amd64`
#           注册 QEMU；构建慢、且大包（torch）可能耗很久，仅适合临时用
#     3) 有网机器构建 → docker save | ssh 服务器 docker load（离线交付首选）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-laya-decision-api:latest}"
shift || true

PLATFORM="${PLATFORM:-}"          # 空 = 构建机原生架构
HOST_ARCH="$(uname -m)"
BUILD_CMD=(docker build)

if [ -n "$PLATFORM" ]; then
  if docker buildx version >/dev/null 2>&1; then
    # buildx 默认只把结果留在 build cache，要 --load 才进本地镜像列表
    BUILD_CMD=(docker buildx build --platform "$PLATFORM" --load)
    echo "跨架构构建：--platform ${PLATFORM}（构建机 ${HOST_ARCH}）"
    case "$HOST_ARCH/$PLATFORM" in
      arm64/linux/amd64|aarch64/linux/amd64|x86_64/linux/arm64|amd64/linux/arm64)
        echo "  提示：目标架构与构建机不同，走的是 QEMU 模拟，构建会明显变慢（torch 层可能十几分钟起）。"
        echo "  若构建失败并报 exec format error，先注册模拟器："
        echo "    docker run --privileged --rm tonistiigi/binfmt --install amd64,arm64";;
    esac
  else
    echo "警告：本机 docker 没有 buildx，--platform 不生效（会构建成 $HOST_ARCH 镜像）" >&2
    echo "      跨架构构建请装 buildx/新版 Docker，或改用「在目标机器上构建」" >&2
  fi
else
  case "$HOST_ARCH" in
    arm64|aarch64)
      echo "提示：未指定 PLATFORM，将构建 linux/arm64 镜像（构建机 ${HOST_ARCH}）。"
      echo "      目标是 x86_64 服务器的话，请改用：PLATFORM=linux/amd64 bash scripts/docker-build.sh ${TAG}";;
    x86_64|amd64)
      echo "构建 linux/amd64 镜像（构建机 ${HOST_ARCH}）";;
  esac
fi

# 可选透传：这些环境变量设了就随 --build-arg 传进去（不设则用 Dockerfile 默认值）
# 典型用法：LAY开头的服务参数（端口/鉴权/路径）在这里给默认，运行时还能用 -e 再覆盖
PASSTHROUGH=(APP_DIR MODELS_DIR LAYA_RUN_USER LAYA_RUN_UID LAYA_RUN_GID \
             LAYA_API_HOST LAYA_API_PORT LAYA_ENGINE LAYA_MODEL LAYA_BACKEND LAYA_MODEL_DIR \
             LAYA_WARM_ON_START LAYA_PREFIX_CACHE LAYA_MAX_QUEUE LAYA_DEFAULT_TIMEOUT_MS \
             LAYA_BUSY_RETRY_AFTER_S LAYA_MAX_STATE_CHARS LAYA_MAX_OPTIONS \
             LAYA_AUTH_MODE LAYA_API_KEYS LAYA_AUTH_HEADER LAYA_AUTH_PROTECT_STATUS \
             LAYA_AUTH_PUBLIC_PATHS LAYA_RATE_LIMIT_PER_MIN LAYA_RATE_LIMIT_BURST)
EXTRA_ARGS=()
for _n in "${PASSTHROUGH[@]}"; do
  _v="$(printenv "$_n" || true)"
  if [ -n "${_v}" ]; then
    EXTRA_ARGS+=(--build-arg "${_n}=${_v}")
    case "$_n" in
      LAYA_API_KEYS) echo "  传参 ${_n}=***（已隐藏）";;
      *)             echo "  传参 ${_n}=${_v}";;
    esac
  fi
done

echo "构建 $TAG"
# 想用“已装好 torch 的官方基础镜像”就加：
#   --build-arg BASE_IMAGE=pytorch/pytorch:<ver>-...-runtime --build-arg RUN_BASE_IMAGE=<同一个>
"${BUILD_CMD[@]}" \
  --build-arg PIP_INDEX_URL_BUILD="${PIP_INDEX_URL_BUILD:-https://pypi.tuna.tsinghua.edu.cn/simple}" \
  --build-arg TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cpu}" \
  --build-arg DEBIAN_MIRROR="${DEBIAN_MIRROR-https://mirrors.tuna.tsinghua.edu.cn}" \
  --build-arg PIP_FLAGS="${PIP_FLAGS:-}" \
  --build-arg BASE_IMAGE="${BASE_IMAGE:-python:3.12-slim-bookworm}" \
  --build-arg RUN_BASE_IMAGE="${RUN_BASE_IMAGE:-python:3.12-slim-bookworm}" \
  "${EXTRA_ARGS[@]}" \
  -t "$TAG" "$@" "$ROOT"

# 产物架构核对：这一步能直接拦住“在 Mac 上构建、往 x86 服务器推”的经典事故
ACTUAL="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$TAG" 2>/dev/null || echo 'unknown')"
echo
echo "镜像架构：$ACTUAL"
if [ -n "$PLATFORM" ] && [ "$ACTUAL" != "$PLATFORM" ]; then
  echo "警告：期望 ${PLATFORM}，实际 ${ACTUAL} —— 平台参数没生效（见上面 buildx 提示）" >&2
elif [ -z "${PLATFORM}" ] && [ "${ACTUAL##*/}" = "arm64" ]; then
  echo "注意：产物是 arm64 镜像，只能在 arm64 主机运行；x86_64 服务器请用 PLATFORM=linux/amd64 重建。" >&2
fi

echo
echo "冒烟（不挂权重会以 EX_CONFIG=78 退出，属预期）："
echo "  docker run --rm $TAG python -c \"import fastapi, uvicorn, laya; print('deps ok')\""
