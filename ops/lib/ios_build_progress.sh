#!/usr/bin/env bash
# ios_build_progress.sh — shared compile-progress monitor for ios_build.sh / ios_test.sh
#
# Provides two functions:
#
#   count_compile_events LOG
#     Returns the number of SwiftCompile+CompileC lines in LOG — one line per
#     compiled file that xcodebuild emits when NOT using -quiet.
#
#   start_build_monitor LOG BASELINE_FILE PREFIX START_EPOCH_SECS
#     Starts a background subshell that prints a progress line to stderr every
#     ~8s when new compile events appear, or a heartbeat every 30s during
#     quiet phases (linking, code-signing, resource copy).
#     Returns the background PID on stdout. Caller must kill it when xcodebuild exits:
#
#       MONITOR_PID=$(start_build_monitor "$LOG" "$BASELINE" "[tag]" "$(date +%s)")
#       xcodebuild ... >"$LOG" 2>&1
#       EXIT=$?
#       kill "$MONITOR_PID" 2>/dev/null || true; wait "$MONITOR_PID" 2>/dev/null || true
#
#     Baseline mechanics:
#       • First run: no baseline file → raw counts, no %.
#       • After a successful build: caller writes the final count to BASELINE_FILE.
#       • Future runs: count / baseline → ~%.  Incremental builds compile fewer
#         files than a full build so % is capped at 99 to avoid confusing "103%".
#
#     SwiftCompile line format (xcodebuild without -quiet):
#       SwiftCompile normal arm64 [Compiling\ name.swift] /abs/path.swift (in target 'T' from project 'P')

count_compile_events() {
  local count
  count=$(grep -cE '^(SwiftCompile|CompileC) ' "$1" 2>/dev/null || true)
  [[ "$count" =~ ^[0-9]+$ ]] || count=0
  printf '%s\n' "$count"
}

# Tick cadence constants (seconds).
# TICK_INTERVAL   — how often to print *something* (keep-alive for agents)
# DETAIL_INTERVAL — how often to include filename + target in the tick line
TICK_INTERVAL=3
DETAIL_INTERVAL=20

start_build_monitor() {
  local log="$1" baseline_file="$2" prefix="$3" start_s="$4"
  (
    local baseline count last_count now elapsed pct cur_phase last_file target
    local last_tick last_detail

    baseline=0
    if [[ -f "$baseline_file" ]]; then
      baseline=$(cat "$baseline_file" 2>/dev/null | tr -d '[:space:]')
      [[ "$baseline" =~ ^[0-9]+$ ]] || baseline=0
    fi
    last_count=0
    last_tick=$start_s
    last_detail=$start_s

    while true; do
      sleep 2
      [[ -f "$log" ]] || continue

      count=$(count_compile_events "$log")
      now=$(date +%s)
      elapsed=$(( now - start_s ))

      # Phase detection: compile while new events appear; switch to link/sign
      # once events stop and the corresponding log lines are present.
      if [[ "$count" -gt "$last_count" ]]; then
        cur_phase="compile"
      elif grep -qE '^CodeSign ' "$log" 2>/dev/null; then
        cur_phase="code-signing"
      elif grep -qE '^Ld '       "$log" 2>/dev/null; then
        cur_phase="linking"
      else
        cur_phase="compile"   # early startup — events not yet in log
      fi

      if [[ $(( now - last_tick )) -ge $TICK_INTERVAL ]]; then

        if [[ "$cur_phase" == "compile" ]]; then
          # Compute %
          if [[ "$baseline" -gt 0 ]]; then
            pct=$(( count * 100 / baseline ))
            [[ $pct -gt 99 ]] && pct=99   # incremental builds compile fewer files
          else
            pct=-1
          fi

          if [[ $(( now - last_detail )) -ge $DETAIL_INTERVAL ]]; then
            # Detail tick every 20s: add target + filename for context
            last_file=$(grep -E '^SwiftCompile ' "$log" 2>/dev/null | tail -1 \
              | sed "s/.*\/\([^\/]*\.swift\) .*/\1/; s/ *(in target.*//" | tr -d '\\' | xargs 2>/dev/null || true)
            target=$(grep -E '^(SwiftCompile|CompileC) ' "$log" 2>/dev/null | tail -1 \
              | sed -n "s/.*in target '\\([^']*\\)'.*/\\1/p")
            if [[ $pct -ge 0 ]]; then
              printf '%s ▸ ~%d%% (%d/%d, %ds)' "$prefix" "$pct" "$count" "$baseline" "$elapsed"
            else
              printf '%s ▸ %d events (%ds, no baseline yet)' "$prefix" "$count" "$elapsed"
            fi
            [[ -n "$target" ]]    && printf ' target=%s' "$target"
            [[ -n "$last_file" ]] && printf ' — %s' "$last_file"
            printf '\n'
            last_detail=$now
          else
            # Short tick every 3s: just % + elapsed
            if [[ $pct -ge 0 ]]; then
              printf '%s ▸ ~%d%% %ds\n' "$prefix" "$pct" "$elapsed"
            else
              printf '%s ▸ %d events %ds\n' "$prefix" "$count" "$elapsed"
            fi
          fi
          last_count=$count

        else
          # Link / code-signing / resources: no compile events, just show phase
          printf '%s ~ %s %ds\n' "$prefix" "$cur_phase" "$elapsed"
        fi

        last_tick=$now
      fi
    done
  ) >&2 &
  echo $!
}

# start_tick_monitor LOG PREFIX START_EPOCH_SECS
#   Generic keep-alive monitor for long commands that emit NO compile events —
#   xcodebuild archive/export, xcrun altool upload, test execution. Prints:
#     Tick   (every 3s):  short dots so an agent sees the process is alive
#                           [prefix] ··· 12s
#     Detail (every 20s): the last meaningful log line for context
#                           [prefix] 40s — Signing BooksAndVocab.app
#   Same lifecycle contract as start_build_monitor: caller kills+waits the PID.
#   If LOG is empty/absent (altool writes nothing to a file), pass /dev/null and
#   only the elapsed-time tick is shown — still a valid keep-alive signal.
start_tick_monitor() {
  local log="$1" prefix="$2" start_s="$3"
  (
    local now elapsed last_tick last_detail last_line
    last_tick=$start_s
    last_detail=$start_s

    while true; do
      sleep 2
      now=$(date +%s)
      elapsed=$(( now - start_s ))
      [[ $(( now - last_tick )) -ge $TICK_INTERVAL ]] || continue

      if [[ $(( now - last_detail )) -ge $DETAIL_INTERVAL && -s "$log" ]]; then
        # Detail tick: strip absolute paths and target suffixes for a clean line.
        last_line=$(tail -1 "$log" 2>/dev/null \
          | sed 's|/[^ ]*/||g; s/(in target[^)]*)//g' | cut -c1-100 || true)
        printf '%s %ds — %s\n' "$prefix" "$elapsed" "${last_line:-running...}"
        last_detail=$now
      else
        printf '%s ··· %ds\n' "$prefix" "$elapsed"
      fi
      last_tick=$now
    done
  ) >&2 &
  echo $!
}
