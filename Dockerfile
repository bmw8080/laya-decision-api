# ============================================================
# Laya 决策服务 —— 独立镜像
# 两级镜像 + 非 root + HEALTHCHECK + 入口自检 + 国内源
#
# 基础镜像、路径、端口、鉴权密钥等**全部可用 --build-arg 赋值**（见下方参数表），
# 运行期还可用 -e / --env-file 再覆盖（运行时 > 构建时 > Dockerfile 默认）。
#
# 架构（x86_64 / arm64）：
#   * 本文件不绑定架构：python:3.12-slim-bookworm 是 multi-arch manifest。
#   * 镜像架构 = 构建机架构。arm64 上构建出的是 linux/arm64，拷到 x86_64 会 `exec format error`；
#     跨架构请显式给平台（见 scripts/docker-build.sh 与 README「架构与跨机交付」）。
#
# 参数表（--build-arg，全部有默认值，按需覆盖）：
#   ── 构建行为 ────────────────────────────────────────────
#   BASE_IMAGE / RUN_BASE_IMAGE   基础镜像（默认 python:3.12-slim-bookworm）
#   PIP_INDEX_URL_BUILD           pip 源（默认清华）
#   TORCH_INDEX_URL               torch 索引（默认 PyTorch 官方 CPU 索引，勿用 PyPI：会拖 nvidia-* 包）
#   DEBIAN_MIRROR                 apt 源（脚本默认传清华；空=官方源）
#   PIP_FLAGS                     额外 pip 开关（跨架构构建传 --no-compile 提速）
#   LAYA_PIP_SPEC                 上游包名（默认 laya）
#   ── 路径 ──────────────────────────────────────────────
#   APP_DIR                       应用目录（默认 /app）
#   MODELS_DIR                    权重目录（默认 /models）
#   ── 运行身份 ──────────────────────────────────────────
#   LAYA_RUN_USER / _UID / _GID   运行用户（默认 app / 1001 / 1001）
#   ── 服务行为（同名环境变量在运行期可再覆盖）────────────
#   LAYA_API_HOST / LAYA_API_PORT            监听地址 / 端口（默认 0.0.0.0 / 8765）
#   LAYA_ENGINE / LAYA_MODEL / LAYA_BACKEND  引擎 / 模型 / 后端（默认 laya_torch / multilingual / auto）
#   LAYA_MODEL_DIR                           权重目录（默认 ${MODELS_DIR}/${LAYA_MODEL}）
#   LAYA_WARM_ON_START / LAYA_PREFIX_CACHE   启动预热 / 前缀缓存
#   LAYA_MAX_QUEUE / LAYA_DEFAULT_TIMEOUT_MS / LAYA_BUSY_RETRY_AFTER_S
#   LAYA_MAX_STATE_CHARS / LAYA_MAX_OPTIONS
#   LAYA_AUTH_MODE / LAYA_API_KEYS / LAYA_AUTH_HEADER / LAYA_AUTH_PROTECT_STATUS
#   LAYA_AUTH_PUBLIC_PATHS / LAYA_RATE_LIMIT_PER_MIN / LAYA_RATE_LIMIT_BURST
#
# ⚠️ 密钥警告：`--build-arg LAYA_API_KEYS=...` 会把密钥**固化进镜像层**（`docker history`/`docker inspect`
#    可见，且被推到镜像仓后无法收回）。推荐做法是构建时不传，运行时用 `-e LAYA_API_KEYS=...`
#    或 `--env-file .env.docker` 注入；确需烤进镜像时请确保该镜像只在内网私有仓。
# ============================================================

# ---------- 构建期参数（FROM 之前声明才能用于 FROM）----------
ARG BASE_IMAGE=python:3.12-slim-bookworm
ARG RUN_BASE_IMAGE=python:3.12-slim-bookworm

# ============================================================
# Stage 1: builder —— 依赖（torch 若基础镜像已有则自动跳过）
# ============================================================
FROM ${BASE_IMAGE} AS builder

ARG PIP_INDEX_URL_BUILD=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG LAYA_PIP_SPEC=laya
# 额外 pip 开关：跨架构（QEMU 模拟）构建时传 --no-compile 可显著提速（跳过字节码编译）
ARG PIP_FLAGS=""

WORKDIR /build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 运行期依赖单独一份：不能直接用 pyproject —— 它把 `hermes-laya[mlx]` 列为依赖，
# 那是 macOS/Metal 路径，Linux 装不了。这一层只依赖 requirements 文件，
# 改业务代码不会触发依赖重装（层缓存）。
COPY requirements-docker.txt ./
RUN pip install --prefix=/install --retries 10 --timeout 60 ${PIP_FLAGS} \
      -i ${PIP_INDEX_URL_BUILD} -r requirements-docker.txt

