#!/usr/bin/env bash
# release.sh — KG 版號發布統一入口（對標 backend/ops_cli.py 的單入口 + 乾淨 subcommand）
#
# 收斂原本散在 /release command（prose）+ scripts/ primitives 的發版編排。
# 寫入面（bump 改本地檔、publish push）一律 dry-run 預設、--yes 才落地（同 asc.sh set 紀律）。
# 注意：目前無 tag-triggered CI workflow，tag 為「版本標記」，GitHub Release 須手動建。
#
# 三平面 release 平面入口。develop=cutover 進本地 main；backup=orchestrate sync 推 origin/main；
# release=刻意發布。前後端共用 `release <backend|ios> <ver>`，底下各自機器（backend 推 origin/prod
# →felix reconciler；ios→ios_release upload TestFlight）。tag 只做「版號標記」（push origin main=備份，
# 非部署）。
#
# Usage:
#   ./ops/release.sh status                      # 各 component 待發版 commit + released gap（本地唯讀）
#   ./ops/release.sh changelog <api|ios>         # 印 markdown changelog 預覽（唯讀）
#   ./ops/release.sh bump <api|ios> <x.y.z>      # 改本地版號檔（api: pyproject+api.py / ios: pbxproj；dry-run 預設，--yes 才寫）
#   ./ops/release.sh bump-build ios              # 只 +1 pbxproj CURRENT_PROJECT_VERSION（App Review 被拒同版重送；dry-run 預設，--yes 才寫）
#   ./ops/release.sh tag <api|ios> <x.y.z>       # commit 版號檔 + tag + push origin main（iOS 新版另須 --new-version-after-ready <previous>）
#   ./ops/release.sh release <backend|ios> <x.y.z>  # 統一發布（iOS 新版須 --new-version-after-ready <previous>）。須在 main。dry-run 預設
#   ./ops/release.sh publish <api|ios> <x.y.z>   # 已改名 tag 的別名（相容保留）
#
# 全域 flag：--yes（bump/tag 真寫、release 真執行）
# iOS 新 marketing version attestation：--new-version-after-ready <previous-version>
#   表示 operator 已從 ASC 確認 previous-version 完成審查；本 guard 不連網，只和 latest local ios/* tag 對證。
#   未上架/被拒重送不可用此 flag，應走 bump-build ios + ios_release.sh --upload。
# 其他：-h|--help
# App Store 側（正交）：出 build → ops/ios_release.sh；查/改文案 → ops/asc.sh；細節見 docs/sop/ios.md §發版。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YES=0
NEW_VERSION_AFTER_READY=""

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

