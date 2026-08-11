#!/usr/bin/env bash
# docs_lint.sh — docs gate / audit / registry checks
#
# 邏輯:
#   1. 預設 gate 模式只掃本分支/工作樹變更的 docs,避免既有 doc debt 阻塞日常 PR
#   2. audit/all 模式才對 docs/**/*.md(除了 assets/legal)做全 repo freshness 盤點
#   3. registry 模式驗證 docs/registry.yml 控制平面(path/kind/generator 基本有效性)
#   4. gate 模式透過 docs_impact.py 輸出 registry impact hints(提示用,不作為 fail 條件)
#   5. 對選中的 doc 解析 doc-meta frontmatter,檢查 tier / authority / update_trigger / scope / verified_against
#   6. audit 模式對非 archive doc 計算 verified_against..HEAD 期間有多少 commit 動過 scope 路徑
#      - 超過 STALE_THRESHOLD(預設 30)→ WARN
#      - verified_against 不是有效 sha(且不是 frozen)→ ERROR
#   7. verified_against 必須 reachable from HEAD(merge-base --is-ancestor);
#      orphan(rebase 後舊 hash)在 gate/files 模式 ERROR,audit 模式降 WARN(不翻既有 debt)
#   8. 第二層:verified_against 是否 reachable from $ORIGIN_REF(預設 origin/main)。
#      HEAD 可達 != origin 可達——本 repo 拓樸是本地 main 為主幹、刻意超前 origin,
#      所以錨在分支自身 commit 過得了第 7 條,卻正是 cutover rebase 會 orphan 掉的那種。
#      這條在 gate/files/audit 三種模式一律 **WARN 不 ERROR**(worktree pre-cutover 錨在
#      自身 commit 是合法情境,升 ERROR 會把整條 worktree 流程擋死),並印一個可照抄的
#      替代 sha。$ORIGIN_REF 不存在(未 fetch 的 clone)→ 整段跳過。
#      WARN 會以 EXIT_WARN(3) 回報；--strict 僅保留為相容旗標，不改變分類。
#
# 用法:
#   ops/docs_lint.sh                 # gate: registry + changed docs
#   ops/docs_lint.sh --changed       # 只掃本分支/工作樹變更的 docs
#   ops/docs_lint.sh --since <rev>   # 只掃 <rev>..HEAD + 工作樹變更的 docs
#   ops/docs_lint.sh --files <docs...>
#   ops/docs_lint.sh <docs/...md> [<docs/...md> ...]  # 相當於 --files
#   ops/docs_lint.sh --registry      # 只驗證 docs/registry.yml
#   ops/docs_lint.sh --audit|--all   # 全 repo audit(可暴露既有 debt)
#   ops/docs_lint.sh --reanchor [--commit]  # dry-run/落地 orphan verified_against 映射
#   ops/docs_lint.sh --reanchor --search-depth <n>  # 限制 patch-id 搜尋視窗
#   ops/docs_lint.sh --strict        # 保留相容旗標；WARN 一律 exit 3
#   STALE_THRESHOLD=10 ops/docs_lint.sh
#   KG_DOCS_LINT_ORIGIN_REF=origin/prod ops/docs_lint.sh   # 換 anchor 可達性的參考 ref
#
# Exit code:
#   0 — 全部 OK
#   1 — lint/tool execution failure
#   2 — 有 ERROR(欄位缺失 / verified_against 無效)
#   3 — 有 WARN(無 ERROR)
#   64 — command-line usage error
#
# 相容 bash 3.2(macOS 預設),不使用 mapfile / readarray。

set -euo pipefail

EXIT_OK=0
EXIT_TOOL_ERROR=1
EXIT_BLOCK=2
EXIT_WARN=3
EXIT_USAGE=64

# 檢查呼叫者所在 checkout。linked worktree 與 main 共用 object store,但工作樹檔案各自獨立；
# 強制 cd 回 main 會漏掉 PR worktree 內尚未 commit 的 docs/registry 變更。
cd "$(git rev-parse --show-toplevel)"

STALE_THRESHOLD="${STALE_THRESHOLD:-30}"
# anchor 可達性的第二個參考點。預設 origin/main;可覆寫成別的 ref(例如部署機的
# origin/prod),或在沒有 remote 的環境指向任何存在的 ref。ref 不存在 → 該檢查整段跳過。
ORIGIN_REF="${KG_DOCS_LINT_ORIGIN_REF:-origin/main}"
STRICT=0
MODE="gate"
SINCE_REV=""
FILE_ARGS=()
GATE_BASE=""
REANCHOR_COMMIT=0
REANCHOR_SEARCH_DEPTH="${KG_DOCS_LINT_REANCHOR_SEARCH_DEPTH:-2000}"
REANCHOR_SEARCH_DEPTH_SET=0

