#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
CONFIG_FILE="${TUSHARE_CONFIG_FILE:-$PROJECT_DIR/config.yaml}"
IMAGE="${RICEQUANT_DWD_IMAGE:-${RICEQUANT_IMAGE:-tushare-integration:ricequant-v1}}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
USE_SUDO="${USE_SUDO:-auto}"
LOCK_FILE="${RICEQUANT_DWD_LOCK_FILE:-/tmp/ricequant-dwd-sync.lock}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Missing DWD config file: $CONFIG_FILE" >&2
  exit 1
fi

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] Another RiceQuant DWD sync is active; exiting."
  exit 1
fi

DOCKER_PREFIX=()
if [[ "$USE_SUDO" == "1" ]]; then
  DOCKER_PREFIX=(sudo)
elif [[ "$USE_SUDO" == "auto" && "$EUID" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
  DOCKER_PREFIX=(sudo)
fi

docker_cmd() {
  "${DOCKER_PREFIX[@]}" "$DOCKER_BIN" "$@"
}

tables=(
  dwd_ricequant_stock_connect_holding_detail
  dwd_ricequant_fund_holding
)

for table in "${tables[@]}"; do
  container="ricequant-dwd-${table#dwd_ricequant_}"
  docker_cmd rm -f "$container" >/dev/null 2>&1 || true
  echo "[$(date '+%F %T')] Starting RiceQuant DWD sync table=$table image=$IMAGE"
  docker_cmd run --rm \
    --name "$container" \
    --net=host \
    -v "$CONFIG_FILE:/code/app/config.yaml:ro" \
    "$IMAGE" \
    python main.py dwd sync "$table"
  echo "[$(date '+%F %T')] RiceQuant DWD sync completed table=$table"
done