# torch：基础镜像已带就跳过；没有才装（CPU 版约 200MB；GPU 换 CUDA 索引）
RUN if python -c "import torch" 2>/dev/null; then \
      echo "基础镜像已带 torch：$(python -c 'import torch; print(torch.__version__)')，跳过安装"; \
    else \
      echo "基础镜像无 torch，从 ${TORCH_INDEX_URL} 安装"; \
      pip install --prefix=/install --retries 10 --timeout 60 ${PIP_FLAGS} torch --index-url ${TORCH_INDEX_URL}; \
    fi

# 上游 laya 的运行期依赖（来自 laya 的 Requires-Dist，除 torch 外；都不依赖 torch）
# 显式装是为了不让 pip 在装 laya 时"重新解析" torch 依赖 —— 那样它会从 PyPI 拖 CUDA 版 torch
# 和整套 nvidia-* 包（实测：几百 MB 下载 + 磁盘翻倍，且与上面装的 CPU 版冲突）
ARG LAYA_EXTRA_SPECS="transformers safetensors huggingface_hub numpy"
RUN pip install --prefix=/install --retries 10 --timeout 60 ${PIP_FLAGS} \
      -i ${PIP_INDEX_URL_BUILD} ${LAYA_EXTRA_SPECS}

# 上游 laya 本体（--no-deps：依赖已在上一步与 torch 步骤装好）
RUN pip install --prefix=/install --retries 10 --timeout 60 ${PIP_FLAGS} --no-deps \
      -i ${PIP_INDEX_URL_BUILD} ${LAYA_PIP_SPEC}

# 依赖完整性自检（漏装/多装了 CUDA 版 torch 都会在这里暴露）
RUN PYTHONPATH="$(ls -d /install/lib/python*/site-packages)" python -c "import torch, transformers, safetensors, huggingface_hub, numpy; \
      assert '+cpu' in torch.__version__ or 'cpu' in torch.__version__.lower(), 'torch 不是 CPU 版：' + torch.__version__; \
      print('deps ok · torch', torch.__version__, '· transformers', transformers.__version__)"

# ============================================================
# Stage 2: runner —— 最终运行镜像
# ============================================================
FROM ${RUN_BASE_IMAGE}

# ---------- 路径与服务参数（构建时赋值）----------
ARG APP_DIR=/app
ARG MODELS_DIR=/models
ARG LAYA_RUN_USER=app
ARG LAYA_RUN_UID=1001
ARG LAYA_RUN_GID=1001
ARG LAYA_API_HOST=0.0.0.0
ARG LAYA_API_PORT=8765
ARG LAYA_ENGINE=laya_torch
ARG LAYA_MODEL=multilingual
ARG LAYA_BACKEND=auto
ARG LAYA_MODEL_DIR=""
ARG LAYA_WARM_ON_START=1
ARG LAYA_PREFIX_CACHE=1
ARG LAYA_MAX_QUEUE=16
ARG LAYA_DEFAULT_TIMEOUT_MS=5000
ARG LAYA_BUSY_RETRY_AFTER_S=1
ARG LAYA_MAX_STATE_CHARS=4000
ARG LAYA_MAX_OPTIONS=20
ARG LAYA_AUTH_MODE=off
ARG LAYA_API_KEYS=""
ARG LAYA_AUTH_HEADER=X-API-Key
ARG LAYA_AUTH_PROTECT_STATUS=0
ARG LAYA_AUTH_PUBLIC_PATHS="/healthz,/readyz,/docs,/redoc,/wiki,/ui,/openapi.json,/static"
ARG LAYA_RATE_LIMIT_PER_MIN=0
ARG LAYA_RATE_LIMIT_BURST=0

# apt 源可换：默认用官方 debian 源；国内网络（或 deb.debian.org 被中间设备干扰时）用
#   --build-arg DEBIAN_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
ARG DEBIAN_MIRROR=""
RUN if [ -n "${DEBIAN_MIRROR}" ]; then \
      for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
        if [ -f "$f" ]; then \
          sed -i -E "s|https?://deb\.debian\.org/|${DEBIAN_MIRROR}/|g" "$f"; \
          sed -i -E "s|https?://security\.debian\.org/|${DEBIAN_MIRROR}/|g" "$f"; \
        fi; \
      done; \
      echo "apt 源已切到 ${DEBIAN_MIRROR}"; \
    fi \
 && apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