usage() {
  # 印檔頭註解:跳過 shebang,一路印到第一行非註解為止。**不要改回寫死行號**——
  # 前身是 `sed -n '2,24p'`,而註解區早已長到第 31 行,--help 於是靜靜漏掉
  # 「Exit code」與 STALE_THRESHOLD 那幾行。行號寫在別處、內容長在這裡,兩邊必然漂移。
  awk 'NR == 1 { next } /^#/ { sub(/^# ?/, ""); print; next } { exit }' "$0"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --strict)
      STRICT=1
      shift
      ;;
    --changed)
      MODE="gate"
      shift
      ;;
    --since)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --since" >&2
        exit "$EXIT_USAGE"
      fi
      MODE="gate"
      SINCE_REV="$2"
      shift 2
      ;;
    --files)
      MODE="files"
      shift
      while [ "$#" -gt 0 ]; do
        case "$1" in
          --*) break ;;
          *) FILE_ARGS+=("$1"); shift ;;
        esac
      done
      ;;
    --registry)
      MODE="registry"
      shift
      ;;
    --audit|--all)
      MODE="audit"
      shift
      ;;
    --reanchor)
      MODE="reanchor"
      shift
      ;;
    --commit)
      REANCHOR_COMMIT=1
      shift
      ;;
    --search-depth)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --search-depth" >&2
        exit "$EXIT_USAGE"
      fi
      REANCHOR_SEARCH_DEPTH="$2"
      REANCHOR_SEARCH_DEPTH_SET=1
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ "${1#-}" != "$1" ]; then
        echo "Unknown arg: $1" >&2
        echo "提示: 若要指定 doc 路徑,請改用 --files: ops/docs_lint.sh --files docs/<path>.md ..." >&2
        echo "      或直接傳 doc 路徑: ops/docs_lint.sh docs/<path>.md ..." >&2
        exit "$EXIT_USAGE"
      fi
      MODE="files"
      FILE_ARGS+=("$1")
      shift
      while [ "$#" -gt 0 ]; do
        case "$1" in
          --*) break ;;
          *) FILE_ARGS+=("$1"); shift ;;
        esac
      done
      ;;
  esac
done

if [ "$REANCHOR_COMMIT" -eq 1 ] && [ "$MODE" != "reanchor" ]; then
  echo "ERROR --commit 只適用於 --reanchor" >&2
  exit "$EXIT_USAGE"
fi

if [ "$MODE" != "reanchor" ] && [ "$REANCHOR_SEARCH_DEPTH_SET" -eq 1 ]; then
  echo "ERROR --search-depth 只適用於 --reanchor" >&2
  exit "$EXIT_USAGE"
fi

if [ "$MODE" = "reanchor" ]; then
  case "$REANCHOR_SEARCH_DEPTH" in
    ''|*[!0-9]*)
      echo "ERROR --search-depth 必須是正整數: $REANCHOR_SEARCH_DEPTH" >&2
      exit "$EXIT_USAGE"
      ;;
    0)
      echo "ERROR --search-depth 必須大於 0" >&2
      exit "$EXIT_USAGE"
      ;;
  esac
fi

REQUIRED_FIELDS="tier authority update_trigger scope verified_against"
VALID_TIERS="policy sop reference snapshot runbook archive assets"
REGISTRY_KINDS="contract generated reference sop policy decision guide snapshot runbook archive assets"

errors=0
warnings=0
ok=0
IMPACT_HINTS_EMITTED=0

emit_generated_diff() {
  local id="$1" path="$2" generator="$3"
  local expected_tmp diff_tmp total_lines max_lines=40
  expected_tmp="$(mktemp "${TMPDIR:-/tmp}/kg_docs_expected.XXXXXX")"
  diff_tmp="$(mktemp "${TMPDIR:-/tmp}/kg_docs_diff.XXXXXX")"

  # `check` is arbitrary shell, so do not pretend it can produce a diff. Only
  # use the registry's generator when it is a zero-argument command that
  # successfully emits a non-empty expected document; otherwise retain the
  # existing error as the honest fallback.
  if ! sh -c "$generator" </dev/null >"$expected_tmp" 2>/dev/null ||
     [ ! -s "$expected_tmp" ] || [ ! -f "$path" ]; then
    rm -f "$expected_tmp" "$diff_tmp"
    return 0
  fi
  if diff -u "$path" "$expected_tmp" >"$diff_tmp" 2>/dev/null; then
    rm -f "$expected_tmp" "$diff_tmp"
    return 0
  fi

  total_lines="$(wc -l < "$diff_tmp" | tr -d ' ')"
  echo "    drift diff ($id):"
  sed -n "1,${max_lines}p" "$diff_tmp"
  if [ "$total_lines" -gt "$max_lines" ]; then
    echo "    ... 還有 $((total_lines - max_lines)) 行差異未顯示"
  fi
  rm -f "$expected_tmp" "$diff_tmp"
  return 0
}

