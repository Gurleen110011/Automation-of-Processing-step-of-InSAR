#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMAND="${1:-all}"

case "$COMMAND" in
  step)
    FIRST_STEP="${2:-}"
    LAST_STEP="$FIRST_STEP"
    CONFIG_FILE="${3:-${CONFIG_FILE:-$ROOT_DIR/config/workflow.env}}"
    ;;
  from)
    FIRST_STEP="${2:-}"
    LAST_STEP="17"
    CONFIG_FILE="${3:-${CONFIG_FILE:-$ROOT_DIR/config/workflow.env}}"
    ;;
  range)
    FIRST_STEP="${2:-}"
    LAST_STEP="${3:-}"
    CONFIG_FILE="${4:-${CONFIG_FILE:-$ROOT_DIR/config/workflow.env}}"
    ;;
  all)
    FIRST_STEP="01"
    LAST_STEP="17"
    CONFIG_FILE="${2:-${CONFIG_FILE:-$ROOT_DIR/config/workflow.env}}"
    ;;
  list|help|-h|--help)
    FIRST_STEP=""
    LAST_STEP=""
    CONFIG_FILE="${2:-${CONFIG_FILE:-$ROOT_DIR/config/workflow.env}}"
    ;;
  *)
    echo "Unknown command: $COMMAND" >&2
    exit 2
    ;;
esac

STEP_FILES=(
  ""
  "01_validate.py"
  "02_unzip_slcs.py"
  "03_prepare_aois.py"
  "04_scan_scenes.py"
  "05_reframe.py"
  "06_load_dem.py"
  "07_align.py"
  "08_geocode.py"
  "09_baseline_pairs.py"
  "10_interferograms.py"
  "11_unwrap.py"
  "12_stratified_correction.py"
  "13_sbas_inversion.py"
  "14_geocode_products.py"
  "15_export_results.py"
  "16_finalize.py"
  "17_collect_results.py"
)

print_steps() {
  cat <<'STEPS'
01  Validate inputs and AOI selection
02  Unzip Sentinel-1 ZIP products
03  Prepare AOI input/configuration directories
04  Scan SLC scenes and check/download orbits
05  Reframe scenes to each AOI
06  Load and normalize each AOI DEM
07  Align scenes to the reference acquisition
08  Compute geocoding lookup grids
09  Build the small-baseline pair network
10  Generate interferograms and coherence
11  Unwrap phase with SNAPHU
12  Apply stratified/topographic correction
13  Run SBAS inversion
14  Geocode displacement and velocity products
15  Export GeoTIFF and time-series products
16  Verify and finalize each AOI
17  Collect final results
STEPS
}

print_usage() {
  cat <<'USAGE'
Usage:
  ./run_all.sh all [config-file]
  ./run_all.sh step <number> [config-file]
  ./run_all.sh from <number> [config-file]
  ./run_all.sh range <first-number> <last-number> [config-file]
  ./run_all.sh list

The normal complete command is:
  ./run_all.sh all

Examples:
  ./run_all.sh step 05
  ./run_all.sh from 10
  ./run_all.sh range 04 08
USAGE
}

if [[ "$COMMAND" == "list" ]]; then
  print_steps
  exit 0
fi
if [[ "$COMMAND" == "help" || "$COMMAND" == "-h" || "$COMMAND" == "--help" ]]; then
  print_usage
  printf '\n'
  print_steps
  exit 0
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Configuration file not found: $CONFIG_FILE" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$CONFIG_FILE"
PYTHON_BIN="${PYTHON_BIN:-python3}"

: "${MASTER_NAME:=LocalProcessing}"
: "${AOI_GROUPS:=ABC}"
: "${AOI_INDICES:=1-10}"
: "${AOI_LIST:=}"
: "${MAX_PARALLEL_AOIS:=1}"
: "${FORCE_STEPS:=0}"
if (( MAX_PARALLEL_AOIS < 1 )); then MAX_PARALLEL_AOIS=1; fi

