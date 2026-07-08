#!/usr/bin/env bash
# release.sh — KG 版號發布統一入口（對標 backend/ops_cli.py 的單入口 + 乾淨 subcommand）
#
# 收斂原本散在 /release command（prose）+ scripts/ primitives 的發版編排。
# 寫入面（bump 改本地檔、publish push）一律 dry-run 預設、--yes 才落地（同 asc.sh set 紀律）。
# 注意：目前無 tag-triggered CI workflow，tag 為「版本標記」，GitHub Release 須手動建。
#
# Usage:
#   ./ops/release.sh status                     # 各 component 自上個 tag 以來的待發版 commit + 建議版號
#   ./ops/release.sh changelog <api|ios>        # 印 markdown changelog 預覽（唯讀）
#   ./ops/release.sh bump <api|ios> <x.y.z>     # 改本地版號檔（api: pyproject+api.py / ios: pbxproj；預設 dry-run 印舊→新，--yes 才寫）
#   ./ops/release.sh publish <api|ios> <x.y.z>  # commit 版號檔 + tag + push（預設 dry-run，--yes 才真送）
#
# 全域 flag：--yes（bump 真寫 / publish 真送）  -h|--help
# App Store 側（正交）：出 build → ops/ios_release.sh；查/改文案 → ops/asc.sh；細節見 docs/sop/ios.md §發版。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YES=0

err()  { echo "✗ $*" >&2; exit 1; }
# 只印開頭連續註解區（停在第一個非 # 行），避免把 set -euo pipefail / ROOT= / YES= 洩進 help。
usage() { awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; }

# ---- component → tag/commit prefix + 版號檔（單一真相，與 release_bump.sh 對映） ----
tag_prefix()    { case "$1" in api) echo "api/";; ios) echo "ios/";; *) err "未知 component: $1（api|ios）";; esac; }
commit_prefix() { case "$1" in api) echo "api:";; ios) echo "ios:";; esac; }

current_version() {  # 從版號檔讀目前 marketing 版本
  case "$1" in
    api) grep -m1 '^version = ' "$ROOT/backend/pyproject.toml" | sed -E 's/.*"([^"]+)".*/\1/' ;;
    ios) grep -m1 'MARKETING_VERSION = ' "$ROOT/ios/BooksAndVocab.xcodeproj/project.pbxproj" | sed -E 's/.*MARKETING_VERSION = ([^;]+);.*/\1/' | tr -d ' ' ;;
  esac
}

valid_semver() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; }

bump_semver() {  # $1=x.y.z  $2=major|minor|patch
  local IFS=.; read -r MA MI PA <<<"$1"
  case "$2" in
    major) echo "$((MA+1)).0.0" ;;
    minor) echo "$MA.$((MI+1)).0" ;;
    patch) echo "$MA.$MI.$((PA+1))" ;;
  esac
}

last_tag() { git -C "$ROOT" tag -l "$(tag_prefix "$1")*" --sort=-v:refname 2>/dev/null | head -1; }

# ---- status：各 component 待發版總覽（唯讀） ----
cmd_status() {
  for c in api ios; do
    local tp cp lt range commits n suggest curver basever sv
    tp="$(tag_prefix "$c")"; cp="$(commit_prefix "$c")"
    lt="$(last_tag "$c")"
    if [[ -n "$lt" ]]; then range="$lt..HEAD"; else range=""; fi
    if [[ -n "$range" ]]; then
      commits="$(git -C "$ROOT" log "$range" --oneline --no-merges 2>/dev/null | grep -iE "^[a-f0-9]+ $cp" || true)"
    else
      commits="$(git -C "$ROOT" log --oneline --no-merges 2>/dev/null | grep -iE "^[a-f0-9]+ $cp" || true)"
    fi
    n="$(printf '%s' "$commits" | grep -c . || true)"
    # 建議 bump 等級
    if printf '%s' "$commits" | grep -qiE 'breaking|重寫|!:'; then suggest=major
    elif printf '%s' "$commits" | grep -qiE 'feat|新增|支援|feature'; then suggest=minor
    else suggest=patch; fi
    curver="$(current_version "$c")"
    basever="${lt#"$tp"}"; [[ -n "$basever" ]] || basever="$curver"
    if valid_semver "$basever"; then sv="$(bump_semver "$basever" "$suggest")"; else sv="（首發，參考檔內 ${curver}）"; fi

    echo "■ $c  上個 tag：${lt:-（尚未發版）}  檔內版本：$curver"
    # 漂移警示：上個 tag 的版號與版號檔不一致（如 tag api/1.6.0 但 pyproject 0.1.0）→ 發版前先對齊。
    # 比較前把兩段版號（ios pbxproj 慣用 1.6）補成三段再比，避免「1.6 vs 1.6.0」恆觸發警報疲勞。
    local cmpcur="$curver"
    [[ "$cmpcur" =~ ^[0-9]+\.[0-9]+$ ]] && cmpcur="$cmpcur.0"
    if [[ -n "$lt" && "$basever" != "$cmpcur" ]]; then
      echo "   ⚠ 版號漂移：上個 tag=${basever} 但檔內=${curver}（發版前先 bump 對齊）"
    fi
    if [[ "$n" -eq 0 ]]; then
      echo "   自上個 tag 無 $cp commit（無待發版）"
    else
      echo "   待發版 $n 筆 $cp commit；建議 $suggest → $sv"
      printf '%s\n' "$commits" | head -15 | sed 's/^/     /'
      [[ "$n" -gt 15 ]] && echo "     … 還有 $((n-15)) 筆（完整清單見 ./ops/release.sh changelog ${c}）"
    fi
    echo
  done
  echo "下一步：./ops/release.sh bump <c> <ver> --yes → changelog <c> → publish <c> <ver> --yes"
}

