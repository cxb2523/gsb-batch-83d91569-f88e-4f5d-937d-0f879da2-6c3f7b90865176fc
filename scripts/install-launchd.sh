#!/bin/sh
# Install (or reinstall) the macOS LaunchAgent that runs the collector.
#
#   ./scripts/install-launchd.sh            install / reinstall
#   ./scripts/install-launchd.sh --uninstall remove it
#
# A LaunchAgent is not a resident process — it is a declaration that tells the
# already-running launchd "execute this at these times". The script runs for a
# few seconds and exits.
#
# The schedule is 00:30 / 12:00 / 21:00 plus RunAtLoad. RunAtLoad matters:
# `man 5 launchd.plist` promises that intervals missed while *asleep* are
# coalesced into one run on wake, but says nothing about intervals missed while
# the machine is *off* — and in practice those are simply skipped. RunAtLoad
# gives us a run at every login instead. It is safe to fire often because the
# collector is idempotent.
set -eu

HERE=$(cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname -- "$HERE")
LABEL=com.token-history.collect
LEGACY_LABEL=com.daily-tokens.collect     # pre-rename label; cleaned up on sight
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/token-history.log"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--uninstall" ]; then
    for l in "$LABEL" "$LEGACY_LABEL"; do
        launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
        rm -f "$HOME/Library/LaunchAgents/$l.plist"
    done
    echo "removed $LABEL"
    exit 0
fi

[ -f "$REPO/config.json" ] || {
    echo "config.json not found. Copy config.example.json to config.json and set your host alias." >&2
    exit 1
}

# launchd starts jobs with PATH=/usr/bin:/bin:/usr/sbin:/sbin, which contains
# neither node (needed for ccusage via npx) nor uv. Pass through the dirs that
# actually hold them on this machine rather than guessing.
EXTRA=""
for tool in npx uv git; do
    p=$(command -v "$tool" 2>/dev/null || true)
    [ -n "$p" ] && EXTRA="$EXTRA:$(dirname -- "$p")"
done
[ -x "$HOME/.local/bin/uv" ] && EXTRA="$EXTRA:$HOME/.local/bin"
# de-duplicate while preserving order
PATH_VALUE=$(printf '%s' "${EXTRA#:}:/usr/bin:/bin:/usr/sbin:/sbin" \
    | tr ':' '\n' | awk 'NF && !seen[$0]++' | paste -sd: -)

mkdir -p "$HOME/Library/LaunchAgents" "$(dirname -- "$LOG")"
cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$REPO/scripts/run.sh</string>
        <string>collect</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$PATH_VALUE</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>

    <key>StartCalendarInterval</key>
    <array>
        <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>30</integer></dict>
        <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
        <dict><key>Hour</key><integer>21</integer><key>Minute</key><integer>0</integer></dict>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>
</dict>
</plist>
PLIST_EOF

# There is no "reload"; bootout then bootstrap is the supported sequence.
# Also retire the pre-rename job so two collectors never run side by side.
launchctl bootout "$DOMAIN/$LEGACY_LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
launchctl enable "$DOMAIN/$LABEL"   # in case it was switched off in Login Items

echo "installed $LABEL"
echo "  plist : $PLIST"
echo "  log   : $LOG"
echo "  PATH  : $PATH_VALUE"
echo
echo "run now:  launchctl kickstart -k $DOMAIN/$LABEL"
echo "status :  launchctl print $DOMAIN/$LABEL"
echo "remove :  $0 --uninstall"
echo
echo "If it stops running for no reason, check System Settings > General >"
echo "Login Items & Extensions > Allow in the Background — the toggle disables"
echo "the job without removing the plist."
