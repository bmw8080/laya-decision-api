#!/bin/bash
# 下载 laya multilingual 权重（643.8MB）到目标目录。ModelScope 国内直连（实测 1.1MB/s）。
# 用法：bash scripts/fetch-weights.sh [目标目录，默认 ./models]
set -euo pipefail
DEST="${1:-$(cd "$(dirname "$0")/.." && pwd)/models}"
# 归一成绝对路径：脚本随后会 cd 进 $DEST/$MODEL，末尾的 ls 若用相对路径（如传入 ./weights）必然失败
DEST="$(mkdir -p "$DEST" && cd "$DEST" && pwd)"
MODEL="${LAYA_MODEL:-multilingual}"
BASE="https://www.modelscope.cn/api/v1/models/convaiinnovations/laya/repo?Revision=master&FilePath=${MODEL}%2F"

mkdir -p "$DEST/$MODEL"
cd "$DEST/$MODEL"

for f in model.safetensors rl_agent_config.json encoder/config.json tokenizer/tokenizer.json tokenizer/tokenizer_config.json; do
  mkdir -p "$(dirname "$f")"
  if [ -s "$f" ]; then echo "跳过已存在：$f"; continue; fi
  echo "下载 $f ..."
  curl -fL --retry 5 --retry-delay 3 -C - --noproxy '*' -o "$f" "${BASE}${f//\//%2F}"
done

echo "完成：$DEST/$MODEL"
ls -la "$DEST/$MODEL"