validate_registry() {
  reg="docs/registry.yml"
  if [ ! -f "$reg" ]; then
    echo "ERROR registry — missing $reg"
    errors=$((errors+1))
    return
  fi

  entries_tmp="$(mktemp "${TMPDIR:-/tmp}/kg_docs_registry.XXXXXX")"
  awk '
    function flush() {
      if (id != "") {
        print "ENTRY\t" id "\t" path "\t" kind "\t" generator "\t" check
      }
    }
    /^  - id:[[:space:]]*/ {
      flush()
      id=$0
      sub(/^  - id:[[:space:]]*/, "", id)
      path=""
      kind=""
      generator=""
      check=""
      next
    }
    id != "" && /^    path:[[:space:]]*/ {
      path=$0
      sub(/^    path:[[:space:]]*/, "", path)
      next
    }
    id != "" && /^    kind:[[:space:]]*/ {
      kind=$0
      sub(/^    kind:[[:space:]]*/, "", kind)
      next
    }
    id != "" && /^    generator:[[:space:]]*/ {
      generator=$0
      sub(/^    generator:[[:space:]]*/, "", generator)
      next
    }
    id != "" && /^    check:[[:space:]]*/ {
      check=$0
      sub(/^    check:[[:space:]]*/, "", check)
      next
    }
    END { flush() }
  ' "$reg" > "$entries_tmp"

  reg_bad=0
  entry_count=0
  while IFS="$(printf '\t')" read -r tag id path kind generator check; do
    [ "$tag" = "ENTRY" ] || continue
    entry_count=$((entry_count+1))
    if [ -z "$id" ] || [ -z "$path" ] || [ -z "$kind" ]; then
      echo "ERROR registry — entry 缺 id/path/kind: id=$id path=$path kind=$kind"
      reg_bad=$((reg_bad+1))
      continue
    fi
    if ! echo " $REGISTRY_KINDS " | grep -q " $kind "; then
      echo "ERROR registry — $id 非法 kind: $kind(允許: $REGISTRY_KINDS)"
      reg_bad=$((reg_bad+1))
    fi
    if [ ! -f "$path" ]; then
      echo "ERROR registry — $id path 不存在: $path"
      reg_bad=$((reg_bad+1))
    fi
    if [ "$kind" = "generated" ]; then
      if [ -z "$generator" ]; then
        echo "ERROR registry — $id kind=generated 但缺 generator"
        reg_bad=$((reg_bad+1))
      elif [ ! -f "$generator" ]; then
        echo "ERROR registry — $id generator 不存在: $generator"
        reg_bad=$((reg_bad+1))
      fi
      # generator: 只證明「有人宣稱這檔是產生出來的」。真正可機器檢查的關係是
      # 產物 == generator 輸出，那個關係在此之前從來沒被評估過——一份 generated
      # 文檔可以腐爛到面目全非而這裡照樣回綠（IMP-20260805-462d28）。
      # 缺 check: 直接 ERROR，讓這個洞由構造關上，而不是靠下一個人記得。
      if [ -z "$check" ]; then
        echo "ERROR registry — $id kind=generated 但缺 check(產物等值檢查命令)"
        reg_bad=$((reg_bad+1))
      # 「非空字串 + 今天 exit 0」只證明有人打了字。`check: true` 通過；把鄰居 entry 的
      # check 複製過來也通過——被驗的會是別人的產物或什麼都不是，而 gate 照樣回綠
      # （IMP-20260805-462d28 review D2）。要求 check 字串裡出現本 entry 的 path，把
      # 「這條命令在檢查哪個檔」變成結構上可讀、可比對的事實。附帶效果：複製貼上的 check
      # 帶著別人的 path 必然被擋，所以不需要另外驗「check 字串不得重複」。
      # 這是**必要非充分**條件——它擋不住「有指名 path 但無條件回 0」的裝飾品；那個失效
      # 模式由 ops/tests/test_docs_lint_generated_check.sh case 7（逐筆弄髒真產物、要求
      # docs_lint 具名轉紅）負責。兩者缺一，這個 gate 就退回靠信仰。
      elif ! printf '%s' "$check" | grep -qF -- "$path"; then
        echo "ERROR registry — $id check 未指名 path: ${path}（check=${check}）"
        echo "    修法: 把 $path 當參數/比對目標寫進 check 命令，否則無從得知它在驗哪個檔"
        reg_bad=$((reg_bad+1))
      # `</dev/null` 不是噪音，不要刪：這個 while 迴圈的 stdin 是 ${entries_tmp}（見迴圈尾），
      # 任何繼承 stdin 的子命令都會吃掉尚未讀取的 registry entry。症狀是後面幾筆 entry
      # 神秘消失、entry_count 少掉，而 rc 仍是 0——正是本 gate 存在要擋的那類錯誤。
      elif ! sh -c "$check" </dev/null >/dev/null 2>&1; then
        echo "ERROR registry — $id 產物與 generator 輸出不一致: $path(跑 $check 看差異)"
        emit_generated_diff "$id" "$path" "$generator"
        reg_bad=$((reg_bad+1))
      fi
    fi
  done < "$entries_tmp"
  rm -f "$entries_tmp"

  if [ "$entry_count" -eq 0 ]; then
    echo "ERROR registry — no document entries"
    errors=$((errors+1))
    return
  fi
  if [ "$reg_bad" -gt 0 ]; then
    echo "ERROR registry — $reg_bad invalid entr$( [ "$reg_bad" -eq 1 ] && echo "y" || echo "ies" )"
    errors=$((errors+1))
    return
  fi
  echo "REGISTRY OK: $entry_count documents"
  ok=$((ok+1))
}

