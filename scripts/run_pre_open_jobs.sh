#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
PRE_OPEN_JOBS_FILE="${PRE_OPEN_JOBS_FILE:-$PROJECT_DIR/pre_open_job.yaml}"
JOBS_FILE="${JOBS_FILE:-$PRE_OPEN_JOBS_FILE}"

# shellcheck source=lib/market_job_runner.sh
source "$SCRIPT_DIR/lib/market_job_runner.sh"
market_job_runner_init "pre-open-jobs"

main() {
  require_file "$JOBS_FILE"
  require_file "$CONFIG_FILE"

  echo "[$(date '+%F %T')] Pre-open jobs started. update_type=$UPDATE_TYPE Log: $RUN_LOG"
  run_job "tushare-pre-open-${UPDATE_TYPE}-adj-factor" "$IMAGE_BASIC" "pre/stock-adj-factor" "$UPDATE_TYPE"

  if [[ "$NORMAL_JOBS_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Skipping DWD sync because the pre-open crawl failed."
    return 0
  fi

  run_dwd_sync "tushare-pre-open-dwd-sync-stock-adj-factor" "$DWD_SYNC_IMAGE" "dwd_stock_adj_factor"
  if [[ "$DWD_SYNC_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Pre-open jobs completed; DWD sync completed with failures."
    return 0
  fi

  echo "[$(date '+%F %T')] Pre-open jobs and DWD adj_factor sync completed."
}

main "$@"
