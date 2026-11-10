#!/usr/bin/env bash
set -Eeuo pipefail

# Crontab entry point for every implemented RiceQuant incremental dataset.
# Calendar and instrument snapshots are dependencies and are added by the
# runner automatically, so they must not be scheduled as separate jobs.
PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
RUNNER="$PROJECT_DIR/scripts/run_ricequant_jobs.sh"
INCLUDE_TICK="${RICEQUANT_INCLUDE_TICK:-1}"
LOG_DIR="${RICEQUANT_LOG_DIR:-$PROJECT_DIR/logs}"
CRON_LOG="${RICEQUANT_CRON_LOG_FILE:-$LOG_DIR/ricequant-incremental-cron-$(date +%Y%m%d).log}"

mkdir -p "$LOG_DIR"
exec >>"$CRON_LOG" 2>&1

echo "[$(date '+%F %T')] RiceQuant incremental cron wrapper started. include_tick=$INCLUDE_TICK"

if [[ ! -x "$RUNNER" ]]; then
  echo "RiceQuant runner is missing or not executable: $RUNNER" >&2
  exit 1
fi

case "$INCLUDE_TICK" in
  0|1) ;;
  *)
    echo "RICEQUANT_INCLUDE_TICK must be 0 or 1" >&2
    exit 2
    ;;
esac

datasets=(
  index_daily
  index_components
  index_weights
  index_weights_ex
  stock_daily
  stock_minute
  stock_ex_factor
  stock_split
  financial_income
  financial_balance
  financial_cashflow
  financial_metric
  concept_catalog
  concept_members
  concept_snapshot
  industry_mapping
  industry_members
  industry_snapshot
  sector_snapshot
)

if [[ "$INCLUDE_TICK" == "1" ]]; then
  datasets+=(tick)
fi

args=(incremental)
for dataset in "${datasets[@]}"; do
  args+=(--dataset "$dataset")
done

status=0
"$RUNNER" "${args[@]}" || status=$?

echo "[$(date '+%F %T')] RiceQuant incremental cron wrapper finished. exit_code=$status"
exit "$status"
