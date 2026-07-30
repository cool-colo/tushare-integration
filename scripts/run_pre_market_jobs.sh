#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
PRE_JOBS_FILE="${PRE_JOBS_FILE:-$PROJECT_DIR/pre_job.yaml}"
JOBS_FILE="${JOBS_FILE:-$PRE_JOBS_FILE}"

# shellcheck source=lib/market_job_runner.sh
source "$SCRIPT_DIR/lib/market_job_runner.sh"
market_job_runner_init "pre-market-jobs"

main() {
  require_file "$JOBS_FILE"
  require_file "$CONFIG_FILE"

  echo "[$(date '+%F %T')] Pre-market jobs started. update_type=$UPDATE_TYPE Log: $RUN_LOG"
  run_job "tushare-pre-${UPDATE_TYPE}-stock-eod-price" "$IMAGE_BASIC" "pre/stock-eod-price" "$UPDATE_TYPE"

  if [[ "$NORMAL_JOBS_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Skipping DWD sync because the pre-market crawl failed."
    return 0
  fi

  run_dwd_sync "tushare-pre-dwd-sync-stock-eod-price" "$DWD_SYNC_IMAGE" "dwd_stock_eod_price"
  if [[ "$DWD_SYNC_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Pre-market jobs completed; DWD sync completed with failures."
    return 0
  fi

  echo "[$(date '+%F %T')] Pre-market jobs and DWD price sync completed."
}

main "$@"
