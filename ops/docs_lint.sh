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
#
# 用法:
#   ops/docs_lint.sh                 # gate: registry + changed docs
#   ops/docs_lint.sh --changed       # 只掃本分支/工作樹變更的 docs
#   ops/docs_lint.sh --since <rev>   # 只掃 <rev>..HEAD + 工作樹變更的 docs
#   ops/docs_lint.sh --files <docs...>
#   ops/docs_lint.sh <docs/...md> [<docs/...md> ...]  # 相當於 --files
#   ops/docs_lint.sh --registry      # 只驗證 docs/registry.yml
#   ops/docs_lint.sh --audit|--all   # 全 repo audit(可暴露既有 debt)
#   ops/docs_lint.sh --strict        # 任何 WARN 都 exit 1
#   STALE_THRESHOLD=10 ops/docs_lint.sh
#
# Exit code:
#   0 — 全部 OK 或僅 WARN
#   1 — 有 ERROR(欄位缺失 / verified_against 無效)或 --strict 模式下有 WARN
#
# 相容 bash 3.2(macOS 預設),不使用 mapfile / readarray。

set -euo pipefail

# 檢查呼叫者所在 checkout。linked worktree 與 main 共用 object store,但工作樹檔案各自獨立；
# 強制 cd 回 main 會漏掉 PR worktree 內尚未 commit 的 docs/registry 變更。
cd "$(git rev-parse --show-toplevel)"

STALE_THRESHOLD="${STALE_THRESHOLD:-30}"
STRICT=0
MODE="gate"
SINCE_REV=""
FILE_ARGS=()
GATE_BASE=""

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
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
        exit 2
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [ "${1#-}" != "$1" ]; then
        echo "Unknown arg: $1" >&2
        echo "提示: 若要指定 doc 路徑,請改用 --files: ops/docs_lint.sh --files docs/<path>.md ..." >&2
        echo "      或直接傳 doc 路徑: ops/docs_lint.sh docs/<path>.md ..." >&2
        exit 2
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

REQUIRED_FIELDS="tier authority update_trigger scope verified_against"
VALID_TIERS="policy sop reference snapshot runbook archive assets"
REGISTRY_KINDS="contract generated reference sop policy decision guide snapshot runbook archive assets"

errors=0
warnings=0
ok=0
IMPACT_HINTS_EMITTED=0

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
      # `</dev/null` 不是噪音，不要刪：這個 while 迴圈的 stdin 是 ${entries_tmp}（見迴圈尾），
      # 任何繼承 stdin 的子命令都會吃掉尚未讀取的 registry entry。症狀是後面幾筆 entry
      # 神秘消失、entry_count 少掉，而 rc 仍是 0——正是本 gate 存在要擋的那類錯誤。
      elif ! sh -c "$check" </dev/null >/dev/null 2>&1; then
        echo "ERROR registry — $id 產物與 generator 輸出不一致: $path(跑 $check 看差異)"
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
    exit 2
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
    exit 2
  fi
  for f in "${FILE_ARGS[@]}"; do
    case "$f" in
      docs/*.md) ;;
      *)
        echo "ERROR --files 只接受 docs/*.md 路徑: $f" >&2
        exit 2
        ;;
    esac
    case "$f" in
      docs/assets/*|docs/legal/*)
        echo "ERROR --files 不掃描 assets/legal doc: $f" >&2
        exit 2
        ;;
    esac
    if [ ! -f "$f" ]; then
      echo "ERROR --files 路徑不存在: $f" >&2
      exit 2
    fi
  done
  printf '%s\n' "${FILE_ARGS[@]}" | sort -u
}

echo "docs_lint: mode=$MODE"
validate_registry

if [ "$MODE" = "registry" ]; then
  echo ""
  echo "─────────────────────────────────────"
  echo "OK:    $ok"
  echo "WARN:  $warnings"
  echo "ERROR: $errors"
  echo "─────────────────────────────────────"
  [ "$errors" -gt 0 ] && exit 1
  exit 0
fi

if [ "$MODE" = "gate" ]; then
  GATE_BASE="${SINCE_REV:-$(default_changed_base)}"
  if ! git rev-parse --verify "$GATE_BASE^{commit}" >/dev/null 2>&1; then
    echo "ERROR --since/changed base 不是有效 commit: $GATE_BASE" >&2
    exit 2
  fi
  emit_impact_hints
fi

case "$MODE" in
  audit) DOCS=$(all_docs) ;;
  gate) DOCS=$(changed_docs) ;;
  files) DOCS=$(files_docs) ;;
  *) echo "internal error: unknown MODE=$MODE" >&2; exit 2 ;;
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
  [ "$errors" -gt 0 ] && exit 1
  [ "$STRICT" -eq 1 ] && [ "$warnings" -gt 0 ] && exit 1
  exit 0
fi

[ "$MODE" = "gate" ] && echo "docs_lint: changed-doc frontmatter checks"

while IFS= read -r f; do
  [ -z "$f" ] && continue

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

[ "$errors" -gt 0 ] && exit 1
[ "$STRICT" -eq 1 ] && [ "$warnings" -gt 0 ] && exit 1
exit 0
