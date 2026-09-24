#!/bin/bash
# 卸载常驻服务并回收端口。
set -euo pipefail
LABEL="com.user.laya-decision-api"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl disable "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
rm -rf "${LAYA_RUN_ROOT:-$HOME/Library/Application Support/laya-decision-api}"
echo "已卸载 ${LABEL}（plist 已删）。权重与代码保留：~/.cache/laya-models、本项目目录。"
