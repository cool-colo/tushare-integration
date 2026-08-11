#!/usr/bin/env bash

# Shared runtime helpers for the market batch scripts.  This file is sourced,
# not executed directly.

market_job_runner_init() {
  local log_prefix="$1"

  PROJECT_DIR="${PROJECT_DIR:-/data/flc/code/quant/tushare-integration}"
  JOBS_FILE="${JOBS_FILE:-$PROJECT_DIR/jobs.yaml}"
  CONFIG_FILE="${CONFIG_FILE:-$PROJECT_DIR/config.yaml}"
  LOG_DIR="${LOG_DIR:-$PROJECT_DIR/logs}"
  UPDATE_TYPE="${UPDATE_TYPE:-incremental}"
  LOCK_FILE="${LOCK_FILE:-/tmp/tushare-market-jobs.lock}"
  SCRIPT_START_DATE="$(date +%F)"

  IMAGE_DEFAULT="${IMAGE_DEFAULT:-tushare-integration:0.0.7}"
  IMAGE_BASIC="${IMAGE_BASIC:-$IMAGE_DEFAULT}"
  DWD_SYNC_IMAGE="${DWD_SYNC_IMAGE:-$IMAGE_DEFAULT}"
  DWS_SYNC_IMAGE="${DWS_SYNC_IMAGE:-$DWD_SYNC_IMAGE}"
  DQC_IMAGE="${DQC_IMAGE:-$DWS_SYNC_IMAGE}"
  DQC_AS_OF_DATE="${DQC_AS_OF_DATE:-$SCRIPT_START_DATE}"
  DOCKER_BIN="${DOCKER_BIN:-docker}"
  USE_SUDO="${USE_SUDO:-auto}"
  CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-0}"
  RUN_LABEL="${RUN_LABEL:-$log_prefix}"
  # 钉钉webhook:优先用环境变量,否则从config.yaml读取 dingtalk_webhook
  if [[ -z "${DINGTALK_WEBHOOK:-}" && -f "$CONFIG_FILE" ]]; then
    DINGTALK_WEBHOOK="$(sed -nE 's/^[[:space:]]*dingtalk_webhook:[[:space:]]*"?([^"#]+)"?.*$/\1/p' "$CONFIG_FILE" | head -n1)"
    DINGTALK_WEBHOOK="${DINGTALK_WEBHOOK%"${DINGTALK_WEBHOOK##*[![:space:]]}"}"
  fi
  NORMAL_JOBS_HAD_FAILURE=0
  DWD_SYNC_HAD_FAILURE=0
  DWS_SYNC_HAD_FAILURE=0
  DQC_HAD_FAILURE=0

  mkdir -p "$LOG_DIR"
  RUN_LOG="${RUN_LOG:-$LOG_DIR/${UPDATE_TYPE}-${log_prefix}-${SCRIPT_START_DATE//-/}.log}"
  exec > >(tee -a "$RUN_LOG") 2>&1

  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "[$(date '+%F %T')] Another market job run is already active. Exiting."
    exit 1
  fi

  DOCKER_PREFIX=()
  if [[ "$USE_SUDO" == "1" ]]; then
    DOCKER_PREFIX=(sudo)
  elif [[ "$USE_SUDO" == "auto" && "$EUID" -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
    DOCKER_PREFIX=(sudo)
  fi

  ACTIVE_CONTAINER=""
  ACTIVE_LOGS_PID=""
  trap market_job_runner_on_exit EXIT
  trap market_job_runner_on_interrupt INT
  trap market_job_runner_on_terminate TERM
}

docker_cmd() {
  "${DOCKER_PREFIX[@]}" "$DOCKER_BIN" "$@"
}

# 发送钉钉告警。仅用于中断流程的失败;subject为标题,content为markdown正文。
notify_dingtalk() {
  local subject="$1" content="$2"
  if [[ -z "${DINGTALK_WEBHOOK:-}" ]]; then
    echo "[$(date '+%F %T')] No dingtalk webhook, skip notify: $subject"
    return 0
  fi

  local text body
  text="### ${subject}"$'\n\n'"${content}"
  # 用python构造JSON,避免正文里的引号/换行/反斜杠破坏payload
  body="$(SUBJECT="$subject" TEXT="$text" python3 -c 'import json,os; print(json.dumps({"msgtype":"markdown","markdown":{"title":"牛 "+os.environ["SUBJECT"],"text":os.environ["TEXT"]}}))' 2>/dev/null)"
  if [[ -z "$body" ]]; then
    echo "[$(date '+%F %T')] Failed to build dingtalk payload, skip notify: $subject"
    return 0
  fi

  local resp
  resp="$(curl -sS -m 10 -X POST -H 'Content-Type: application/json' -d "$body" "$DINGTALK_WEBHOOK" 2>&1)" || true
  echo "[$(date '+%F %T')] Sent dingtalk notify: $subject; response: $resp"
}

# 收集容器最近日志,作为告警正文的一部分。
container_log_tail() {
  local container="$1" lines="${2:-25}"
  docker_cmd logs --tail "$lines" "$container" 2>&1 | tail -n "$lines"
}

cleanup_active_container() {
  if [[ -n "${ACTIVE_LOGS_PID:-}" ]]; then
    kill "$ACTIVE_LOGS_PID" >/dev/null 2>&1 || true
    wait "$ACTIVE_LOGS_PID" >/dev/null 2>&1 || true
    ACTIVE_LOGS_PID=""
  fi

  if [[ -n "${ACTIVE_CONTAINER:-}" ]]; then
    echo "[$(date '+%F %T')] Stopping active container: $ACTIVE_CONTAINER"
    docker_cmd rm -f "$ACTIVE_CONTAINER" >/dev/null 2>&1 || true
    ACTIVE_CONTAINER=""
  fi
}

market_job_runner_on_exit() {
  local exit_code="$?"
  if [[ "$exit_code" != "0" ]]; then
    cleanup_active_container
  fi
}

market_job_runner_on_interrupt() {
  echo "[$(date '+%F %T')] Interrupted. Stopping current job."
  notify_dingtalk "任务被中断 [$RUN_LABEL]" \
    "- 信号:SIGINT"$'\n'"- 当前容器:${ACTIVE_CONTAINER:-无}"$'\n'"- 时间:$(date '+%F %T')"
  cleanup_active_container
  exit 130
}

market_job_runner_on_terminate() {
  echo "[$(date '+%F %T')] Terminated. Stopping current job."
  notify_dingtalk "任务被终止 [$RUN_LABEL]" \
    "- 信号:SIGTERM"$'\n'"- 当前容器:${ACTIVE_CONTAINER:-无}"$'\n'"- 时间:$(date '+%F %T')"
  cleanup_active_container
  exit 143
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "[$(date '+%F %T')] Missing required file: $path"
    exit 1
  fi
}

run_job() {
  local container="$1" image="$2" job="$3" update_type="$4"
  local container_id exit_code logs_pid
  local command=(python main.py run job "$job")

  if [[ "$update_type" != "all" ]]; then
    command+=(--update-type "$update_type")
  fi

  echo "[$(date '+%F %T')] Starting $job update_type=$update_type with $image as $container"
  docker_cmd rm -f "$container" >/dev/null 2>&1 || true
  container_id="$(docker_cmd run -d --name "$container" --net=host -v "$JOBS_FILE:/code/app/jobs.yaml:ro" -v "$CONFIG_FILE:/code/app/config.yaml:ro" "$image" "${command[@]}")"
  echo "[$(date '+%F %T')] Container started: $container_id"
  ACTIVE_CONTAINER="$container"
  docker_cmd logs -f "$container" &
  logs_pid="$!"
  ACTIVE_LOGS_PID="$logs_pid"
  exit_code="$(docker_cmd wait "$container")"
  wait "$logs_pid" || true
  ACTIVE_LOGS_PID=""
  ACTIVE_CONTAINER=""

  if [[ "$exit_code" != "0" ]]; then
    echo "[$(date '+%F %T')] Job failed: $job exited with code $exit_code"
    NORMAL_JOBS_HAD_FAILURE=1
    notify_dingtalk "采集任务失败 [$RUN_LABEL]" \
      "- 任务:\`$job\`"$'\n'"- 类型:采集(ODS) update_type=$update_type"$'\n'"- 退出码:$exit_code"$'\n'"- 时间:$(date '+%F %T')"$'\n\n'"最近日志:"$'\n'"\`\`\`"$'\n'"$(container_log_tail "$container")"$'\n'"\`\`\`"
    [[ "$CONTINUE_ON_ERROR" == "1" ]] && return 0
    return "$exit_code"
  fi
  echo "[$(date '+%F %T')] Job completed: $job"
}

run_dwd_sync() {
  local container="$1" image="$2" table="$3"
  local container_id exit_code logs_pid

  echo "[$(date '+%F %T')] Starting DWD sync $table with $image as $container"
  docker_cmd rm -f "$container" >/dev/null 2>&1 || true
  container_id="$(docker_cmd run -d --name "$container" --net=host -v "$CONFIG_FILE:/code/app/config.yaml:ro" "$image" python main.py dwd sync "$table")"
  echo "[$(date '+%F %T')] Container started: $container_id"
  ACTIVE_CONTAINER="$container"
  docker_cmd logs -f "$container" &
  logs_pid="$!"
  ACTIVE_LOGS_PID="$logs_pid"
  exit_code="$(docker_cmd wait "$container")"
  wait "$logs_pid" || true
  ACTIVE_LOGS_PID=""
  ACTIVE_CONTAINER=""

  if [[ "$exit_code" != "0" ]]; then
    echo "[$(date '+%F %T')] DWD sync failed: $table exited with code $exit_code"
    DWD_SYNC_HAD_FAILURE=1
    notify_dingtalk "DWD同步失败 [$RUN_LABEL]" \
      "- 表:\`$table\`"$'\n'"- 阶段:DWD sync"$'\n'"- 退出码:$exit_code"$'\n'"- 时间:$(date '+%F %T')"$'\n\n'"最近日志:"$'\n'"\`\`\`"$'\n'"$(container_log_tail "$container")"$'\n'"\`\`\`"
    [[ "$CONTINUE_ON_ERROR" == "1" ]] && return 0
    return "$exit_code"
  fi
  echo "[$(date '+%F %T')] DWD sync completed: $table"
}

run_dws_sync() {
  local container="$1" image="$2" table="$3"
  local container_id exit_code logs_pid

  echo "[$(date '+%F %T')] Starting DWS sync $table with $image as $container"
  docker_cmd rm -f "$container" >/dev/null 2>&1 || true
  container_id="$(docker_cmd run -d --name "$container" --net=host -v "$CONFIG_FILE:/code/app/config.yaml:ro" "$image" python main.py dws sync "$table")"
  echo "[$(date '+%F %T')] Container started: $container_id"
  ACTIVE_CONTAINER="$container"
  docker_cmd logs -f "$container" &
  logs_pid="$!"
  ACTIVE_LOGS_PID="$logs_pid"
  exit_code="$(docker_cmd wait "$container")"
  wait "$logs_pid" || true
  ACTIVE_LOGS_PID=""
  ACTIVE_CONTAINER=""

  if [[ "$exit_code" != "0" ]]; then
    echo "[$(date '+%F %T')] DWS sync failed: $table exited with code $exit_code"
    DWS_SYNC_HAD_FAILURE=1
    notify_dingtalk "DWS同步失败 [$RUN_LABEL]" \
      "- 表:\`$table\`"$'\n'"- 阶段:DWS sync"$'\n'"- 退出码:$exit_code"$'\n'"- 时间:$(date '+%F %T')"$'\n\n'"最近日志:"$'\n'"\`\`\`"$'\n'"$(container_log_tail "$container")"$'\n'"\`\`\`"
    [[ "$CONTINUE_ON_ERROR" == "1" ]] && return 0
    return "$exit_code"
  fi
  echo "[$(date '+%F %T')] DWS sync completed: $table"
}

run_dqc() {
  local container="$1" image="$2" as_of_date="$3"
  local container_id exit_code logs_pid

  echo "[$(date '+%F %T')] Starting DWS DQC as_of_date=$as_of_date with $image as $container"
  docker_cmd rm -f "$container" >/dev/null 2>&1 || true
  container_id="$(docker_cmd run -d --name "$container" --net=host -v "$CONFIG_FILE:/code/app/config.yaml:ro" "$image" python main.py quality dqc --layer dws --all --as-of-date "$as_of_date")"
  echo "[$(date '+%F %T')] Container started: $container_id"
  ACTIVE_CONTAINER="$container"
  docker_cmd logs -f "$container" &
  logs_pid="$!"
  ACTIVE_LOGS_PID="$logs_pid"
  exit_code="$(docker_cmd wait "$container")"
  wait "$logs_pid" || true
  ACTIVE_LOGS_PID=""
  ACTIVE_CONTAINER=""

  if [[ "$exit_code" != "0" ]]; then
    echo "[$(date '+%F %T')] DWS DQC failed: as_of_date=$as_of_date exited with code $exit_code"
    DQC_HAD_FAILURE=1
    notify_dingtalk "DWS DQC失败 [$RUN_LABEL]" \
      "- as_of_date:$as_of_date"$'\n'"- 阶段:DWS DQC"$'\n'"- 退出码:$exit_code"$'\n'"- 时间:$(date '+%F %T')"$'\n\n'"最近日志:"$'\n'"\`\`\`"$'\n'"$(container_log_tail "$container")"$'\n'"\`\`\`"
    [[ "$CONTINUE_ON_ERROR" == "1" ]] && return 0
    return "$exit_code"
  fi
  echo "[$(date '+%F %T')] DWS DQC completed: as_of_date=$as_of_date"
}