filter_docs() {
  awk '
    /\.md$/ &&
    $0 !~ /^docs\/assets\// &&
    $0 !~ /^docs\/legal\// &&
    $0 ~ /^docs\// { print }
  ' | sort -u
}

all_docs() {
  find docs -type f -name "*.md" \
    ! -path "docs/assets/*" \
    ! -path "docs/legal/*" | sort
}

default_changed_base() {
  if [ -n "${DOCS_LINT_BASE:-}" ]; then
    printf '%s\n' "$DOCS_LINT_BASE"
    return
  fi
  if git rev-parse --verify origin/HEAD >/dev/null 2>&1; then
    git merge-base origin/HEAD HEAD
    return
  fi
  git rev-parse HEAD
}

changed_docs() {
  base="${GATE_BASE:-${SINCE_REV:-$(default_changed_base)}}"
  if ! git rev-parse --verify "$base^{commit}" >/dev/null 2>&1; then
    echo "ERROR --since/changed base 不是有效 commit: $base" >&2
    exit "$EXIT_USAGE"
  fi
  {
    git diff --name-only --diff-filter=ACMR "$base..HEAD" -- docs
    git diff --name-only --diff-filter=ACMR --cached -- docs
    git diff --name-only --diff-filter=ACMR -- docs
    git ls-files --others --exclude-standard docs
  } | filter_docs
}

emit_impact_hints() {
  [ "$MODE" = "gate" ] || return
  [ -n "$GATE_BASE" ] || return

  if [ ! -x "ops/docs_impact.py" ]; then
    echo "WARN docs_lint: ops/docs_impact.py 不存在或不可執行,略過 registry impact hints"
    return
  fi

  impact_out="$(./ops/docs_impact.py --since "$GATE_BASE" 2>&1)" || {
    echo "WARN docs_lint: docs_impact.py 執行失敗,略過 registry impact hints"
    echo "$impact_out"
    return
  }

  if echo "$impact_out" | grep -q '^IMPACT '; then
    IMPACT_HINTS_EMITTED=1
    echo "docs_lint: current checkout impact hints (warn only)"
    echo "$impact_out" | sed -n 's/^IMPACT /WARN impact — /p'
    echo "docs_lint: inspect suppression with ./ops/docs_impact.py --since $GATE_BASE --explain"
    echo "docs_lint: frontmatter checks below only cover docs changed in the current checkout; use the impact hints above to judge non-doc changes"
    echo "docs_lint: next-step heuristic -> impact hints are sync candidates, not auto-required; STALE means freshness risk, not automatic doc-sync for this change"
  fi
}

files_docs() {
  if [ "${#FILE_ARGS[@]}" -eq 0 ]; then
    echo "ERROR --files 需要至少一個 docs/*.md 路徑" >&2
    exit "$EXIT_USAGE"
  fi
  for f in "${FILE_ARGS[@]}"; do
    case "$f" in
      docs/*.md) ;;
      *)
        echo "ERROR --files 只接受 docs/*.md 路徑: $f" >&2
        exit "$EXIT_USAGE"
        ;;
    esac
    case "$f" in
      docs/assets/*|docs/legal/*)
        echo "ERROR --files 不掃描 assets/legal doc: $f" >&2
        exit "$EXIT_USAGE"
        ;;
    esac
    if [ ! -f "$f" ]; then
      echo "ERROR --files 路徑不存在: $f" >&2
      exit "$EXIT_USAGE"
    fi
  done
  printf '%s\n' "${FILE_ARGS[@]}" | sort -u
}

tracked_docs() {
  git ls-files --cached -- 'docs/*.md' 'docs/**/*.md' | filter_docs
}

