#!/bin/sh
# 启动前检查权重目录；缺失就明确报错退出（EX_CONFIG=78），不要让它起一个空转的服务。
set -e

MODEL="${LAYA_MODEL:-multilingual}"
DIR="${LAYA_MODEL_DIR:-/models/$MODEL}"

echo "[entrypoint] engine=${LAYA_ENGINE:-laya_torch} model=${MODEL} dir=${DIR}"

if [ "${LAYA_ENGINE:-laya_torch}" = "laya_mlx" ]; then
  echo "[entrypoint] 警告：laya_mlx 需要 macOS + Metal，容器内不可用；请用 laya_torch"
fi

if [ ! -d "$DIR" ]; then
  cat <<EOF >&2
[entrypoint] 权重目录不存在：$DIR
  宿主机准备（ModelScope 国内直连，644MB）：
    mkdir -p /opt/laya-models && bash scripts/fetch-weights.sh /opt/laya-models
  启动时挂载：
    -v /opt/laya-models:/models:ro
  需要文件：model.safetensors / rl_agent_config.json / encoder/config.json / tokenizer/*
EOF
  exit 78
fi

for f in model.safetensors rl_agent_config.json encoder/config.json; do
  if [ ! -e "$DIR/$f" ]; then
    echo "[entrypoint] 权重不完整：缺少 ${DIR}/${f}（跑 scripts/fetch-weights.sh 续传补全）" >&2
    exit 78
  fi
done

echo "[entrypoint] 权重就绪，启动服务（单 worker）"
exec "$@"