semver_gt() {
  local rma rmi rpa pma pmi ppa
  IFS=. read -r rma rmi rpa <<<"$1"
  IFS=. read -r pma pmi ppa <<<"$2"
  rma=$((10#$rma)); rmi=$((10#$rmi)); rpa=$((10#$rpa))
  pma=$((10#$pma)); pmi=$((10#$pmi)); ppa=$((10#$ppa))
  (( rma > pma ||
     (rma == pma && rmi > pmi) ||
     (rma == pma && rmi == pmi && rpa > ppa) ))
}

bump_semver() {  # $1=x.y.z  $2=major|minor|patch
  local IFS=.; read -r MA MI PA <<<"$1"
  case "$2" in
    major) echo "$((MA+1)).0.0" ;;
    minor) echo "$MA.$((MI+1)).0" ;;
    patch) echo "$MA.$MI.$((PA+1))" ;;
  esac
}

last_tag() { git -C "$ROOT" tag -l "$(tag_prefix "$1")*" --sort=-v:refname 2>/dev/null | head -1; }

# iOS marketing version 是否能前進的 server 真相只在 ASC；為避免把 release 綁死在網路/API，
# 這裡要求 operator 用 typed attestation 明示已查證，並以 latest local ios/* tag 對證 previous version。
# 它不宣稱離線驗出 READY_FOR_SALE，而是讓「新版本」不能從 semver 建議被默默推導。
guard_ios_new_version() {
  local requested="$1" previous_tag previous
  previous_tag="$(last_tag ios)"
  [[ -n "$previous_tag" ]] || err "找不到上一個 ios/* tag，無法離線對證新版本前序；先人工確認 release history"
  previous="${previous_tag#ios/}"

  [[ "$requested" != "$previous" ]] \
    || err "${requested} 已是上一個 release tag；未上架/被拒同版重送請走 ./ops/release.sh bump-build ios --yes，再跑 ./ops/ios_release.sh --upload"
  [[ -n "$NEW_VERSION_AFTER_READY" ]] \
    || err "iOS 新 marketing version 須明示 --new-version-after-ready ${previous}（僅在 ASC 確認 ios/${previous} 已完成審查後使用）；未上架/被拒請走 bump-build ios"
  valid_semver "$NEW_VERSION_AFTER_READY" \
    || err "--new-version-after-ready 格式錯誤：${NEW_VERSION_AFTER_READY}（需 x.y.z）"
  [[ "$NEW_VERSION_AFTER_READY" == "$previous" ]] \
    || err "--new-version-after-ready ${NEW_VERSION_AFTER_READY} 與 latest local tag ${previous_tag} 不符；停止發版並重查 ASC/release history"
  semver_gt "$requested" "$previous" \
    || err "iOS 新 marketing version ${requested} 必須高於 latest local tag ${previous}；禁止倒退或重用已發布版號"
}

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
    # released 面（本地唯讀；不碰遠端）：origin/prod tracking ref = 上次 fetch 的「期望部署狀態」
    if [[ "$c" == api ]]; then
      local prod_ref ahead_prod
      prod_ref="$(git -C "$ROOT" rev-parse --short origin/prod 2>/dev/null || true)"
      if [[ -n "$prod_ref" ]]; then
        ahead_prod="$(git -C "$ROOT" rev-list --count origin/prod..main 2>/dev/null || echo '?')"
        echo "   released：origin/prod=${prod_ref}；main 超前 prod ${ahead_prod} commit（release backend 才推 prod→部署）"
      else
        echo "   released：origin/prod 本地未知（尚未 seed 或未 fetch；見 docs/sop/release.md 切換）"
      fi
      echo "   live：curl -s https://wordnexus.lol/api/system/info（欲查生產實跑版本）"
    else
      echo "   live：./ops/asc.sh builds（TestFlight 最新 build）+ review-status"
    fi
    echo
  done
  echo "下一步：./ops/release.sh bump <c> <ver> --yes → changelog <c> → release <backend|ios> <ver> --yes"
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

# ---- bump-build：只 +1 iOS build number（被拒同版重送；委派 primitive --build-only） ----
cmd_bump_build() {
  local c="${1:?用法: release.sh bump-build ios [--yes]}"
  [[ "$c" == ios ]] || err "bump-build 只支援 ios（api 無 build number；改版號用 ./ops/release.sh bump api <x.y.z>）"
  [[ $# -le 1 ]] || err "多餘參數：${*:2}（bump-build 不吃版本號，build number 自動 +1）"
  if [[ $YES -eq 1 ]]; then
    "$ROOT/ops/release_bump.sh" ios --build-only --yes
  else
    "$ROOT/ops/release_bump.sh" ios --build-only
  fi
}

# ---- tag：commit 版號檔 + 打 tag + push origin main（版號標記+備份，非部署；dry-run 預設）----
# 三平面：tag 是 release 平面的「版號標記」子步驟。它 push origin main = backup（reconciler 不看
# main），不觸發生產。生產部署由 release <backend|ios> 的 deploy(prod)/upload 完成。（原名 publish）
cmd_tag() {
  local c="${1:?用法: release.sh tag <api|ios> <x.y.z> [--yes]}" v="${2:-}"
  tag_prefix "$c" >/dev/null
  [[ -n "$v" ]] || err "請提供版本號 x.y.z"
  valid_semver "$v" || err "版本號格式錯誤：${v}（需 x.y.z）"
  if [[ "$c" == ios ]]; then
    guard_ios_new_version "$v"
  elif [[ -n "$NEW_VERSION_AFTER_READY" ]]; then
    err "--new-version-after-ready 只適用 iOS 新 marketing version"
  fi

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
    if git -C "$ROOT" diff --cached --quiet -- "${files[@]}"; then
      echo "  版號檔已在目前 HEAD，略過空 release commit；tag 將指向 $(git -C "$ROOT" rev-parse --short HEAD)"
    else
      # pathspec 鎖住 release files，避免把 operator 預先 staged 的無關變更一起提交。
      git -C "$ROOT" commit -m "ops: release $c $v" -- "${files[@]}"
    fi
    git -C "$ROOT" tag "$tag"
    git -C "$ROOT" push origin "$branch" "$tag"
    echo "✓ 已 commit + tag ${tag} + 推送 origin/${branch}（版號標記+備份；生產部署走 release <backend|ios>）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會 commit + 打 tag + 推送 origin："
    echo "  ./ops/release.sh tag $c $v --yes"
  fi
}

# ---- release：前後端統一發布入口。dry-run 預設，--yes 才執行 ----
# backend: bump api → tag api → orchestrate deploy --commit（推 origin/prod = felix reconciler 部署）
# ios:     bump ios → ios_release.sh --upload（archive + 上傳 TestFlight）→ tag ios（upload failure 不留 false tag）
# 須在 primary、on main（release 發布本地主幹；feature 改動先 cutover 進 main）。
cmd_release() {
  local target="${1:?用法: release.sh release <backend|ios> <x.y.z> [--yes]}" v="${2:-}"
  local comp
  case "$target" in
    backend|api) comp=api ;;
    ios)         comp=ios ;;
    *) err "未知 target: ${target}（backend|ios）" ;;
  esac
  [[ -n "$v" ]] || err "請提供版本號 x.y.z"
  valid_semver "$v" || err "版本號格式錯誤：${v}（需 x.y.z）"
  if [[ "$comp" == ios ]]; then
    guard_ios_new_version "$v"
  elif [[ -n "$NEW_VERSION_AFTER_READY" ]]; then
    err "--new-version-after-ready 只適用 iOS 新 marketing version"
  fi

  local branch curver need_bump
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  [[ "$branch" == main ]] || err "release 須在 main 執行（目前 ${branch}）—— 它發布本地主幹；feature 改動先 cutover 進 main"
  curver="$(current_version "$comp")"
  # need_bump 用 RAW 相等（與 cmd_tag 的 strict curver==v 檢查一致）：ios 慣用兩段 MARKETING_VERSION
  # (如 2.0)，若用正規化相等判 2.0==2.0.0 會跳過 bump，但 cmd_tag strict 比較 raw 2.0≠2.0.0 反而
  # abort。用 raw 判 → 2.0 vs 2.0.0 觸發 bump 寫成三段 → cmd_tag 一致通過。
  need_bump=0; [[ "$curver" == "$v" ]] || need_bump=1

  echo "release target=${target}（component=${comp}）version=${v}  branch=${branch}"
  echo "  計畫（dry-run 預設）："
  if [[ $need_bump -eq 1 ]]; then echo "    1) bump ${comp} ${v}（檔內 ${curver} → ${v}）"; else echo "    1) bump 略過（檔內已 ${curver}）"; fi
  if [[ "$comp" == api ]]; then
    echo "    2) tag ${comp} ${v}（commit 版號檔 + ${comp}/${v} tag + push origin main）"
    echo "    3) orchestrate deploy --commit（推 origin/prod → felix reconciler 部署 wordnexus.lol）⚠ 生產"
  else
    echo "    2) ios_release.sh --upload（archive + 上傳 TestFlight）⚠ 外部不可逆"
    echo "    3) tag ${comp} ${v}（upload 成功後才 commit 版號檔 + ${comp}/${v} tag + push origin main）"
  fi

  if [[ $YES -ne 1 ]]; then
    echo "[dry-run] 未執行。確認無誤後加 --yes："
    echo "  ./ops/release.sh release ${target} ${v} --yes"
    return 0
  fi

  # 執行：任一步失敗即 err 中止（cmd_bump/cmd_tag 讀全域 YES=1）
  if [[ $need_bump -eq 1 ]]; then cmd_bump "$comp" "$v"; fi
  if [[ "$comp" == api ]]; then
    cmd_tag "$comp" "$v"
    "$ROOT/ops/worktree_orchestrate.py" deploy --commit || err "deploy 失敗，中止（origin/prod 未前進）"
    echo "✓ release backend ${v}：已 tag + 推 origin/prod；felix reconciler 將健康 gate 部署。"
  else
    "$ROOT/ops/ios_release.sh" --upload || err "ios_release --upload 失敗，中止"
    cmd_tag "$comp" "$v"
    echo "✓ release ios ${v}：已上傳 TestFlight + tag（GUI 綁 build 送審見 docs/sop/ios.md）。"
  fi
}

# ---- 全域 flag 解析（subcommand 前後皆可） ----
SUB=""; ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)      YES=1; shift ;;
    --new-version-after-ready)
      [[ $# -ge 2 && -n "${2:-}" ]] || err "--new-version-after-ready 需要 previous-version（x.y.z）"
      NEW_VERSION_AFTER_READY="$2"; shift 2 ;;
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
  bump-build) cmd_bump_build ${ARGS[@]+"${ARGS[@]}"} ;;
  tag)       cmd_tag ${ARGS[@]+"${ARGS[@]}"} ;;
  publish)   cmd_tag ${ARGS[@]+"${ARGS[@]}"} ;;   # 相容別名：publish → tag
  release)   cmd_release ${ARGS[@]+"${ARGS[@]}"} ;;
  ""|help)   usage ;;
  *)         err "unknown subcommand: ${SUB}（release.sh help 看用法）" ;;
esac
