#!/usr/bin/env bash
set -Eeuo pipefail

ENV_SH="${ENV_SH:-/app/script/env.sh}"
if [[ ! -f "$ENV_SH" ]]; then
  echo "error: env script not found: $ENV_SH" >&2
  exit 1
fi

# shellcheck source=/app/script/env.sh
source "$ENV_SH"

SERVICE_NAME="${SERVICE_NAME:-/function_input}"
SERVICE_TYPE="${SERVICE_TYPE:-function_msgs/srv/FunctionInput}"
SOURCE_NAME="${SOURCE_NAME:-rcp_cli_nav_jump_test}"
NAV_DURATION_SEC="${NAV_DURATION_SEC:-180}"
ACTION_SLEEP_SEC="${ACTION_SLEEP_SEC:-3}"
POST_STOP_SLEEP_SEC="${POST_STOP_SLEEP_SEC:-5}"
POST_JUMP_SLEEP_SEC="${POST_JUMP_SLEEP_SEC:-15}"
MOTOR_POWER_CYCLE_SLEEP_SEC="${MOTOR_POWER_CYCLE_SLEEP_SEC:-5}"
POST_LOCO_START_SLEEP_SEC="${POST_LOCO_START_SLEEP_SEC:-3}"
LOOPS="${LOOPS:-1}"
SERVICE_WAIT_SEC="${SERVICE_WAIT_SEC:-20}"
SERVICE_TIMEOUT_SEC="${SERVICE_TIMEOUT_SEC:-15}"
LOCOMOTION_SYSTEMD_SERVICE="${LOCOMOTION_SYSTEMD_SERVICE:-locomotion}"
LOCOMOTION_SERVICE_NAME="${LOCOMOTION_SERVICE_NAME:-/locomotion/set_run_mode}"
LOCOMOTION_SERVICE_TYPE="${LOCOMOTION_SERVICE_TYPE:-function_msgs/srv/SetRunMode}"
BMS_TEST_BIN="${BMS_TEST_BIN:-}"
DAGS_ROOT="${DAGS_ROOT:-}"
DRY_RUN=0
MOTOR_POWER_OFF=0
LOCOMOTION_STOPPED_BY_SCRIPT=0

usage() {
  cat <<'EOF'
Usage: test_rcp_nav_jump_sequence.sh [options]

Runs this RCP DAG sequence through ros2 cli:
  stand -> start navigation -> wait -> stop navigation -> jump in place -> laydown
  -> stop locomotion -> motor power off/on -> start locomotion

Options:
  -d, --duration SEC     Navigation duration before stop. Default: 180
      --sleep SEC        Safety sleep between actions. Default: 3
      --post-stop-sleep SEC
                         Sleep after stop_navigation. Default: 5
      --post-jump-sleep SEC
                         Sleep after jump in place before laydown. Default: 15
      --motor-sleep SEC  Motor power-off duration. Default: 5
      --post-loco-start-sleep SEC
                         Sleep after starting locomotion. Default: 3
      --loops N          Number of full cycles to run. Default: 1
      --dags-root PATH   DAG root. Default: /app/config/dags, then repo script/dags
      --source NAME      FunctionInput source name. Default: rcp_cli_nav_jump_test
      --service NAME     FunctionInput service name. Default: /function_input
      --timeout SEC      Timeout for each ros2 service call. Default: 15
      --dry-run          Validate inputs and print ros2 calls without executing them
  -h, --help             Show this help

Environment overrides:
  ENV_SH, DAGS_ROOT, NAV_DURATION_SEC, ACTION_SLEEP_SEC, SERVICE_WAIT_SEC,
  POST_STOP_SLEEP_SEC, POST_JUMP_SLEEP_SEC, MOTOR_POWER_CYCLE_SLEEP_SEC,
  POST_LOCO_START_SLEEP_SEC, LOOPS, SERVICE_TIMEOUT_SEC, SERVICE_NAME,
  SOURCE_NAME, BMS_TEST_BIN
EOF
}

log() {
  printf '[%(%Y-%m-%d %H:%M:%S)T] %s\n' -1 "$*"
}

die() {
  echo "error: $*" >&2
  exit 1
}

is_seconds() {
  [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]
}

