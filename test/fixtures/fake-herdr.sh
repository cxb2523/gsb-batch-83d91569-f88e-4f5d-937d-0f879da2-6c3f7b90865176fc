#!/bin/sh
# 가짜 herdr: 실행 중 세션 없음. 실제 herdr를 띄우지 않는 테스트용.
case "$*" in
  "--version") echo "herdr 0.0.0-fake" ;;
  "session list") echo "NAME STATUS DIRECTORY SOCKET" ;;
  *"pane read"*) echo "FAKE PANE SCREEN" ;;
  *) echo "fake herdr: $*" >&2; exit 1 ;;
esac
