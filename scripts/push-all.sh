#!/bin/bash
# 双推：一次把当前分支与全部 tag 推到 GitHub(origin) 与 Gitee(gitee)。
#
# 为什么要有它：Gitee 那份是镜像仓库，手工记得推第二个远端很容易漏，
# 漏了就出现"两个仓库版本不一致"（用户看到的"导入有缺失"多半是这类）。
#
# 用法：
#   bash scripts/push-all.sh              # 推当前分支 + 全部 tag
#   bash scripts/push-all.sh main         # 指定分支
#   REMOTES="origin" bash scripts/push-all.sh    # 只推某一个远端
set -euo pipefail

BRANCH="${1:-$(git rev-parse --abbrev-ref HEAD)}"
REMOTES="${REMOTES:-origin gitee}"
PUSHED=0

for R in ${REMOTES}; do
  if ! git remote get-url "${R}" >/dev/null 2>&1; then
    echo "  跳过 ${R}：没有配置这个远端"
    continue
  fi
  echo "→ ${R}：推送分支 ${BRANCH} 与全部 tag"
  git push "${R}" "${BRANCH}"
  git push "${R}" --tags
  PUSHED=$((PUSHED + 1))
done

if [ "${PUSHED}" -eq 0 ]; then
  echo "没有可用的远端（检查 git remote -v）" >&2
  exit 1
fi
echo "完成：${BRANCH} + tag 已推到 ${PUSHED} 个远端"