is_positive_integer() {
  [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

yaml_single_quote_escape() {
  sed "s/'/''/g"
}

repo_root_from_script() {
  local script_dir
  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  cd -- "$script_dir/.." && pwd
}

choose_dags_root() {
  if [[ -n "$DAGS_ROOT" ]]; then
    [[ -d "$DAGS_ROOT" ]] || die "DAGS_ROOT does not exist: $DAGS_ROOT"
    return
  fi

  if [[ -d /app/config/dags ]]; then
    DAGS_ROOT=/app/config/dags
    return
  fi

  local repo_root
  repo_root="$(repo_root_from_script)"
  if [[ -d "$repo_root/script/dags" ]]; then
    DAGS_ROOT="$repo_root/script/dags"
    return
  fi

  die "cannot find DAG root; pass --dags-root PATH"
}

compact_json() {
  local file="$1"

  if command -v jq >/dev/null 2>&1; then
    jq -c . "$file"
    return
  fi

  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as f:
    print(json.dumps(json.load(f), separators=(",", ":")))
PY
    return
  fi

  die "need jq or python3 to compact JSON"
}

request_id_for() {
  local label="$1"
  printf '%s_%s_%s_%s' \
    "$SOURCE_NAME" \
    "$label" \
    "$(date +%Y%m%d%H%M%S)" \
    "$RANDOM" | tr -c 'A-Za-z0-9_.:-' '_'
}

wait_for_ros_service() {
  local service_name="$1"
  local service_type="$2"

  (( DRY_RUN )) && return

  command -v ros2 >/dev/null 2>&1 || die "ros2 command not found after sourcing $ENV_SH"
  command -v timeout >/dev/null 2>&1 || die "timeout command not found"

  log "waiting for $service_name ($service_type)"

  local deadline=$((SECONDS + SERVICE_WAIT_SEC))
  local actual_type=""
  while (( SECONDS <= deadline )); do
    actual_type="$(timeout 5 ros2 service type "$service_name" 2>/dev/null || true)"
    if printf '%s\n' "$actual_type" | grep -Fxq "$service_type"; then
      return
    fi
    sleep 1
  done

  if [[ -n "$actual_type" ]]; then
    die "$service_name type is '$actual_type', expected '$service_type'"
  fi
  die "$service_name not available after ${SERVICE_WAIT_SEC}s"
}

wait_for_service() {
  wait_for_ros_service "$SERVICE_NAME" "$SERVICE_TYPE"
}

resolve_bms_test() {
  if [[ -n "$BMS_TEST_BIN" ]]; then
    if [[ "$BMS_TEST_BIN" == */* ]]; then
      [[ -x "$BMS_TEST_BIN" ]] ||
        die "BMS_TEST_BIN is not executable: $BMS_TEST_BIN"
    elif command -v "$BMS_TEST_BIN" >/dev/null 2>&1; then
      BMS_TEST_BIN="$(command -v "$BMS_TEST_BIN")"
    elif (( DRY_RUN )); then
      return
    else
      die "BMS_TEST_BIN not found in PATH: $BMS_TEST_BIN"
    fi
    return
  fi

  if command -v bms_test >/dev/null 2>&1; then
    BMS_TEST_BIN="$(command -v bms_test)"
    return
  fi

  if [[ -x /usr/vita/bin/bms_test ]]; then
    BMS_TEST_BIN=/usr/vita/bin/bms_test
    return
  fi

  if (( DRY_RUN )); then
    BMS_TEST_BIN=bms_test
    return
  fi

  die "bms_test not found; pass BMS_TEST_BIN=/path/to/bms_test"
}

run_or_print() {
  if (( DRY_RUN )); then
    printf 'DRY_RUN'
    printf ' %q' "$@"
    printf '\n'
    return
  fi

  "$@"
}

start_locomotion() {
  log "start ${LOCOMOTION_SYSTEMD_SERVICE}.service"
  run_or_print systemctl start "$LOCOMOTION_SYSTEMD_SERVICE"
  LOCOMOTION_STOPPED_BY_SCRIPT=0
  sleep_for "$POST_LOCO_START_SLEEP_SEC" "after starting locomotion"
  wait_for_ros_service "$LOCOMOTION_SERVICE_NAME" "$LOCOMOTION_SERVICE_TYPE"
}

ensure_locomotion_ready() {
  if (( DRY_RUN )); then
    log "dry-run: ensure ${LOCOMOTION_SYSTEMD_SERVICE}.service is active"
    return
  fi

  if ! systemctl is-active --quiet "$LOCOMOTION_SYSTEMD_SERVICE"; then
    log "${LOCOMOTION_SYSTEMD_SERVICE}.service is not active"
    start_locomotion
    return
  fi

  wait_for_ros_service "$LOCOMOTION_SERVICE_NAME" "$LOCOMOTION_SERVICE_TYPE"
}

motor_power_cycle() {
  resolve_bms_test

  log "stop ${LOCOMOTION_SYSTEMD_SERVICE}.service before motor power cycle"
  run_or_print systemctl stop "$LOCOMOTION_SYSTEMD_SERVICE"
  LOCOMOTION_STOPPED_BY_SCRIPT=1

  log "motor power off: ${BMS_TEST_BIN} -c 0"
  run_or_print "$BMS_TEST_BIN" -c 0
  MOTOR_POWER_OFF=1

  sleep_for "$MOTOR_POWER_CYCLE_SLEEP_SEC" "motor power off"

  log "motor power on: ${BMS_TEST_BIN} -s 0"
  run_or_print "$BMS_TEST_BIN" -s 0
  MOTOR_POWER_OFF=0

  start_locomotion
}

cleanup_on_exit() {
  local rc=$?
  if (( DRY_RUN )); then
    return "$rc"
  fi

  if (( MOTOR_POWER_OFF )); then
    log "cleanup: motor may be powered off, running ${BMS_TEST_BIN:-bms_test} -s 0"
    if [[ -n "$BMS_TEST_BIN" && -x "$BMS_TEST_BIN" ]]; then
      "$BMS_TEST_BIN" -s 0 || true
    elif command -v bms_test >/dev/null 2>&1; then
      bms_test -s 0 || true
    elif [[ -x /usr/vita/bin/bms_test ]]; then
      /usr/vita/bin/bms_test -s 0 || true
    fi
  fi

  if (( LOCOMOTION_STOPPED_BY_SCRIPT )); then
    log "cleanup: starting ${LOCOMOTION_SYSTEMD_SERVICE}.service"
    systemctl start "$LOCOMOTION_SYSTEMD_SERVICE" || true
  fi

  return "$rc"
}

submit_dag() {
  local label="$1"
  local rel_path="$2"
  local full_path="$DAGS_ROOT/$rel_path"

  [[ -f "$full_path" ]] || die "DAG file not found: $full_path"

  local dag_json
  dag_json="$(compact_json "$full_path")" || die "failed to parse JSON: $full_path"

  local dag_yaml
  local source_yaml
  dag_yaml="$(printf '%s' "$dag_json" | yaml_single_quote_escape)"
  source_yaml="$(printf '%s' "$SOURCE_NAME" | yaml_single_quote_escape)"

  local request_id
  request_id="$(request_id_for "$label")"

  local request
  request="{source: '$source_yaml', dag: '$dag_yaml', request_id: '$request_id'}"

  log "submit $label: $rel_path"

  if (( DRY_RUN )); then
    printf 'DRY_RUN ros2 service call %q %q %q\n' \
      "$SERVICE_NAME" "$SERVICE_TYPE" "$request"
    return
  fi

  local output
  if ! output="$(timeout "$SERVICE_TIMEOUT_SEC" ros2 service call \
      "$SERVICE_NAME" "$SERVICE_TYPE" "$request" 2>&1)"; then
    printf '%s\n' "$output" >&2
    die "ros2 service call failed for $label"
  fi

  printf '%s\n' "$output"

  if printf '%s\n' "$output" | grep -Eiq 'success=\[[Ff]alse\]|success:[[:space:]]*\[[[:space:]]*false|- false'; then
    die "$label was rejected by $SERVICE_NAME"
  fi
}

sleep_for() {
  local seconds="$1"
  local reason="$2"

  if (( DRY_RUN )); then
    log "dry-run: skip sleep ${seconds}s ($reason)"
    return
  fi

  log "sleep ${seconds}s ($reason)"
  sleep "$seconds"
}

parse_args() {
  while (($#)); do
    case "$1" in
      -d|--duration)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        NAV_DURATION_SEC="$2"
        shift 2
        ;;
      --sleep)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        ACTION_SLEEP_SEC="$2"
        shift 2
        ;;
      --post-stop-sleep)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        POST_STOP_SLEEP_SEC="$2"
        shift 2
        ;;
      --post-jump-sleep)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        POST_JUMP_SLEEP_SEC="$2"
        shift 2
        ;;
      --motor-sleep)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        MOTOR_POWER_CYCLE_SLEEP_SEC="$2"
        shift 2
        ;;
      --post-loco-start-sleep)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        POST_LOCO_START_SLEEP_SEC="$2"
        shift 2
        ;;
      --loops)
        [[ $# -ge 2 ]] || die "$1 requires N"
        LOOPS="$2"
        shift 2
        ;;
      --dags-root)
        [[ $# -ge 2 ]] || die "$1 requires PATH"
        DAGS_ROOT="$2"
        shift 2
        ;;
      --source)
        [[ $# -ge 2 ]] || die "$1 requires NAME"
        SOURCE_NAME="$2"
        shift 2
        ;;
      --service)
        [[ $# -ge 2 ]] || die "$1 requires NAME"
        SERVICE_NAME="$2"
        shift 2
        ;;
      --timeout)
        [[ $# -ge 2 ]] || die "$1 requires SEC"
        SERVICE_TIMEOUT_SEC="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "unknown option: $1"
        ;;
    esac
  done
}

main() {
  trap cleanup_on_exit EXIT

  parse_args "$@"

  is_seconds "$NAV_DURATION_SEC" || die "invalid duration: $NAV_DURATION_SEC"
  is_seconds "$ACTION_SLEEP_SEC" || die "invalid sleep: $ACTION_SLEEP_SEC"
  is_seconds "$POST_STOP_SLEEP_SEC" ||
    die "invalid post-stop sleep: $POST_STOP_SLEEP_SEC"
  is_seconds "$POST_JUMP_SLEEP_SEC" ||
    die "invalid post-jump sleep: $POST_JUMP_SLEEP_SEC"
  is_seconds "$MOTOR_POWER_CYCLE_SLEEP_SEC" ||
    die "invalid motor sleep: $MOTOR_POWER_CYCLE_SLEEP_SEC"
  is_seconds "$POST_LOCO_START_SLEEP_SEC" ||
    die "invalid post-loco-start sleep: $POST_LOCO_START_SLEEP_SEC"
  is_seconds "$SERVICE_TIMEOUT_SEC" || die "invalid timeout: $SERVICE_TIMEOUT_SEC"
  is_positive_integer "$LOOPS" || die "invalid loops: $LOOPS"
  [[ "$SERVICE_WAIT_SEC" =~ ^[0-9]+$ ]] || die "invalid service wait: $SERVICE_WAIT_SEC"

  choose_dags_root
  resolve_bms_test

  log "DAGS_ROOT=$DAGS_ROOT"
  log "navigation duration=${NAV_DURATION_SEC}s, safety sleep=${ACTION_SLEEP_SEC}s"
  log "post-stop sleep=${POST_STOP_SLEEP_SEC}s, post-jump sleep=${POST_JUMP_SLEEP_SEC}s"
  log "motor sleep=${MOTOR_POWER_CYCLE_SLEEP_SEC}s, loops=${LOOPS}"

  wait_for_service

  for ((cycle = 1; cycle <= LOOPS; cycle++)); do
    log "cycle ${cycle}/${LOOPS} start"

    ensure_locomotion_ready

    submit_dag "stand_c${cycle}" "action_stand_from_phone.json"
    sleep_for "$ACTION_SLEEP_SEC" "after stand"

    submit_dag "start_navigation_c${cycle}" "start_navigation_from_phone.json"
    sleep_for "$NAV_DURATION_SEC" "navigation running"

    submit_dag "stop_navigation_c${cycle}" "stop_navigation_from_phone.json"
    sleep_for "$POST_STOP_SLEEP_SEC" "after stop navigation"

    submit_dag "jump_in_place_c${cycle}" "actions/JUMP_IN_PLACE.json"
    sleep_for "$POST_JUMP_SLEEP_SEC" "after jump in place"

    submit_dag "laydown_c${cycle}" "action_down_from_phone.json"
    sleep_for "$ACTION_SLEEP_SEC" "after laydown"

    motor_power_cycle

    log "cycle ${cycle}/${LOOPS} complete"
  done

  log "sequence complete"
}

main "$@"
