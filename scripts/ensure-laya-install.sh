#!/bin/bash
# 幂等修复：Hermes venv 重建 / 升级 hermes-laya 之后跑一次。
# 做三件事：装插件 → 打本地权重补丁 → 验证加载耗时与一次真实决策。
set -euo pipefail
PY="${LAYA_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"   # 可用 LAYA_PY 覆盖
PATCH="${LAYA_PATCH_SCRIPT:-$HOME/.hermes/scripts/patch-laya-local-weights.sh}"

echo "== 1/3 安装 hermes-laya[mlx]（PyPI 直连索引）=="
"$PY" -m pip install --index-url https://pypi.org/simple "hermes-laya[mlx]" 2>&1 | tail -3

echo "== 2/3 本地权重补丁（避免每次加载联网校验 150s）=="
if [ -x "$PATCH" ]; then "$PATCH"; else
  echo "  ⚠ 未找到补丁脚本 $PATCH —— 手动确认 hermes_laya/backend.py 的 _CHECKPOINTS['multilingual']['mlx'] 指向 ~/.cache/laya-models/multilingual"; fi

echo "== 3/3 验证（加载 + 一次真实决策）=="
"$PY" - <<'PY'
import os, sys, time
sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent/venv/lib/python3.11/site-packages"))
from hermes_laya import backend
t0 = time.perf_counter()
agent, be, alias = backend.get_agent()
print(f"  加载 {round((time.perf_counter()-t0)*1000)} ms  backend={be} model={alias}")
res, ms, be, alias = backend.predict({"body": "账单重复扣款，请退款"}, {
    "department": {"type": "choice", "instructions": "Which team?",
                   "criteria": {"billing": "payments refunds", "technical": "bugs"}}})
print(f"  决策 {ms} ms -> {res['answers']['department']['choice']} "
      f"p={res['answers']['department']['probabilities']}")
PY
echo "OK"