# 非 root 运行用户：uid/gid/用户名可用 --build-arg 改。
# 幂等 + 降级：某些官方基础镜像（如 pytorch/*）已占用 1001 或已有同名用户，
# 必须保证 `USER ${LAYA_RUN_USER}` 一定存在，否则容器起不来。
RUN if ! id -u "${LAYA_RUN_USER}" >/dev/null 2>&1; then \
      (groupadd --system --gid "${LAYA_RUN_GID}" "${LAYA_RUN_USER}" 2>/dev/null \
        || groupadd --system "${LAYA_RUN_USER}") && \
      (useradd --system --uid "${LAYA_RUN_UID}" --gid "${LAYA_RUN_USER}" \
               --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${LAYA_RUN_USER}" 2>/dev/null \
        || useradd --system --gid "${LAYA_RUN_USER}" --home-dir "${APP_DIR}" --shell /usr/sbin/nologin "${LAYA_RUN_USER}"); \
    fi && id -u "${LAYA_RUN_USER}"

# builder 里 pip 装的东西覆盖上去（基础镜像自带的 torch 不在 /install 里，会保留基础镜像那份）
COPY --from=builder /install /usr/local

# 应用代码（契约 + 服务）—— 排在依赖层之后，改代码不重装依赖
WORKDIR ${APP_DIR}
COPY --chown=${LAYA_RUN_USER}:${LAYA_RUN_USER} src      ${APP_DIR}/src
COPY --chown=${LAYA_RUN_USER}:${LAYA_RUN_USER} contract ${APP_DIR}/contract
# 内置接口文档（/wiki /docs /redoc）的内容源
COPY --chown=${LAYA_RUN_USER}:${LAYA_RUN_USER} docs     ${APP_DIR}/docs
COPY --chown=${LAYA_RUN_USER}:${LAYA_RUN_USER} docker-entrypoint.sh ${APP_DIR}/docker-entrypoint.sh
# 入口脚本放一个与 APP_DIR 无关的固定路径，ENTRYPOINT 才不会因改路径而失效
RUN sed -i 's/\r$//' "${APP_DIR}/docker-entrypoint.sh" \
 && chmod +x "${APP_DIR}/docker-entrypoint.sh" \
 && ln -sf "${APP_DIR}/docker-entrypoint.sh" /usr/local/bin/laya-entrypoint

# 构建期自检：依赖与后端真的能导入，才允许出镜像
RUN python -c "import platform, fastapi, uvicorn, pydantic, torch, laya; \
      print('build check ok · arch', platform.machine(), '· torch', torch.__version__, '· laya', getattr(laya, '__version__', '?'))"

# ── 权重：打进镜像（单文件交付，容器起来自带 ${MODELS_DIR}/<model>）──
# 准备方式（构建前放进构建上下文）：
#   bash scripts/fetch-weights.sh ./weights      # 或直接把已有的 multilingual 目录放进来
# 想瘦身/不带权重交付：让 weights/ 只留 .gitkeep（镜像里就没有权重），运行时改用挂载：
#   -v /opt/laya-models:${MODELS_DIR}:ro
# 注意：这里**不用 VOLUME 声明** —— 声明了会在运行时生成匿名卷遮蔽镜像内的权重，反而变成"看起来没权重"。
COPY weights/ ${MODELS_DIR}/

# ---------- 运行期环境变量（同名 -e / --env-file 可覆盖）----------
ENV PYTHONPATH=${APP_DIR}/src \
    PYTHONUNBUFFERED=1 \
    LAYA_API_HOST=${LAYA_API_HOST} \
    LAYA_API_PORT=${LAYA_API_PORT} \
    LAYA_ENGINE=${LAYA_ENGINE} \
    LAYA_MODEL=${LAYA_MODEL} \
    LAYA_BACKEND=${LAYA_BACKEND} \
    LAYA_MODEL_DIR=${LAYA_MODEL_DIR:-${MODELS_DIR}/${LAYA_MODEL}} \
    LAYA_WARM_ON_START=${LAYA_WARM_ON_START} \
    LAYA_PREFIX_CACHE=${LAYA_PREFIX_CACHE} \
    LAYA_MAX_QUEUE=${LAYA_MAX_QUEUE} \
    LAYA_DEFAULT_TIMEOUT_MS=${LAYA_DEFAULT_TIMEOUT_MS} \
    LAYA_BUSY_RETRY_AFTER_S=${LAYA_BUSY_RETRY_AFTER_S} \
    LAYA_MAX_STATE_CHARS=${LAYA_MAX_STATE_CHARS} \
    LAYA_MAX_OPTIONS=${LAYA_MAX_OPTIONS} \
    LAYA_AUTH_MODE=${LAYA_AUTH_MODE} \
    LAYA_API_KEYS=${LAYA_API_KEYS} \
    LAYA_AUTH_HEADER=${LAYA_AUTH_HEADER} \
    LAYA_AUTH_PROTECT_STATUS=${LAYA_AUTH_PROTECT_STATUS} \
    LAYA_AUTH_PUBLIC_PATHS=${LAYA_AUTH_PUBLIC_PATHS} \
    LAYA_RATE_LIMIT_PER_MIN=${LAYA_RATE_LIMIT_PER_MIN} \
    LAYA_RATE_LIMIT_BURST=${LAYA_RATE_LIMIT_BURST}

USER ${LAYA_RUN_USER}

EXPOSE ${LAYA_API_PORT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LAYA_API_PORT}/healthz" || exit 1

# 入口脚本会：检查权重 → 未给命令时按 LAYA_API_HOST/LAYA_API_PORT 起 uvicorn（单 worker）
ENTRYPOINT ["/usr/local/bin/laya-entrypoint"]
