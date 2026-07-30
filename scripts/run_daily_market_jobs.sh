#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/market_job_runner.sh
source "$SCRIPT_DIR/lib/market_job_runner.sh"
market_job_runner_init "market-jobs"

main() {
  require_file "$JOBS_FILE"
  require_file "$CONFIG_FILE"

  local jobs=(
    "tushare-job-${UPDATE_TYPE}-basic|$IMAGE_BASIC|stock/basic"
    "tushare-job-${UPDATE_TYPE}-index-basic|$IMAGE_DEFAULT|index/basic|full"
    "tushare-job-${UPDATE_TYPE}-future-basic|$IMAGE_DEFAULT|future/basic|full"
    "tushare-job-${UPDATE_TYPE}-financial|$IMAGE_DEFAULT|stock/financial"
    "tushare-job-${UPDATE_TYPE}-margin|$IMAGE_DEFAULT|stock/margin"
    "tushare-job-${UPDATE_TYPE}-market|$IMAGE_DEFAULT|stock/market"
    "tushare-job-${UPDATE_TYPE}-quotes|$IMAGE_DEFAULT|stock/quotes"
    "tushare-job-${UPDATE_TYPE}-index-quotes|$IMAGE_DEFAULT|index/quotes"
    "tushare-job-daily-index-sw|$IMAGE_DEFAULT|index/sw|all"
    "tushare-job-${UPDATE_TYPE}-special|$IMAGE_DEFAULT|stock/special"
  )
  local dwd_sync_tasks=(
    "tushare-dwd-sync-trade-calendar|$DWD_SYNC_IMAGE|dwd_trade_calendar"
    "tushare-dwd-sync-stock-eod-price|$DWD_SYNC_IMAGE|dwd_stock_eod_price"
    "tushare-dwd-sync-stock-adj-factor|$DWD_SYNC_IMAGE|dwd_stock_adj_factor"
    "tushare-dwd-sync-index-eod-price|$DWD_SYNC_IMAGE|dwd_index_eod_price"
    "tushare-dwd-sync-future-eod-price|$DWD_SYNC_IMAGE|dwd_future_eod_price"
    "tushare-dwd-sync-index-classify|$DWD_SYNC_IMAGE|dwd_index_classify"
    "tushare-dwd-sync-index-weight|$DWD_SYNC_IMAGE|dwd_index_weight"
    "tushare-dwd-sync-security-master|$DWD_SYNC_IMAGE|dwd_security_master"
    "tushare-dwd-sync-stock-daily-basic|$DWD_SYNC_IMAGE|dwd_stock_daily_basic"
    "tushare-dwd-sync-stock-eod-quote-metrics|$DWD_SYNC_IMAGE|dwd_stock_eod_quote_metrics"
    "tushare-dwd-sync-stock-st|$DWD_SYNC_IMAGE|dwd_stock_st"
    "tushare-dwd-sync-stock-financial-indicator|$DWD_SYNC_IMAGE|dwd_stock_financial_indicator"
    "tushare-dwd-sync-stock-income|$DWD_SYNC_IMAGE|dwd_stock_income"
    "tushare-dwd-sync-stock-balance-sheet|$DWD_SYNC_IMAGE|dwd_stock_balance_sheet"
    "tushare-dwd-sync-stock-cashflow|$DWD_SYNC_IMAGE|dwd_stock_cashflow"
    "tushare-dwd-sync-stock-dividend|$DWD_SYNC_IMAGE|dwd_stock_dividend"
    "tushare-dwd-sync-stock-northbound-holding|$DWD_SYNC_IMAGE|dwd_stock_northbound_holding"
    "tushare-dwd-sync-stock-margin-trading|$DWD_SYNC_IMAGE|dwd_stock_margin_trading"
    "tushare-dwd-sync-stock-chip-distribution|$DWD_SYNC_IMAGE|dwd_stock_chip_distribution"
    "tushare-dwd-sync-dc-concept|$DWD_SYNC_IMAGE|dwd_dc_concept"
    "tushare-dwd-sync-dc-concept-cons|$DWD_SYNC_IMAGE|dwd_dc_concept_cons"
    "tushare-dwd-sync-dc-index|$DWD_SYNC_IMAGE|dwd_dc_index"
    "tushare-dwd-sync-dc-member|$DWD_SYNC_IMAGE|dwd_dc_member"
  )
  local dws_sync_tasks=(
    "tushare-dws-sync-stock-financial-indicator-quarter|$DWS_SYNC_IMAGE|dws_stock_financial_indicator_quarter"
    "tushare-dws-sync-stock-cashflow-quarter|$DWS_SYNC_IMAGE|dws_stock_cashflow_quarter"
    "tushare-dws-sync-stock-income-quarter|$DWS_SYNC_IMAGE|dws_stock_income_quarter"
    "tushare-dws-sync-stock-factor-wide|$DWS_SYNC_IMAGE|dws_stock_factor_wide"
    "tushare-dws-sync-stock-factor-wide-matrix|$DWS_SYNC_IMAGE|dws_stock_factor_wide_matrix"
  )

  echo "[$(date '+%F %T')] Market jobs started. update_type=$UPDATE_TYPE Log: $RUN_LOG"
  local entry container image job job_update_type table
  for entry in "${jobs[@]}"; do
    IFS="|" read -r container image job job_update_type <<< "$entry"
    run_job "$container" "$image" "$job" "${job_update_type:-$UPDATE_TYPE}"
  done
  if [[ "$NORMAL_JOBS_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Skipping DWD sync tasks because one or more normal jobs failed."
    return 0
  fi

  echo "[$(date '+%F %T')] DWD sync tasks started."
  for entry in "${dwd_sync_tasks[@]}"; do
    IFS="|" read -r container image table <<< "$entry"
    run_dwd_sync "$container" "$image" "$table"
  done
  if [[ "$DWD_SYNC_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Market jobs completed; DWD sync tasks completed with failures."
    return 0
  fi

  echo "[$(date '+%F %T')] DWS sync tasks started."
  for entry in "${dws_sync_tasks[@]}"; do
    IFS="|" read -r container image table <<< "$entry"
    run_dws_sync "$container" "$image" "$table"
  done
  if [[ "$DWS_SYNC_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Market jobs completed; DWS sync tasks completed with failures."
    return 0
  fi

  echo "[$(date '+%F %T')] DWS DQC task started."
  run_dqc "tushare-dqc-dws-all" "$DQC_IMAGE" "$DQC_AS_OF_DATE"
  if [[ "$DQC_HAD_FAILURE" != "0" ]]; then
    echo "[$(date '+%F %T')] Market jobs completed; DWS DQC task completed with failures."
    return 0
  fi
  echo "[$(date '+%F %T')] Market jobs, DWD sync tasks, DWS sync tasks, and DWS DQC task completed."
}

main "$@"
