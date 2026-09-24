#!/bin/bash
# 把源码同步到 home 下的运行副本，再（重新）加载常驻服务。
#
# 为什么要有这一步：macOS 的 launchd 用户代理没有"可移动卷"访问权限，
# 直接执行外置卷上的脚本会失败（Operation not permitted）。
# 所以：代码真源留在外置卷（本项目目录），运行时副本在 home。
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ROOT="${LAYA_RUN_ROOT:-$HOME/Library/Application Support/laya-decision-api}"

mkdir -p "$RUN_ROOT"
rsync -a --delete \
  --exclude 'logs/' --exclude '__pycache__/' --exclude '.git/' --exclude '.DS_Store' \
  "$ROOT/src" "$ROOT/scripts" "$ROOT/contract" "$ROOT/docs" "$ROOT/pyproject.toml" "$RUN_ROOT/"
chmod +x "$RUN_ROOT"/scripts/*.sh
echo "已同步运行副本到：$RUN_ROOT"