# ---- changelog：委派 primitive（唯讀） ----
cmd_changelog() {
  local c="${1:?用法: release.sh changelog <api|ios>}"; tag_prefix "$c" >/dev/null
  "$ROOT/ops/release_changelog.sh" "$c"
}

# ---- bump：委派 primitive（本地檔案寫入；dry-run 預設，--yes 才寫） ----
cmd_bump() {
  local c="${1:?用法: release.sh bump <api|ios> <x.y.z> [--yes]}" v="${2:-}"
  tag_prefix "$c" >/dev/null
  [[ -n "$v" ]] || err "請提供版本號 x.y.z"
  valid_semver "$v" || err "版本號格式錯誤：${v}（需 x.y.z）"
  if [[ $YES -eq 1 ]]; then
    "$ROOT/ops/release_bump.sh" "$c" "$v" --yes
  else
    "$ROOT/ops/release_bump.sh" "$c" "$v"
  fi
}

# ---- publish：commit 版號檔 + tag + push（dry-run 預設，--yes 才真送） ----
cmd_publish() {
  local c="${1:?用法: release.sh publish <api|ios> <x.y.z> [--yes]}" v="${2:-}"
  tag_prefix "$c" >/dev/null
  [[ -n "$v" ]] || err "請提供版本號 x.y.z"
  valid_semver "$v" || err "版本號格式錯誤：${v}（需 x.y.z）"

  local tp tag files curver branch
  tp="$(tag_prefix "$c")"; tag="${tp}${v}"
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  [[ "$branch" != HEAD ]] || err "detached HEAD —— 先 checkout 一個分支再發版（避免 push origin HEAD）"
  case "$c" in
    api) files=(backend/pyproject.toml backend/src/kg/api.py) ;;
    ios) files=(ios/BooksAndVocab.xcodeproj/project.pbxproj) ;;
  esac

  # preflight
  git -C "$ROOT" rev-parse -q --verify "refs/tags/$tag" >/dev/null \
    && err "tag $tag 已存在（重複發版？換版號或先刪 tag）"
  curver="$(current_version "$c")"
  [[ "$curver" == "$v" ]] || err "版號檔目前是 ${curver}，非 ${v} —— 先跑 ./ops/release.sh bump ${c} ${v} --yes"

  echo "component=$c  version=$v  tag=$tag  branch=$branch"
  echo "  將 commit 的檔：${files[*]}"
  echo "  commit message：ops: release $c $v"

  if [[ $YES -eq 1 ]]; then
    git -C "$ROOT" add -- "${files[@]}"
    git -C "$ROOT" commit -m "ops: release $c $v"
    git -C "$ROOT" tag "$tag"
    git -C "$ROOT" push origin "$branch" "$tag"
    echo "✓ 已 commit + tag ${tag} + 推送到 origin/${branch}（tag 為版本標記；無 tag-triggered CI，GitHub Release 須手動建）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會 commit + 打 tag + 推送 origin："
    echo "  ./ops/release.sh publish $c $v --yes"
  fi
}

# ---- 全域 flag 解析（subcommand 前後皆可） ----
SUB=""; ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)      YES=1; shift ;;
    -h|--help)  usage; exit 0 ;;
    -*)         err "unknown option: $1" ;;
    *)          if [[ -z "$SUB" ]]; then SUB="$1"; else ARGS+=("$1"); fi; shift ;;
  esac
done

case "${SUB:-}" in
  # ${ARGS[@]+"${ARGS[@]}"}：空陣列→零參數（讓 cmd 的 ${1:?usage} 正常觸發），非空→保留各元素引號；
  # 不用 "${ARGS[@]:-}"（空時會誤傳一個空字串參數）。
  status)    cmd_status ;;
  changelog) cmd_changelog ${ARGS[@]+"${ARGS[@]}"} ;;
  bump)      cmd_bump ${ARGS[@]+"${ARGS[@]}"} ;;
  publish)   cmd_publish ${ARGS[@]+"${ARGS[@]}"} ;;
  ""|help)   usage ;;
  *)         err "unknown subcommand: ${SUB}（release.sh help 看用法）" ;;
esac
