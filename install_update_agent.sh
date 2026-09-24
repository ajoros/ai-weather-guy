#!/bin/sh
# Install a user LaunchAgent that runs update_local.sh every 30 minutes.
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
LABEL="com.ajoros.ai-weather-guy.update"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/.cache"
cat > "$DEST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${ROOT}/update_local.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${ROOT}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>GOOGLE_CLOUD_PROJECT</key>
    <string>weathernext3-joros</string>
  </dict>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${ROOT}/.cache/update-agent.log</string>
  <key>StandardErrorPath</key>
  <string>${ROOT}/.cache/update-agent.log</string>
</dict>
</plist>
EOF
UID_N="$(id -u)"
launchctl bootout "gui/${UID_N}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/${UID_N}" "$DEST"
echo "installed $DEST (every 30 min + now)" >&2
