#!/usr/bin/env bash
# Refresh the Mihomo subscription without replacing a working configuration.
# Run from the WebMirage repository root: ./mihomo/update_subscription.sh
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${MIHOMO_DATA_DIR:-$ROOT_DIR/mihomo/data}"
# Once backups are configured, keep the managed multi-source topology intact.
# This only prints a boolean; URLs stay out of command arguments and logs.
MULTI_SOURCE="$(python3 - "$ROOT_DIR/.env" <<'PY'
import os, sys
from pathlib import Path
values = {}
p = Path(sys.argv[1])
if p.exists():
    for line in p.read_text().splitlines():
        key, sep, value = line.strip().partition('=')
        if sep and not key.startswith('#'):
            values[key] = value.strip().strip('\"\'')
values.update(os.environ)
print(int(any(k.startswith('MIHOMO_BACKUP_SUBSCRIPTION_URL') and v for k, v in values.items())))
PY
)"
if [[ "$MULTI_SOURCE" == "1" ]]; then
  exec python3 "$ROOT_DIR/mihomo/configure_failover.py" --data-dir "$DATA_DIR" --apply
fi
# Docker Compose reads .env itself. Parse just this value here instead of sourcing
# the file: subscription URLs often contain '&' and other shell metacharacters.
if [[ -z "${MIHOMO_SUBSCRIPTION_URL:-}" && -f "$ROOT_DIR/.env" ]]; then
  MIHOMO_SUBSCRIPTION_URL="$(awk -F= '/^MIHOMO_SUBSCRIPTION_URL=/{sub(/^[^=]*=/, ""); value=$0} END{print value}' "$ROOT_DIR/.env")"
  MIHOMO_SUBSCRIPTION_URL="${MIHOMO_SUBSCRIPTION_URL#\"}"
  MIHOMO_SUBSCRIPTION_URL="${MIHOMO_SUBSCRIPTION_URL%\"}"
fi
SUBSCRIPTION_URL="${MIHOMO_SUBSCRIPTION_URL:?Set MIHOMO_SUBSCRIPTION_URL in .env or the environment}"
CONFIG="$DATA_DIR/config.yaml"; SECRET_FILE="$DATA_DIR/API_SECRET"; CANDIDATE="$DATA_DIR/config.candidate.yaml"; DOWNLOAD="$DATA_DIR/subscription.candidate.yaml"
BACKUP="$DATA_DIR/config.yaml.backup.$(date +%Y%m%d-%H%M%S)"
mkdir -p "$DATA_DIR"; [[ -f "$CONFIG" ]] || { echo "Missing current configuration: $CONFIG" >&2; exit 1; }; [[ -f "$SECRET_FILE" ]] || { echo "Missing controller secret: $SECRET_FILE" >&2; exit 1; }
trap 'rm -f "$CANDIDATE" "$DOWNLOAD"' EXIT
# curl is quiet because the subscription URL may contain a token.
curl --fail --silent --show-error --location --connect-timeout 10 --max-time 300 -A 'webmirage-mihomo-updater' "$SUBSCRIPTION_URL" -o "$DOWNLOAD"
python3 "$ROOT_DIR/mihomo/merge_subscription.py" --subscription "$DOWNLOAD" --output "$CANDIDATE" --secret-file "$SECRET_FILE"
if ! timeout 120 docker compose -f "$ROOT_DIR/docker-compose.yml" exec -T mihomo /mihomo -t -f /root/.config/mihomo/config.candidate.yaml; then echo "Candidate rejected by Mihomo; current configuration was left unchanged." >&2; exit 1; fi
cp -p "$CONFIG" "$BACKUP"; mv -f "$CANDIDATE" "$CONFIG"
if ! docker compose -f "$ROOT_DIR/docker-compose.yml" restart mihomo; then echo "Restart failed; rolling back previous configuration." >&2; cp -p "$BACKUP" "$CONFIG"; docker compose -f "$ROOT_DIR/docker-compose.yml" restart mihomo || true; exit 1; fi
echo "Mihomo subscription refreshed; previous config saved as $(basename "$BACKUP")."
