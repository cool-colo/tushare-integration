#!/usr/bin/env bash
set -Eeuo pipefail

# Fill missing all-market RQData minute-bar days from recent years backwards.
# Explicit bootstrap ranges are intentional: stock_minute bootstrap skips days
# whose latest coverage event is complete, while backfill refreshes every day in
# the requested range. Partial days still resume from their persisted staging
# cursor.

PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
RUNNER="${RICEQUANT_RUNNER:-$PROJECT_DIR/scripts/run_ricequant_jobs.sh}"
START_YEAR="${RICEQUANT_MINUTE_BACKFILL_START_YEAR:-2015}"
END_YEAR="${RICEQUANT_MINUTE_BACKFILL_END_YEAR:-2019}"

if [[ ! -x "$RUNNER" ]]; then
  echo "RiceQuant runner is missing or not executable: $RUNNER" >&2
  exit 1
fi

if [[ ! "$START_YEAR" =~ ^[0-9]{4}$ || ! "$END_YEAR" =~ ^[0-9]{4}$ ]]; then
  echo "Backfill years must be four-digit integers" >&2
  exit 2
fi

if (( START_YEAR > END_YEAR )); then
  echo "Backfill start year must not be later than end year" >&2
  exit 2
fi

RESULT_LOG="$(mktemp /tmp/ricequant-minute-backfill-result.XXXXXX.log)"
trap 'rm -f "$RESULT_LOG"' EXIT

echo "[$(date '+%F %T')] RiceQuant minute backfill started: $END_YEAR -> $START_YEAR"

for ((year = END_YEAR; year >= START_YEAR; year--)); do
  range_start="${year}-01-01"
  range_end="${year}-12-31"
  echo "[$(date '+%F %T')] Checking/filling stock_minute year=$year"

  set +e
  "$RUNNER" bootstrap \
    --dataset stock_minute \
    --start "$range_start" \
    --end "$range_end" | tee "$RESULT_LOG"
  runner_status=${PIPESTATUS[0]}
  set -e

  if (( runner_status != 0 )); then
    echo "[$(date '+%F %T')] Minute backfill failed for year=$year exit_code=$runner_status" >&2
    exit "$runner_status"
  fi

  if grep -Fq '"status": "quota_paused"' "$RESULT_LOG"; then
    echo "[$(date '+%F %T')] Daily quota paused in year=$year; rerun this script on the next quota day"
    exit 0
  fi

  if ! grep -Fq '"status": "complete"' "$RESULT_LOG"; then
    echo "[$(date '+%F %T')] Runner returned no recognized completion status for year=$year" >&2
    exit 1
  fi

  echo "[$(date '+%F %T')] Minute backfill year=$year complete"
done

echo "[$(date '+%F %T')] RiceQuant minute backfill complete: $END_YEAR -> $START_YEAR"
