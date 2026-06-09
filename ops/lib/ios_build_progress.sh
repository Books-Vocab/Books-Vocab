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
#     Starts a background subshell that prints a progress line to stdout every
#     ~8s when new compile events appear, or a heartbeat every 30s during
#     quiet phases (linking, code-signing, resource copy).
#     Returns the background PID.  Caller must kill it when xcodebuild exits:
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
  grep -cE '^(SwiftCompile|CompileC) ' "$1" 2>/dev/null || echo 0
}

start_build_monitor() {
  local log="$1" baseline_file="$2" prefix="$3" start_s="$4"
  (
    local baseline count last_count last_print now elapsed pct last_file target phase

    baseline=0
    if [[ -f "$baseline_file" ]]; then
      baseline=$(cat "$baseline_file" 2>/dev/null | tr -d '[:space:]')
      [[ "$baseline" =~ ^[0-9]+$ ]] || baseline=0
    fi
    last_count=0
    last_print=$start_s

    while true; do
      sleep 5
      [[ -f "$log" ]] || continue

      count=$(count_compile_events "$log")
      now=$(date +%s)
      elapsed=$(( now - start_s ))

      if [[ "$count" -gt "$last_count" ]]; then
        # Extract the last compiled filename and current target.
        # SwiftCompile format: SwiftCompile normal arm64 [Compiling\ name.swift] /abs/path.swift (in target 'T' ...)
        last_file=$(grep -E '^SwiftCompile ' "$log" 2>/dev/null | tail -1 \
          | sed "s/.*\/\([^\/]*\.swift\) .*/\1/; s/ *(in target.*//" | tr -d '\\' | xargs 2>/dev/null || true)
        target=$(grep -E '^(SwiftCompile|CompileC) ' "$log" 2>/dev/null | tail -1 \
          | sed -n "s/.*in target '\\([^']*\\)'.*/\\1/p")

        if [[ "$baseline" -gt 0 ]]; then
          pct=$(( count * 100 / baseline ))
          # Incremental builds compile fewer files than the stored (full-build)
          # baseline → cap at 99% so agents don't see a confusing "103%".
          [[ $pct -gt 99 ]] && pct=99
          printf '%s ▸ compile %d/%d (~%d%%, %ds)' "$prefix" "$count" "$baseline" "$pct" "$elapsed"
        else
          printf '%s ▸ compile %d events (%ds; no baseline yet — %% shown after first successful build)' \
            "$prefix" "$count" "$elapsed"
        fi
        [[ -n "$target" ]] && printf ' target=%s' "$target"
        [[ -n "$last_file" ]] && printf ' — %s' "$last_file"
        printf '\n'

        last_count=$count
        last_print=$now

      elif [[ $(( now - last_print )) -ge 30 ]]; then
        # Heartbeat covers Ld / CodeSign / CpResource phases that emit no compile events.
        phase=""
        grep -qE '^Ld '      "$log" 2>/dev/null && phase=" (linking)"
        grep -qE '^CodeSign ' "$log" 2>/dev/null && phase=" (code-signing)"
        last_line=$(tail -1 "$log" 2>/dev/null \
          | sed 's|/[^ ]*/||g; s/(in target[^)]*)//g' | cut -c1-100 || true)
        printf '%s ▸ xcodebuild running %ds%s — last: %s\n' \
          "$prefix" "$elapsed" "$phase" "${last_line:-waiting...}"
        last_print=$now
      fi
    done
  ) &
  echo $!
}
