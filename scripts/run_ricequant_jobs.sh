#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
CONFIG_FILE="${RICEQUANT_CONFIG_FILE:-$PROJECT_DIR/ricequant.yaml}"
ENV_FILE="${RICEQUANT_ENV_FILE:-$PROJECT_DIR/ricequant.env}"
LOG_DIR="${RICEQUANT_LOG_DIR:-$PROJECT_DIR/logs}"
IMAGE="${RICEQUANT_IMAGE:-tushare-integration:ricequant-v1}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
USE_SUDO="${USE_SUDO:-auto}"
LOCK_FILE="${RICEQUANT_JOB_LOCK_FILE:-/tmp/ricequant-scheduled-job.lock}"
MODE="${1:-incremental}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

case "$MODE" in
  init-db|bootstrap|incremental|backfill|status|quota) ;;
  *)
    echo "Unsupported RiceQuant mode: $MODE" >&2
    exit 2
    ;;
esac

for required_file in "$CONFIG_FILE" "$ENV_FILE"; do
  if [[ ! -f "$required_file" ]]; then
    echo "Missing required file: $required_file" >&2
    exit 1
  fi
done

mkdir -p "$LOG_DIR"
RUN_LOG="$LOG_DIR/ricequant-${MODE}-$(date +%Y%m%d).log"
exec > >(tee -a "$RUN_LOG") 2>&1

if [[ "$MODE" != "quota" ]]; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "[$(date '+%F %T')] Another RiceQuant scheduled job is active; exiting."
    exit 1
  fi
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

CONTAINER_NAME="ricequant-${MODE}"
if [[ "$MODE" == "quota" ]]; then
  # Quota is read-only and may be inspected while an ingestion container is
  # active. A per-process name also permits simultaneous operator queries.
  CONTAINER_NAME="ricequant-quota-$$"
fi
cleanup() {
  docker_cmd rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup INT TERM

# A stale container can remain after a host or scheduler crash. The host lock
# above ensures this never removes a currently managed RiceQuant run.
cleanup
echo "[$(date '+%F %T')] Starting RiceQuant mode=$MODE image=$IMAGE log=$RUN_LOG"
docker_cmd run --rm \
  --name "$CONTAINER_NAME" \
  --net=host \
  --env-file "$ENV_FILE" \
  -v "$CONFIG_FILE:/code/app/ricequant.yaml:ro" \
  "$IMAGE" \
  python -m ricequant_integration --config /code/app/ricequant.yaml "$MODE" "$@"
echo "[$(date '+%F %T')] RiceQuant mode=$MODE finished"

