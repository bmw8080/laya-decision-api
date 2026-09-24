#!/bin/bash
# 安装常驻服务（launchd，用户级）。回滚：scripts/uninstall-service.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN_ROOT="${LAYA_RUN_ROOT:-$HOME/Library/Application Support/laya-decision-api}"
LABEL="com.user.laya-decision-api"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PY="${LAYA_PY:-$HOME/.hermes/hermes-agent/venv/bin/python}"   # 可用 LAYA_PY 覆盖
PORT="${LAYA_API_PORT:-8765}"

LOGDIR="$HOME/Library/Logs/laya-decision-api"
mkdir -p "$LOGDIR" "$HOME/Library/LaunchAgents"

# 1) 源码 → home 运行副本（launchd 无权读外置卷）
bash "$ROOT/scripts/deploy.sh"

cat > "$PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$RUN_ROOT/scripts/run.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key><string>$HOME</string>
        <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin</string>
        <key>LAYA_PY</key><string>$PY</string>
        <key>LAYA_API_PORT</key><string>$PORT</string>
        <key>LAYA_WARM_ON_START</key><string>1</string>
        <key>LAYA_ENGINE</key><string>${LAYA_ENGINE:-laya_mlx}</string>
    </dict>
    <key>WorkingDirectory</key><string>$RUN_ROOT</string>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>ThrottleInterval</key><integer>30</integer>
    <key>ExitTimeOut</key><integer>30</integer>
    <key>StandardOutPath</key><string>$LOGDIR/service.out.log</string>
    <key>StandardErrorPath</key><string>$LOGDIR/service.err.log</string>
</dict>
</plist>
PLISTEOF

plutil -lint "$PLIST"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
sleep 1
launchctl enable "gui/$(id -u)/$LABEL" 2>/dev/null || true
for attempt in 1 2 3; do
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>&1 && break
  echo "bootstrap 第 $attempt 次失败，重试（launchd 刚 bootout 后常报 EIO）"
  sleep 3
done
for i in $(seq 1 20); do
  curl -s --max-time 2 "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 1
done
launchctl print "gui/$(id -u)/$LABEL" | grep -E "^\\s+(state|pid) = " || true
echo "健康检查："; curl -s --max-time 10 "http://127.0.0.1:$PORT/healthz" || echo "(还没起来，看 $LOGDIR/service.err.log)"
echo "日志：$LOGDIR/service.{out,err}.log"
