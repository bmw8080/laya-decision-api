# ============================================================
# Laya 决策服务 —— 独立镜像
# 两级镜像 + 非 root + HEALTHCHECK + 入口自检 + 国内源
#
# 基础镜像可用 --build-arg 换（推荐用“已经装好 torch 的官方镜像”，构建就不再下 torch）：
#   默认（薄）        ：python:3.12-slim-bookworm
#   预装 torch（推荐）  ：pytorch/pytorch:<ver>-...-runtime（无 GPU 用其 CPU 变体）
#   离线              ：有网机器构建一次 → docker save → 服务器 docker load
#
# 架构（x86_64 / arm64）：
#   * 本文件**不绑定架构**：python:3.12-slim-bookworm 是 multi-arch manifest，
#     x86_64 与 arm64 都能构建；容器内走 torch 后端（CPU），上游 `laya` 是 py3-none-any 纯 Python，
#     torch / tokenizers / numpy / safetensors 在 x86_64 与 aarch64 都有 manylinux wheel（已核）。
#   * 但镜像架构 = **构建机架构**：Apple Silicon 上 docker build 出来的是 linux/arm64，
#     推到 x86_64 服务器会 `exec format error`。跨架构请显式给平台（见 scripts/docker-build.sh）：
#       PLATFORM=linux/amd64 bash scripts/docker-build.sh <tag>     # 在 arm64 机上为 x86 构建（QEMU，慢）
#     或在目标架构的机器上直接构建（推荐，最快且无模拟层）。
# ============================================================

ARG BASE_IMAGE=python:3.12-slim-bookworm
ARG RUN_BASE_IMAGE=python:3.12-slim-bookworm

# ============================================================
# Stage 1: builder —— 依赖（torch 若基础镜像已有则自动跳过）
# ============================================================
FROM ${BASE_IMAGE} AS builder

WORKDIR /app

ARG PIP_INDEX_URL_BUILD=https://pypi.tuna.tsinghua.edu.cn/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG LAYA_PIP_SPEC=laya

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 运行期依赖单独一份：不能直接用 pyproject —— 它把 `hermes-laya[mlx]` 列为依赖，
# 那是 macOS/Metal 路径，Linux 装不了。这一层只依赖 requirements 文件，
# 改业务代码不会触发依赖重装（层缓存）。
COPY requirements-docker.txt ./
RUN pip install --prefix=/install -i ${PIP_INDEX_URL_BUILD} -r requirements-docker.txt

# torch：基础镜像已带就跳过；没有才装（CPU 版约 200MB，GPU 换 CUDA 索引）
RUN if python -c "import torch" 2>/dev/null; then \
      echo "基础镜像已带 torch：$(python -c 'import torch; print(torch.__version__)')，跳过安装"; \
    else \
      echo "基础镜像无 torch，从 ${TORCH_INDEX_URL} 安装"; \
      pip install --prefix=/install torch --index-url ${TORCH_INDEX_URL}; \
    fi

# 上游 laya（PyTorch 后端，模块名 `laya`）
RUN pip install --prefix=/install -i ${PIP_INDEX_URL_BUILD} ${LAYA_PIP_SPEC}

# ============================================================
# Stage 2: runner —— 最终运行镜像
# ============================================================
FROM ${RUN_BASE_IMAGE}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# 非 root（uid/gid 1001，与 public-affairs-platform 同款）。
# 幂等 + 降级：某些官方基础镜像（如 pytorch/*）已占用 1001 或已有同名用户，
# 必须保证 `USER app` 一定存在，否则容器起不来。
RUN if ! id -u app >/dev/null 2>&1; then \
      (groupadd --system --gid 1001 app 2>/dev/null || groupadd --system app) && \
      (useradd --system --uid 1001 --gid app --home-dir /app --shell /usr/sbin/nologin app 2>/dev/null \
        || useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app); \
    fi && id -u app

# builder 里 pip 装的东西覆盖上去（基础镜像自带的 torch 不在 /install 里，会保留基础镜像那份）
COPY --from=builder /install /usr/local

# 应用代码（契约 + 服务）—— 排在依赖层之后，改代码不重装依赖
COPY --chown=app:app src      /app/src
COPY --chown=app:app contract /app/contract
# 内置接口文档（/wiki）的内容源
COPY --chown=app:app docs     /app/docs
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
RUN sed -i 's/\r$//' /app/docker-entrypoint.sh && chmod +x /app/docker-entrypoint.sh

# 构建期自检：依赖与后端真的能导入，才允许出镜像
RUN python -c "import platform, fastapi, uvicorn, pydantic, torch, laya; \
      print('build check ok · arch', platform.machine(), '· torch', torch.__version__, '· laya', getattr(laya, '__version__', '?'))"

# ── 权重：不进镜像，运行时挂载（要单文件交付就把权重 COPY 进来，镜像 +644MB）──
VOLUME ["/models"]

USER app

EXPOSE 8765

ENV PYTHONPATH=/app/src \
    LAYA_ENGINE=laya_torch \
    LAYA_MODEL=multilingual \
    LAYA_MODEL_DIR=/models/multilingual \
    LAYA_API_HOST=0.0.0.0 \
    LAYA_API_PORT=8765 \
    LAYA_WARM_ON_START=1 \
    LAYA_MAX_QUEUE=16 \
    PYTHONUNBUFFERED=1

HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${LAYA_API_PORT}/healthz" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
# 必须单 worker：模型单例常驻，多 worker 各自加载一份
CMD ["python", "-m", "uvicorn", "laya_api.server:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1"]