doc_meta_value() {
  file="$1"
  field="$2"
  awk -v wanted="$field" '
    /<!-- doc-meta/ { in_meta=1 }
    in_meta && $0 ~ ("^" wanted ":") {
      value=$0
      sub("^[^:]*:[[:space:]]*", "", value)
      sub(/^"/, "", value)
      sub(/"$/, "", value)
      print value
      exit
    }
    in_meta && /-->/ { exit }
  ' "$file"
}

validate_feature_boundary_loc() {
  local file="$1"
  local header_hits=""
  local row_hits=""
  local grep_rc=0
  case "$file" in
    docs/reference/feature_boundary/*.md) ;;
    *) return 0 ;;
  esac

  if header_hits=$(grep -nE '^\|[[:space:]]*檔案[[:space:]]*\|[[:space:]]*行數[[:space:]]*\|' "$file"); then
    :
  else
    grep_rc=$?
    if [ "$grep_rc" -ne 1 ]; then
      echo "ERROR $file — feature-boundary 行數規則無法讀取文件(rc=$grep_rc)"
      errors=$((errors+1))
      return 1
    fi
  fi
  if row_hits=$(grep -nE '^\|[[:space:]]*`[^`]+\.swift`[[:space:]]*\|[[:space:]]*~?[0-9]+[[:space:]]*\|' "$file"); then
    :
  else
    grep_rc=$?
    if [ "$grep_rc" -ne 1 ]; then
      echo "ERROR $file — feature-boundary 行數規則無法讀取文件(rc=$grep_rc)"
      errors=$((errors+1))
      return 1
    fi
  fi

  if [ -z "$header_hits" ] && [ -z "$row_hits" ]; then
    return 0
  fi

  echo "ERROR $file — feature-boundary 文件禁止手寫行數欄；保留檔案路徑與責任描述即可"
  if [ -n "$header_hits" ]; then
    echo "$header_hits" | sed 's/^/    /'
  fi
  if [ -n "$row_hits" ]; then
    echo "$row_hits" | sed 's/^/    /'
  fi
  errors=$((errors+1))
  return 1
}

reanchor_patch_id() {
  # Match the existing backlog.py reanchor contract: whole-commit patch-id,
  # so a conflict-resolved or otherwise partial rewrite is never guessed.
  git show --no-ext-diff "$1" 2>/dev/null \
    | git patch-id --stable 2>/dev/null \
    | sed -n '1s/[[:space:]].*//p'
}

reanchor_rewrite_anchor() {
  file="$1"
  old="$2"
  new="$3"
  tmp="$(mktemp "${file}.reanchor.XXXXXX")" || return 1
  if ! awk -v old="$old" -v new="$new" '
    /^verified_against:/ && !replaced {
      value=$0
      sub(/^verified_against:[[:space:]]*/, "", value)
      sub(/^"/, "", value)
      sub(/"$/, "", value)
      if (value == old) {
        line=$0
        sub(old, new, line)
        print line
        replaced=1
        next
      }
    }
    { print }
  ' "$file" > "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  file_mode="$(stat -f '%Lp' "$file" 2>/dev/null || true)"
  if [ -z "$file_mode" ]; then
    file_mode="$(stat -c '%a' "$file" 2>/dev/null || true)"
  fi
  if [ -n "$file_mode" ] && ! chmod "$file_mode" "$tmp"; then
    rm -f "$tmp"
    return 1
  fi
  if ! mv "$tmp" "$file"; then
    rm -f "$tmp"
    return 1
  fi
}

run_reanchor() {
  REANCHOR_TMPDIR="$(mktemp -d "${TMPDIR:-/tmp}/kg_docs_reanchor.XXXXXX")"
  trap 'if [ -n "${REANCHOR_TMPDIR:-}" ]; then rm -rf "$REANCHOR_TMPDIR"; fi' EXIT

  docs_tmp="$REANCHOR_TMPDIR/docs"
  orphans_tmp="$REANCHOR_TMPDIR/orphans"
  candidates_tmp="$REANCHOR_TMPDIR/candidates"
  index_tmp="$REANCHOR_TMPDIR/index"
  moves_tmp="$REANCHOR_TMPDIR/moves"
  : > "$orphans_tmp"
  : > "$moves_tmp"
  tracked_docs > "$docs_tmp"

  orphan_count=0
  while IFS= read -r file; do
    [ -n "$file" ] || continue
    verified="$(doc_meta_value "$file" verified_against)"
    case "$verified" in
      ''|*[!0-9a-f]*) continue ;;
    esac
    verified_length="${#verified}"
    [ "$verified_length" -ge 7 ] && [ "$verified_length" -le 40 ] || continue

    verified_sha=""
    if ! verified_sha="$(git rev-parse --verify --quiet "${verified}^{commit}" 2>/dev/null)"; then
      continue
    fi
    if git merge-base --is-ancestor "$verified_sha" HEAD 2>/dev/null; then
      continue
    fi
    printf '%s\t%s\t%s\n' "$file" "$verified" "$verified_sha" >> "$orphans_tmp"
    orphan_count=$((orphan_count+1))
  done < "$docs_tmp"

  if [ "$orphan_count" -eq 0 ]; then
    echo "reanchor: 0 orphaned verified_against anchors"
    return 0
  fi

  if ! git rev-list --max-count="$REANCHOR_SEARCH_DEPTH" HEAD > "$candidates_tmp"; then
    echo "ERROR reanchor — 無法讀取 HEAD commit 搜尋視窗" >&2
    return 1
  fi

  : > "$index_tmp"
  indexed_count=0
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    candidate_pid="$(reanchor_patch_id "$candidate" || true)"
    if [ -n "$candidate_pid" ]; then
      printf '%s\t%s\n' "$candidate_pid" "$candidate" >> "$index_tmp"
      indexed_count=$((indexed_count+1))
    fi
  done < "$candidates_tmp"

  mapped_count=0
  unmatched_count=0
  while IFS="$(printf '\t')" read -r file old old_sha; do
    [ -n "$file" ] || continue
    old_pid="$(reanchor_patch_id "$old_sha" || true)"
    hits=""
    if [ -n "$old_pid" ]; then
      hits="$(awk -F '\t' -v wanted="$old_pid" '$1 == wanted { print $2 }' "$index_tmp")"
    fi
    hit_count="$(printf '%s\n' "$hits" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
    if [ "$hit_count" -eq 1 ]; then
      new="$(printf '%s\n' "$hits" | sed -n '1p' | xargs git rev-parse --short=9)"
      echo "$file: $old -> $new (patch-id match)"
      printf '%s\t%s\t%s\n' "$file" "$old" "$new" >> "$moves_tmp"
      mapped_count=$((mapped_count+1))
    else
      echo "ERROR $file — verified_against $old: patch-id 無唯一匹配(${hit_count} 個候選),不猜" >&2
      unmatched_count=$((unmatched_count+1))
    fi
  done < "$orphans_tmp"

  landed_count=0
  if [ "$REANCHOR_COMMIT" -eq 1 ]; then
    while IFS="$(printf '\t')" read -r file old new; do
      [ -n "$file" ] || continue
      if ! reanchor_rewrite_anchor "$file" "$old" "$new"; then
        echo "ERROR $file — reanchor --commit 無法原子改寫 verified_against" >&2
        return 1
      fi
      landed_count=$((landed_count+1))
    done < "$moves_tmp"
    echo "reanchor: landed $landed_count mapping(s) (--commit)"
  else
    echo "reanchor: dry-run; pass --commit to land $mapped_count mapping(s)"
  fi

  echo "reanchor: orphaned=$orphan_count indexed=$indexed_count mapped=$mapped_count unmatched=$unmatched_count search-depth=$REANCHOR_SEARCH_DEPTH"
  if [ "$unmatched_count" -gt 0 ]; then
    return "$EXIT_BLOCK"
  fi
  return "$EXIT_OK"
}

echo "docs_lint: mode=$MODE"
validate_registry

if [ "$MODE" = "reanchor" ]; then
  if run_reanchor; then
    reanchor_rc=0
  else
    reanchor_rc=$?
  fi
  [ "$errors" -gt 0 ] && exit "$EXIT_BLOCK"
  exit "$reanchor_rc"
fi

if [ "$MODE" = "registry" ]; then
  echo ""
  echo "─────────────────────────────────────"
  echo "OK:    $ok"
  echo "WARN:  $warnings"
  echo "ERROR: $errors"
  echo "─────────────────────────────────────"
  [ "$errors" -gt 0 ] && exit "$EXIT_BLOCK"
  exit "$EXIT_OK"
fi

if [ "$MODE" = "gate" ]; then
  GATE_BASE="${SINCE_REV:-$(default_changed_base)}"
  if ! git rev-parse --verify "$GATE_BASE^{commit}" >/dev/null 2>&1; then
    echo "ERROR --since/changed base 不是有效 commit: $GATE_BASE" >&2
    exit "$EXIT_USAGE"
  fi
  emit_impact_hints
fi

case "$MODE" in
  audit) DOCS=$(all_docs) ;;
  gate) DOCS=$(changed_docs) ;;
  files) DOCS=$(files_docs) ;;
    *) echo "internal error: unknown MODE=$MODE" >&2; exit "$EXIT_TOOL_ERROR" ;;
