#!/bin/sh
# start | stop | status | open — run by herdr (startup hook / actions) or by hand from the plugin root.
# State (pid, db, seen marks) lives in HERDR_PLUGIN_STATE_DIR when herdr runs us, else ~/.config/whosup.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
. "$ROOT/scripts/node-path.sh"
STATE="${HERDR_PLUGIN_STATE_DIR:-$HOME/.config/whosup}"
CONF="${HERDR_PLUGIN_CONFIG_DIR:-$HOME/.config/whosup}"
mkdir -p "$STATE"
# user settings: KEY=value lines in $CONF/.env (PORT, OPEN_BROWSER, AGENT_CMD, FRONT_APP, STALE_DAYS, WHOSUP_READONLY)
if [ -f "$CONF/.env" ]; then
  set -a; . "$CONF/.env"; set +a
fi
PORT="${PORT:-4790}"
PID="$STATE/server.pid"
LOG="$STATE/server.log"
URL="http://127.0.0.1:$PORT"

alive() { [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; }
# 4790이 차 있으면 whosup은 다음 포트로 뜨고 $STATE/port에 적는다 — 그 포트를 먼저 본다.
healthy() {
  if [ -f "$STATE/port" ]; then p="$(cat "$STATE/port")"; curl -fsS -m 2 "http://127.0.0.1:$p/api/health" >/dev/null 2>&1 && { URL="http://127.0.0.1:$p"; return 0; }; fi
  curl -fsS -m 2 "$URL/api/health" >/dev/null 2>&1
}
# OPEN_BROWSER: 환경변수·.env > 자동 감지(원격이면 0, auto.json) > 1.
auto_open_browser() { [ -n "${OPEN_BROWSER:-}" ] || OPEN_BROWSER="$(node "$ROOT/scripts/autoconf.mjs" --read open_browser 2>/dev/null)"; }
open_browser() {
  [ "${1:-}" = "force" ] || auto_open_browser
  [ "${OPEN_BROWSER:-1}" = "1" ] || return 0
  # skip when a tab already talks to us (heartbeat written by the page in the last 15 s)
  hb="$STATE/board-heartbeat"
  if [ -f "$hb" ] && [ -n "$(find "$hb" -newermt '-15 seconds' 2>/dev/null)" ]; then return 0; fi
  # herdr가 켜질 때(start): 가려진 탭이라도 보드에 붙어 있으면 새 탭을 또 열지 않는다. 직접 고른 open(force)은 연다.
  cn="$STATE/board-connected"
  if [ "${1:-}" != "force" ] && [ -f "$cn" ] && [ -n "$(find "$cn" -newermt '-15 seconds' 2>/dev/null)" ]; then return 0; fi
  case "$(uname)" in
    Darwin) [ -n "${SSH_CONNECTION:-}" ] || /usr/bin/open "$URL" ;;
    *) [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] && command -v xdg-open >/dev/null 2>&1 && xdg-open "$URL" >/dev/null 2>&1 ;;
  esac
}

case "${1:-status}" in
  start)
    if healthy; then echo "whosup already listening at $URL"; open_browser; exit 0; fi
    # 기록된 whosup이 살아 있는데 답하지 않으면 새로 띄우지 않는다 — pid 파일을 덮어쓰면 그 프로세스가 고아가 된다.
    if alive; then echo "whosup pid $(cat "$PID") is running but not answering — run stop first, see $LOG"; exit 1; fi
    # preflight가 autoconf까지 돌려 auto.json을 새로 쓴다(서버는 시작할 때 그 파일을 읽는다).
    sh "$ROOT/scripts/preflight.sh" >/dev/null || exit 1
    cd "$ROOT" || exit 1
    WHOSUP_STATE_DIR="$STATE" PORT="$PORT" nohup node bin/whosup.mjs >>"$LOG" 2>&1 </dev/null &
    NEW=$!
    i=0; while [ $i -lt 40 ]; do healthy && break; kill -0 "$NEW" 2>/dev/null || break; sleep 0.25; i=$((i+1)); done
    if healthy; then
      # 같은 상태 폴더의 다른 whosup이 이미 답하고 있으면 방금 띄운 것은 스스로 끝난다 — 그때는 pid 파일을 건드리지 않는다.
      kill -0 "$NEW" 2>/dev/null && echo "$NEW" >"$PID"
      echo "whosup listening at $URL"; open_browser
    else
      # 실패로 끝낼 때는 방금 띄운 프로세스를 남기지 않는다.
      kill -TERM "$NEW" 2>/dev/null
      echo "whosup failed to start — see $LOG"; tail -5 "$LOG"; exit 1
    fi
    ;;
  stop)
    if ! alive; then echo "whosup not running"; exit 0; fi
    kill -TERM "$(cat "$PID")"; i=0; while [ $i -lt 20 ] && alive; do sleep 0.25; i=$((i+1)); done
    alive && { echo "still running pid=$(cat "$PID")"; exit 1; }
    rm -f "$PID"; echo "whosup stopped"
    ;;
  status)
    if healthy; then echo "whosup listening at $URL (pid $(cat "$PID" 2>/dev/null || echo ?))"; else echo "whosup not running"; exit 1; fi
    ;;
  open)
    healthy || { echo "whosup not running — start it first"; exit 1; }
    OPEN_BROWSER=1 open_browser force; echo "opened $URL"
    ;;
  *) echo "usage: plugin.sh start|stop|status|open"; exit 2 ;;
esac