validate_step_number() {
  local value="$1"
  [[ "$value" =~ ^[0-9]{1,2}$ ]] || return 1
  local number=$((10#$value))
  (( number >= 1 && number <= 17 ))
}

if ! validate_step_number "$FIRST_STEP" || ! validate_step_number "$LAST_STEP"; then
  echo "Step numbers must be between 01 and 17." >&2
  print_usage >&2
  exit 2
fi
FIRST_NUMBER=$((10#$FIRST_STEP))
LAST_NUMBER=$((10#$LAST_STEP))
if (( FIRST_NUMBER > LAST_NUMBER )); then
  echo "The first step cannot come after the last step." >&2
  exit 2
fi

AOI_ARGS=(--groups "$AOI_GROUPS" --indices "$AOI_INDICES")
if [[ -n "$AOI_LIST" ]]; then
  AOI_ARGS+=(--aois "$AOI_LIST")
fi
OPTIONAL_AOI_FILE=()
[[ -n "${AOI_INLINE_FILE:-}" ]] && OPTIONAL_AOI_FILE=(--aoi-inline-file "$AOI_INLINE_FILE")
OPTIONAL_ORBIT_DIR=()
[[ -n "${ORBIT_DIR:-}" ]] && OPTIONAL_ORBIT_DIR=(--orbit-dir "$ORBIT_DIR")

expand_indices() {
  local specification="$1"
  local token start end value
  IFS=',' read -r -a tokens <<< "$specification"
  for token in "${tokens[@]}"; do
    token="${token//[[:space:]]/}"
    [[ -z "$token" ]] && continue
    if [[ "$token" == *-* ]]; then
      start="${token%%-*}"
      end="${token##*-}"
      for ((value=start; value<=end; value++)); do
        printf '%s\n' "$value"
      done
    else
      printf '%s\n' "$token"
    fi
  done
}

selected_aois() {
  local value group index
  if [[ -n "$AOI_LIST" ]]; then
    value="${AOI_LIST// /,}"
    IFS=',' read -r -a explicit <<< "$value"
    for value in "${explicit[@]}"; do
      value="${value^^}"
      [[ -n "$value" ]] && printf '%s\n' "$value"
    done
    return
  fi
  local groups="${AOI_GROUPS//[ ,]/}"
  mapfile -t indices < <(expand_indices "$AOI_INDICES")
  for ((i=0; i<${#groups}; i++)); do
    group="${groups:i:1}"
    for index in "${indices[@]}"; do
      printf '%s%s\n' "${group^^}" "$index"
    done
  done
}
mapfile -t AOIS < <(selected_aois | awk 'NF && !seen[$0]++')
if (( ${#AOIS[@]} == 0 )); then
  echo "No AOIs selected." >&2
  exit 2
fi

MASTER_DIR="$(realpath -m "$SCRATCH_ROOT/$MASTER_NAME")"

invalidate_selected_markers() {
  [[ "$FORCE_STEPS" == "1" ]] || return 0
  local start="$FIRST_NUMBER"
  (( start < 4 )) && start=4
  (( start > 16 )) && return 0
  local aoi number stem marker_dir
  for aoi in "${AOIS[@]}"; do
    marker_dir="$MASTER_DIR/$aoi/.stage_markers"
    [[ -d "$marker_dir" ]] || continue
    for ((number=start; number<=16; number++)); do
      stem="${STEP_FILES[$number]%.py}"
      rm -f "$marker_dir/${stem}.success" "$marker_dir/${stem}.failed"
    done
    rm -f "$MASTER_DIR/$aoi/.workflow_success"
  done
}

invalidate_selected_markers

run_global_step() {
  local number="$1"
  local script="$ROOT_DIR/scripts/${STEP_FILES[$number]}"
  local extra=()
  case "$number" in
    1)
      [[ "${CHECK_RUNTIME_DEPS:-0}" == "1" ]] && extra+=(--check-runtime-deps)
      "$PYTHON_BIN" "$script" \
        "${AOI_ARGS[@]}" \
        --slc-source "$SLC_SOURCE" \
        --dem-root "$DEM_ROOT" \
        --aoi-root "$AOI_ROOT" \
        "${OPTIONAL_AOI_FILE[@]}" \
        "${OPTIONAL_ORBIT_DIR[@]}" \
        "${extra[@]}"
      ;;
    2)
      "$PYTHON_BIN" "$script" \
        --slc-source "$SLC_SOURCE" \
        --workers "${UNZIP_WORKERS:-4}"
      ;;
    3)
      [[ "${COPY_DEM:-0}" == "1" ]] && extra+=(--copy-dem)
      [[ "${RESUME_EXISTING_OUTPUTS:-0}" == "1" ]] && extra+=(--resume)
      [[ "${NO_DOWNLOAD_ORBITS:-0}" == "1" ]] && extra+=(--no-download-orbits)
      [[ "${ALLOW_PARALLEL_HDF5:-0}" == "1" ]] && extra+=(--allow-parallel-hdf5)
      "$PYTHON_BIN" "$script" \
        "${AOI_ARGS[@]}" \
        --master "$MASTER_NAME" \
        --scratch-root "$SCRATCH_ROOT" \
        --slc-source "$SLC_SOURCE" \
        --dem-root "$DEM_ROOT" \
        --aoi-root "$AOI_ROOT" \
        "${OPTIONAL_AOI_FILE[@]}" \
        "${OPTIONAL_ORBIT_DIR[@]}" \
        --link-mode "${LINK_MODE:-hardlink}" \
        --orbit-link-mode "${ORBIT_LINK_MODE:-hardlink}" \
        --reference "${REFERENCE_DATE:-2025-01-11}" \
        --limit "${PAIR_LIMIT:-2}" \
        --corr-limit "${CORR_LIMIT:-0.2}" \
        --basedays "${BASELINE_DAYS:-60}" \
        --basemeters "${BASELINE_METERS:-250}" \
        --ncpus "${NCPUS_PER_AOI:-4}" \
        --memory-gb "${MEMORY_GB_PER_AOI:-12}" \
        --dask-workers "${DASK_WORKERS_PER_AOI:-2}" \
        "${extra[@]}"
      ;;
    17)
      [[ "${INCLUDE_HEAVY_RESULTS:-0}" == "1" ]] && extra+=(--include-heavy)
      "$PYTHON_BIN" "$script" \
        "${AOI_ARGS[@]}" \
        --master "$MASTER_NAME" \
        --scratch-root "$SCRATCH_ROOT" \
        --home-results "$HOME_RESULTS" \
        "${extra[@]}"
      ;;
    *)
      echo "Internal error: $number is not a global step" >&2
      return 2
      ;;
  esac
}

run_one_aoi_step() {
  local number="$1"
  local aoi="$2"
  local script="$ROOT_DIR/scripts/${STEP_FILES[$number]}"
  local stem="${STEP_FILES[$number]%.py}"
  local aoi_dir="$MASTER_DIR/$aoi"
  local config="$aoi_dir/config.json"
  local marker_dir="$aoi_dir/.stage_markers"
  local success="$marker_dir/${stem}.success"
  local failure="$marker_dir/${stem}.failed"
  local log_dir="$aoi_dir/logs"
  local stage_log="$log_dir/${stem}.log"
  local combined_log="$aoi_dir/processing_${aoi}.log"

  if [[ ! -f "$config" ]]; then
    echo "[$aoi][$stem] Missing configuration: $config" >&2
    return 2
  fi
  mkdir -p "$marker_dir" "$log_dir"
  if [[ -f "$success" && "$FORCE_STEPS" != "1" ]]; then
    echo "[$aoi][$stem] SKIP: success marker exists"
    return 0
  fi
  rm -f "$success" "$failure"

  echo "[$aoi][$stem] START"
  if env \
      PBS_NCPUS="${NCPUS_PER_AOI:-4}" \
      HDF5_USE_FILE_LOCKING="FALSE" \
      "$PYTHON_BIN" "$script" --config "$config" 2>&1 \
      | sed -u "s/^/[$aoi][$stem] /" \
      | tee -a "$stage_log" "$combined_log"; then
    printf 'completed_utc=%s\nscript=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$script" > "$success"
    rm -f "$failure"
    if (( number == 16 )); then
      printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$aoi_dir/.workflow_success"
    fi
    echo "[$aoi][$stem] SUCCESS"
    return 0
  else
    local code=$?
    printf 'failed_utc=%s\nscript=%s\nexit_code=%s\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$script" "$code" > "$failure"
    rm -f "$aoi_dir/.workflow_success"
    echo "[$aoi][$stem] FAILED exit=$code" >&2
    return "$code"
  fi
}

run_scientific_step() {
  local number="$1"
  local max_parallel="${MAX_PARALLEL_AOIS:-1}"
  local failed=0
  local -a pids=()
  local -a names=()
  local aoi pid index

  if [[ ! -d "$MASTER_DIR" ]]; then
    echo "Prepared master directory not found: $MASTER_DIR" >&2
    echo "Run step 03 first." >&2
    return 2
  fi

  echo "AOIs: ${AOIS[*]}"
  echo "Parallel AOIs for this step: $max_parallel"
  for aoi in "${AOIS[@]}"; do
    run_one_aoi_step "$number" "$aoi" &
    pid=$!
    pids+=("$pid")
    names+=("$aoi")
    if (( ${#pids[@]} >= max_parallel )); then
      for index in "${!pids[@]}"; do
        if ! wait "${pids[$index]}"; then
          echo "AOI failed: ${names[$index]}" >&2
          failed=1
        fi
      done
      pids=()
      names=()
      if (( failed != 0 )); then
        return 1
      fi
    fi
  done
  for index in "${!pids[@]}"; do
    if ! wait "${pids[$index]}"; then
      echo "AOI failed: ${names[$index]}" >&2
      failed=1
    fi
  done
  return "$failed"
}

run_step() {
  local number="$1"
  local padded
  printf -v padded '%02d' "$number"
  echo
  echo "================================================================"
  echo "STEP $padded: ${STEP_FILES[$number]}"
  echo "================================================================"
  if (( number <= 3 || number == 17 )); then
    run_global_step "$number"
  else
    run_scientific_step "$number"
  fi
}

printf 'Selected AOIs (%d): %s\n' "${#AOIS[@]}" "${AOIS[*]}"
printf 'Running steps %02d through %02d\n' "$FIRST_NUMBER" "$LAST_NUMBER"
for ((step=FIRST_NUMBER; step<=LAST_NUMBER; step++)); do
  run_step "$step"
done

echo
echo "Workflow completed successfully."
