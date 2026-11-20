#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
CONFIG_FILE="${RICEQUANT_CONFIG_FILE:-$PROJECT_DIR/ricequant.yaml}"
ENV_FILE="${RICEQUANT_ENV_FILE:-$PROJECT_DIR/ricequant.env}"
SCOPE="${RICEQUANT_REALTIME_SCOPE:-stock}"
case "$SCOPE" in
  stock) DEFAULT_COLLECTOR_NAME="ricequant-realtime" ;;
  csi2000) DEFAULT_COLLECTOR_NAME="ricequant-realtime-csi2000" ;;
  *) echo "RICEQUANT_REALTIME_SCOPE must be stock or csi2000" >&2; exit 2 ;;
esac
STATE_DIR="${RICEQUANT_REALTIME_STATE_DIR:-$PROJECT_DIR/data/$DEFAULT_COLLECTOR_NAME}"
LOG_DIR="${RICEQUANT_LOG_DIR:-$PROJECT_DIR/logs}"
IMAGE="${RICEQUANT_IMAGE:-tushare-integration:ricequant-v1}"
DOCKER_BIN="${DOCKER_BIN:-docker}"
USE_SUDO="${USE_SUDO:-auto}"
CONTAINER_NAME="${RICEQUANT_REALTIME_CONTAINER:-$DEFAULT_COLLECTOR_NAME}"
ACTION="${1:-start}"
if [[ "$#" -gt 0 ]]; then shift; fi
for collector_arg in "$@"; do
  if [[ "$collector_arg" == "--scope" || "$collector_arg" == --scope=* ]]; then
    echo "Set RICEQUANT_REALTIME_SCOPE instead of --scope so the container and outbox use the same scope" >&2
    exit 2
  fi
done

DOCKER_PREFIX=()
if [[ "$USE_SUDO" == "1" ]]; then
  DOCKER_PREFIX=(sudo)
elif [[ "$USE_SUDO" == "auto" && "$EUID" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
  DOCKER_PREFIX=(sudo)
fi
docker_cmd() { "${DOCKER_PREFIX[@]}" "$DOCKER_BIN" "$@"; }

case "$ACTION" in
  start)
    for required_file in "$CONFIG_FILE" "$ENV_FILE"; do
      if [[ ! -f "$required_file" ]]; then
        echo "Missing required file: $required_file" >&2
        exit 1
      fi
    done
    mkdir -p "$STATE_DIR" "$LOG_DIR"
    # Retain the same outbox across process/container/host restarts. An existing
    # named container is never force-removed by this command.
    docker_cmd run -d --name "$CONTAINER_NAME" --restart unless-stopped \
      --net=host --stop-timeout 60 \
      --log-opt max-size=20m --log-opt max-file=5 \
      --env-file "$ENV_FILE" -e TZ=Asia/Shanghai \
      -v "$CONFIG_FILE:/code/app/ricequant.yaml:ro" \
      -v "$STATE_DIR:/code/app/data/ricequant-realtime" \
      -v "$LOG_DIR:/code/app/logs" \
      "$IMAGE" python -m ricequant_integration.realtime \
      --config /code/app/ricequant.yaml --scope "$SCOPE" \
      --state-dir /code/app/data/ricequant-realtime "$@"
    ;;
  stop) docker_cmd stop "$CONTAINER_NAME" ;;
  status) docker_cmd inspect --format '{{.State.Status}}' "$CONTAINER_NAME" ;;
  logs) docker_cmd logs --tail 100 -f "$CONTAINER_NAME" ;;
  *) echo "Usage: $0 {start|stop|status|logs} [collector options]" >&2; exit 2 ;;
esac