esac

if [ -z "$DOCS" ]; then
  echo "docs_lint: no docs selected (mode=$MODE)"
  if [ "$MODE" = "gate" ] && [ "$IMPACT_HINTS_EMITTED" -eq 1 ]; then
    echo "docs_lint: only non-doc files changed, so no doc frontmatter was linted; use the impact hints above to decide whether doc sync is needed"
  fi
  echo ""
  echo "─────────────────────────────────────"
  echo "OK:    $ok"
  echo "WARN:  $warnings"
  echo "ERROR: $errors"
  echo "─────────────────────────────────────"
  [ "$errors" -gt 0 ] && exit "$EXIT_BLOCK"
  [ "$warnings" -gt 0 ] && exit "$EXIT_WARN"
  exit "$EXIT_OK"
fi

[ "$MODE" = "gate" ] && echo "docs_lint: changed-doc frontmatter checks"

while IFS= read -r f; do
  [ -z "$f" ] && continue

  if ! validate_feature_boundary_loc "$f"; then
    continue
  fi

  # git 衝突標記殘留檢查(IMP-0015 / 事故 92da32e64):rebase 未解衝突的標記進 main,
  # docs_lint 全綠沒擋到。只掃 <<<<<<< / ||||||| / >>>>>>>(行首 7 字元 + 空白),
  # 刻意不掃 =======,以免誤判 setext H1 底線。
  if conflict_hits=$(grep -nE '^([<]{7} |[|]{7} |[>]{7} )' "$f"); then
    echo "ERROR $f — 發現 git 衝突標記殘留(rebase/merge 未解):"
    echo "$conflict_hits" | sed 's/^/    /'
    errors=$((errors+1))
    continue
  fi

  # Extract frontmatter block(只抓第一個 <!-- doc-meta ... -->,避免被 doc 內其他 HTML 註解誤抓)
  meta=$(awk '/<!-- doc-meta/{flag=1} flag{print} /-->/{if(flag){exit}}' "$f")
  if [ -z "$meta" ]; then
    echo "ERROR $f — 沒有 <!-- doc-meta --> frontmatter"
    errors=$((errors+1))
    continue
  fi

  # Validate required fields
  missing=""
  for field in $REQUIRED_FIELDS; do
    if ! echo "$meta" | grep -qE "^${field}:"; then
      missing="$missing $field"
    fi
  done
  if [ -n "$missing" ]; then
    echo "ERROR $f — 缺欄位:$missing"
    errors=$((errors+1))
    continue
  fi

  # value 解析:抓 ": " 後面的內容,strip 前後空白與引號(YAML scalar 容錯)
  tier=$(echo "$meta" | grep -E "^tier:" | head -1 | sed -E 's/^tier:[[:space:]]*//; s/^"//; s/"$//')
  verified=$(echo "$meta" | grep -E "^verified_against:" | head -1 | sed -E 's/^verified_against:[[:space:]]*//; s/^"//; s/"$//')

  # Validate tier
  if ! echo " $VALID_TIERS " | grep -q " $tier "; then
    echo "ERROR $f — 非法 tier: $tier(允許: $VALID_TIERS)"
    errors=$((errors+1))
    continue
  fi

  # Archive: skip staleness
  if [ "$tier" = "archive" ]; then
    if [ "$verified" != "frozen" ]; then
      echo "WARN  $f — archive doc verified_against 應為 'frozen',實際: $verified"
      warnings=$((warnings+1))
    else
      ok=$((ok+1))
    fi
    continue
  fi

  # Validate verified_against is real commit
  if ! verified_sha=$(git rev-parse --verify --quiet "$verified^{commit}"); then
    echo "ERROR $f — verified_against 不是有效 commit(object db 找不到): $verified"
    echo "    修法: re-anchor 到當前 HEAD 可達的 code commit;rebase 後 anchor 必須重取"
    errors=$((errors+1))
    continue
  fi

  # Anchor 可達性:rebase 後舊 hash 成 orphan(object 還在,但不在 HEAD 祖先鏈),
  # 只驗 rev-parse 會假綠(事故: shared-decks Phase 2 doc-sync anchor 888dde5f0)。
  # 不變式 = reachable-from-HEAD:worktree pre-cutover anchor 指 branch 自身 commit 合法
  # (ff cutover 後自然 main 可達);rebase 後舊 hash 不可達 → 紅,強制 re-anchor。
  # audit 模式降 WARN,避免把全 repo 既有 debt 翻紅(gate/files 才是 PR 硬閘)。
  if ! git merge-base --is-ancestor "$verified_sha" HEAD 2>/dev/null; then
    if [ "$MODE" = "audit" ]; then
      echo "WARN  $f — verified_against 不可達(orphan,不在 HEAD 祖先鏈): $verified"
      warnings=$((warnings+1))
    else
      echo "ERROR $f — verified_against 不可達(orphan,不在 HEAD 祖先鏈): $verified"
      echo "    修法: re-anchor 到當前 HEAD 可達的 code commit;rebase 後 anchor 必須重取"
      errors=$((errors+1))
    fi
    continue
  fi

  # Anchor origin 可達性(第二層)。上面那段驗的是 HEAD 可達,而本 repo 拓樸是
  # 「本地 main 為主幹、刻意超前 origin」,所以錨在分支自身 commit 的 doc 上面全綠,
  # 卻正是 cutover 的 rebase 會 orphan 掉、CI 隨後拒收的那種——「origin 可達」這條知識
  # 原本只活在 ops/backlog.py 的 _doc_anchor() docstring 裡,這個讀取者一個字都不說。
  #
  # 一律 WARN 不 ERROR:worktree pre-cutover 錨在自身 commit 是**合法**情境(見上段註解),
  # 升 ERROR 會把整條 worktree 流程擋死。$ORIGIN_REF 不存在(未 fetch / shallow clone)
  # → 整段跳過,不得讓「沒有 remote」本身變成紅燈。
  if origin_sha=$(git rev-parse --verify --quiet "$ORIGIN_REF^{commit}"); then
    if ! git merge-base --is-ancestor "$verified_sha" "$origin_sha" 2>/dev/null; then
      echo "WARN  $f — verified_against origin-unreachable(只在本分支可達,cutover 的 rebase 會把它 orphan): $verified"
      # 短 sha 是刻意的:訊息自稱「可照抄」,而 repo 裡每個 verified_against 與
      # ops/backlog.py:_doc_anchor 的 `value[:9]` 都是 9 碼。印 40 碼等於教人種下
      # 唯一一個異形 anchor。
      if suggest=$(git merge-base "$origin_sha" HEAD 2>/dev/null) && [ -n "$suggest" ] \
        && suggest=$(git rev-parse --short=9 "$suggest" 2>/dev/null) && [ -n "$suggest" ]; then
        echo "    建議改錨: $suggest($ORIGIN_REF 與 HEAD 的 merge-base,rebase 後仍可達)"
      else
        # 憑空生一顆 sha 比不給建議更糟:這裡沒有任何 origin 可達的 commit 可指。
        echo "    建議改錨: 無 — $ORIGIN_REF 與 HEAD 無共同祖先,請先確認 KG_DOCS_LINT_ORIGIN_REF 指對 ref"
      fi
      warnings=$((warnings+1))
      # 這裡 continue 而非往下跑 staleness,是為了讓 OK/WARN/ERROR 三個計數維持互斥分割
      # (既有每個分支都是 warn+continue 或 ok+1)。代價可忽略:origin 不可達 = anchor 錨在
      # 很新的分支 commit,verified..HEAD 之間幾乎不可能累積到 STALE_THRESHOLD 個 commit。
      # 已知副作用:同時 origin 不可達又 scope 為空的 doc 只會聽到這一條,下一輪修完 anchor
      # 才會聽到 scope 那條。兩者都是 WARN,計數不受影響。
      continue
    fi
  fi

  # Extract scope paths
  scope_paths=$(echo "$meta" | awk '
    /^scope:/ { in_scope=1; next }
    in_scope && /^  - / { sub(/^  - /,""); print; next }
    in_scope && !/^  / { in_scope=0 }
  ')

  if [ -z "$scope_paths" ]; then
    echo "WARN  $f — scope 為空,無法計算 staleness"
    warnings=$((warnings+1))
    continue
  fi

  # Count commits in scope between verified..HEAD
  # NUL-delimit so scope paths containing whitespace survive as single args
  # (plain `xargs` word-splits on spaces → undercounts staleness). -0 is BSD-safe.
  commits_in_scope=$(printf '%s\n' "$scope_paths" | tr '\n' '\0' | xargs -0 git log --oneline "$verified..HEAD" -- 2>/dev/null | wc -l | tr -d ' ')

  if [ "$commits_in_scope" -gt "$STALE_THRESHOLD" ]; then
    echo "STALE $f — $verified..HEAD 期間 $commits_in_scope 個 commit 動到 scope(閾值 $STALE_THRESHOLD)"
    warnings=$((warnings+1))
  else
    ok=$((ok+1))
  fi
done <<EOF
$DOCS
EOF

echo ""
echo "─────────────────────────────────────"
echo "OK:    $ok"
echo "WARN:  $warnings"
echo "ERROR: $errors"
echo "─────────────────────────────────────"

[ "$errors" -gt 0 ] && exit "$EXIT_BLOCK"
[ "$warnings" -gt 0 ] && exit "$EXIT_WARN"
exit "$EXIT_OK"
