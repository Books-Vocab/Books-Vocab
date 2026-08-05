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
#   ./ops/release.sh bump <api|ios> <x.y.z>      # 改本地版號檔（api: pyproject+api.py+uv.lock / ios: pbxproj；dry-run 預設，--yes 才寫）
#   ./ops/release.sh bump-build ios              # 只 +1 pbxproj CURRENT_PROJECT_VERSION（App Review 被拒同版重送；dry-run 預設，--yes 才寫）
#   ./ops/release.sh tag <api|ios> <x.y.z>       # commit 版號檔 + tag + push origin main（ios 封的是 ios/<x.y.z>+<build>）
#   ./ops/release.sh release <backend|ios> <x.y.z>  # 統一發布。須在 main。dry-run 預設
#   ./ops/release.sh shipped ios                 # 查 ASC 上架版本 → join build tag → 打 ios/<x.y.z>（dry-run 預設）
#   ./ops/release.sh resubmit ios                # 同版號、新 build 重送：bump-build → upload → 封 ios/<x.y.z>+<build>（dry-run 預設）
#   ./ops/release.sh publish <api|ios> <x.y.z>   # 已改名 tag 的別名（相容保留）
#
# iOS 版號的兩種 tag（語意不同，別混）：
#   ios/<x.y.z>          該 marketing version **上架 App Store** 的那顆 commit。
#                        只由 `shipped ios` 依 ASC 驗證後物化；immutable，不移動。
#   ios/<x.y.z>+<build>  該 (version, build) 的封版 commit。由 tag/release/resubmit 產生；
#                        immutable，同版可多顆並存（Apple 的 build number 每個版本重新計數，
#                        單獨沒有意義，必須成對）。
# `--new-version-after-ready` 已移除：ios/<x.y.z> 現在代表上架，tag 存在本身就是證據。
#
# 全域 flag：--yes（bump/tag 真寫、release/shipped/resubmit 真執行）
#           --commit <sha>（僅 shipped：build tag 不存在時人工指定封版 commit；會標記為人工斷言）
# 其他：-h|--help
# App Store 側（正交）：出 build → ops/ios_release.sh；查/改文案 → ops/asc.sh；細節見 docs/sop/ios.md §發版。

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
YES=0
SHIPPED_COMMIT=""
IOS_SAME_VERSION_RESUBMIT=0

# shellcheck source=lib/release_tags.sh
. "$ROOT/ops/lib/release_tags.sh"

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

current_build() {  # iOS app target 的 CURRENT_PROJECT_VERSION（主 app＝檔內第一個，同 release_bump.sh 口徑）
  grep -m1 -o 'CURRENT_PROJECT_VERSION = [0-9]*' "$ROOT/ios/BooksAndVocab.xcodeproj/project.pbxproj" \
    | sed -E 's/.*= *//'
}

valid_semver() { [[ "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; }

# ---- build tag：(marketing version, build number) → 封版 commit ----
# Apple 端沒有這個事實可查：appStoreVersions 只留「當前」一筆，versionString 是可變欄位
# （1.4→1.5→…→2.0.0 反覆改寫同一筆記錄），build number 又每個 marketing version 重新
# 計數。所以「哪顆 commit 產生了哪顆 build」只有 repo 知道，且必須在出 archive 的當下
# 捕捉——事後無從重建。這個 tag 是 immutable 的：同一 (version, build) 不會有第二顆
# archive，若真有，那是必須人工釐清的歧義，不是可覆蓋的重複。
ios_build_tag() { printf 'ios/%s+%s\n' "$1" "$2"; }   # `+` 在 git ref name 合法

IOS_BUILD_TAG_STATE=""
check_ios_build_tag() {  # $1=build tag；設 IOS_BUILD_TAG_STATE=new|idempotent，衝突則 err
  local tag="$1" existing head_now
  existing="$(git -C "$ROOT" rev-parse -q --verify "refs/tags/${tag}^{commit}" || true)"
  if [[ -z "$existing" ]]; then IOS_BUILD_TAG_STATE=new; return 0; fi
  head_now="$(git -C "$ROOT" rev-parse HEAD)"
  # 冪等只在「tag 已指向 HEAD 且版號檔沒有待 commit 的改動」時成立：pbxproj 還髒代表
  # 接下來會生出新 commit，那顆 tag 就會落在不同 commit 上，屬於下面的歧義。
  if [[ "$existing" == "$head_now" ]] \
     && git -C "$ROOT" diff --quiet HEAD -- ios/BooksAndVocab.xcodeproj/project.pbxproj; then
    IOS_BUILD_TAG_STATE=idempotent; return 0
  fi
  err "build tag ${tag} 已存在且指向 $(git -C "$ROOT" rev-parse --short "$existing")，但本次要封的是另一顆 commit。
   同一 (version, build) 從兩顆不同 commit 出過 archive = 真正的歧義，不靜默覆蓋。
   若這次是新的 archive，先 ./ops/release.sh bump-build ios --yes 取得新 build number；
   若是既有那顆的補封，請確認哪顆 commit 才是上傳的那顆再人工處理 tag。"
}

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

# 版號漂移有兩種形狀，補救方向剛好相反：
#   ahead     — 檔內版號高於上個 tag：正常的「已 bump、未 tag」，發版前對齊即可。
#   mistagged — 上個 tag 高於檔內版號：那個版號被**撤回**了（tag 打了，pbxproj /
#               pyproject 隨後 revert 回去）。此時「先 bump 對齊」是錯誤指引，照做
#               會復活一個刻意撤回的版號；而且留著誤標 tag 會讓 last_tag 說謊——
#               新語意下 ios/<x.y.z> 宣稱「已上架」，一個從未上架的版號掛著這種
#               tag，會讓 guard 以它為基準，新版號也被迫跳過它。正解是刪掉那個 tag。
#               實例：ios/2.0.1（6821015a6 打 tag → f3499f3d4 還原成 2.0.0，2.0.1
#               從未上架；2.0.0 才是 READY_FOR_SALE）。
classify_version_drift() {  # $1=tag 版號 $2=檔內版號（呼叫端負責補成三段）
  if [[ "$1" == "$2" ]]; then printf 'none\n'
  elif ! valid_semver "$1" || ! valid_semver "$2"; then printf 'none\n'
  elif semver_gt "$1" "$2"; then printf 'mistagged\n'
  else printf 'ahead\n'; fi
}

bump_semver() {  # $1=x.y.z  $2=major|minor|patch
  local IFS=.; read -r MA MI PA <<<"$1"
  case "$2" in
    major) echo "$((MA+1)).0.0" ;;
    minor) echo "$MA.$((MI+1)).0" ;;
    patch) echo "$MA.$MI.$((PA+1))" ;;
  esac
}

# 「最新的 released marketing version tag」的實作在 ops/lib/release_tags.sh —— 與
# release_changelog.sh 共用同一份。`git tag -l "<prefix>*"` 的 `*` 會跨 `/` 比對，所以
# build tag 也落在 glob 內，且 `--sort=-v:refname` 把 ios/2.0.0+6 排在 ios/2.0.0 之上；
# 兩邊各自維護一份收緊規則，就是「只修了其中一份」那類事故的溫床。
last_tag() {
  local out rc=0
  out="$(release_last_tag "$1" "$ROOT")" || rc=$?
  case "$rc" in
    0) printf '%s\n' "$out" ;;
    1) err "未知 component: $1（api|ios）" ;;
    *) err "無法列出 $1 的 tag（git 失敗）—— 不把它當成「尚未發版」處理" ;;
  esac
}

# 出過 build、但還沒有上架 tag 的 marketing version。build tag 讓這件事第一次可檢查：
# 在此之前 repo 完全不記錄「某版出過 archive」，所以「跳過一個還沒上架的版本」只能靠人記得。
ios_pending_versions() {  # $1=已上架版本 $2=本次要發的版本 → 印出待確認版本（空白分隔）
  local shipped="$1" requested="$2" all line ver out=""
  all="$(git -C "$ROOT" tag -l 'ios/*+*')" || err "無法列出 ios build tag（git 失敗）"
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    ver="${line#ios/}"; ver="${ver%%+*}"
    valid_semver "$ver" || continue
    [[ "$ver" != "$requested" ]] || continue
    semver_gt "$ver" "$shipped" || continue
    case " $out " in *" $ver "*) ;; *) out="${out:+$out }$ver" ;; esac
  done <<< "$all"
  printf '%s\n' "$out"
}

# ios/<x.y.z> 現在的語意是「這個 marketing version 上架 App Store 的那顆 commit」，由
# `shipped ios` 依 ASC 驗證後才物化。所以**它存在本身就是上架證據**，這個 guard 不再需要
# operator 的 typed attestation（`--new-version-after-ready` 因此被移除），而是真的在檢查。
guard_ios_new_version() {
  local requested="$1" shipped_tag shipped pending
  shipped_tag="$(last_tag ios)"
  [[ -n "$shipped_tag" ]] || err "找不到任何已上架 tag ios/<x.y.z>（build tag 不算——那只代表出過 archive）。
   無從判斷 ${requested} 是不是真的往前。先跑 ./ops/release.sh shipped ios 從 ASC 確認目前上架的版本。"
  shipped="${shipped_tag#ios/}"

  [[ "$requested" != "$shipped" ]] \
    || err "${requested} 已經上架（${shipped_tag}）；同版號、新 build 的重送請走 ./ops/release.sh resubmit ios --yes"
  semver_gt "$requested" "$shipped" \
    || err "iOS 新 marketing version ${requested} 必須高於已上架的 ${shipped}；禁止倒退或重用已發布版號"

  pending="$(ios_pending_versions "$shipped" "$requested")"
  [[ -z "$pending" ]] || err "以下版本出過 build、但沒有上架 tag，狀態未確認：${pending}
   （build tag：$(git -C "$ROOT" tag -l 'ios/*+*' | tr '\n' ' '))
   跳過它去發 ${requested}，正是 ios/2.0.1 事故的形狀：2.0.0 還在審就先 bump 了下一版。
   先跑 ./ops/release.sh shipped ios 確認上架版本；若該版確實沒上架，請走 resubmit ios 重送，不要跳過。"
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

    local lt_label="上個 tag"
    [[ "$c" != ios ]] || lt_label="已上架 tag"
    echo "■ $c  ${lt_label}：${lt:-（尚未發版）}  檔內版本：$curver"
    # 漂移警示：上個 tag 的版號與版號檔不一致（如 tag api/1.6.0 但 pyproject 0.1.0）→ 發版前先對齊。
    # 比較前把兩段版號（ios pbxproj 慣用 1.6）補成三段再比，避免「1.6 vs 1.6.0」恆觸發警報疲勞。
    local cmpcur="$curver" drift
    [[ "$cmpcur" =~ ^[0-9]+\.[0-9]+$ ]] && cmpcur="$cmpcur.0"
    drift=none
    [[ -n "$lt" ]] && drift="$(classify_version_drift "$basever" "$cmpcur")"
    case "$drift" in
      ahead)
        echo "   ⚠ 版號漂移：上個 tag=${basever} 但檔內=${curver}（發版前先 bump 對齊）" ;;
      mistagged)
        echo "   ⛔ 誤標 tag：${tp}${basever} 高於檔內 ${curver} — 該版號已被撤回，從未發布。"
        echo "      留著它等於宣稱一個從未上架的版號已上架，guard 會以它為基準，"
        echo "      且新版號被迫跳過 ${basever}。正解是刪 tag（勿 bump 對齊）："
        echo "      git push origin :refs/tags/${tp}${basever} && git tag -d ${tp}${basever}" ;;
    esac
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
        # tag 存在 ≠ 該版號上了生產：tag 只推 origin/main（備份），部署看的是 origin/prod。
        if [[ -n "$lt" ]]; then
          if git -C "$ROOT" merge-base --is-ancestor "$lt" origin/prod 2>/dev/null; then
            echo "   ${lt} 已在 origin/prod（該版號已上生產）"
          else
            echo "   ${lt} 尚未進 origin/prod（版號已標記，但沒部署）"
          fi
        fi
      else
        echo "   released：origin/prod 本地未知（尚未 seed 或未 fetch；見 docs/sop/release.md 切換）"
      fi
      echo "   live：curl -s https://wordnexus.lol/api/system/info（欲查生產實跑版本）"
    else
      # 版號字串相等不代表 tag 指對地方：2.0.0 事故時 status 報「無漂移」（tag 2.0.0 =
      # 檔內 2.0.0），而那顆 tag 指著沒上架的 build 5 的 commit。build tag 是唯一能讓
      # 「這顆 build 有沒有被記錄」變成可見狀態的東西，所以在這裡攤開。
      local curbuild btag_now build_tags
      curbuild="$(current_build)"
      echo "   專案版號：MARKETING_VERSION=${curver}  CURRENT_PROJECT_VERSION=${curbuild}"
      build_tags="$(git -C "$ROOT" tag -l 'ios/*+*' --sort=-v:refname | tr '\n' ' ')"
      if [[ -n "${build_tags// /}" ]]; then
        echo "   build tag 對照："
        git -C "$ROOT" tag -l 'ios/*+*' --sort=-v:refname \
          | while IFS= read -r bt; do
              [[ -n "$bt" ]] || continue
              echo "     ${bt} → $(git -C "$ROOT" rev-parse --short "${bt}^{commit}")"
            done
      else
        echo "   build tag 對照：（無）"
      fi
      if valid_semver "$curver" && [[ "$curbuild" =~ ^[0-9]+$ ]]; then
        btag_now="$(ios_build_tag "$curver" "$curbuild")"
        if ! git -C "$ROOT" rev-parse -q --verify "refs/tags/${btag_now}^{commit}" >/dev/null; then
          echo "   ⚠ 目前的 (${curver}, build ${curbuild}) 沒有 build tag ${btag_now}"
          echo "     = 這顆 build 若出過 archive，沒有留下 build→commit 紀錄（Apple 不留歷史，事後無法重建）"
          echo "     出 build 請走 ./ops/release.sh release ios <x.y.z> 或 resubmit ios，它們會封版"
        fi
      fi
      echo "   live：./ops/asc.sh builds（TestFlight 最新 build）+ review-status"
      echo "   上架後：./ops/release.sh shipped ios --yes（依 ASC 物化 ios/<x.y.z>）"
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

# API release versions are one bounded three-file transaction. Each candidate
# is prepared in its destination directory, validated, and mode-matched before
# any tracked file changes. Renames are atomic per file; same-directory backups
# let EXIT/signal handling roll back an unexpected later rename failure.
API_VERSION_PATHS=()
API_VERSION_CANDIDATES=()
API_VERSION_BACKUPS=()
API_VERSION_INSTALLED=0

api_version_cleanup_temps() {
  local path candidates backups
  # macOS ships Bash 3.2, where expanding a declared-but-empty array under
  # nounset raises instead of yielding zero words.
  set +u
  candidates=("${API_VERSION_CANDIDATES[@]}")
  backups=("${API_VERSION_BACKUPS[@]}")
  for path in "${candidates[@]}" "${backups[@]}"; do
    [[ -n "$path" ]] && rm -f "$path"
  done
  set -u
  API_VERSION_CANDIDATES=()
  API_VERSION_BACKUPS=()
}

api_version_rollback() {
  local i rollback_failed=0
  for ((i=API_VERSION_INSTALLED-1; i>=0; i--)); do
    mv -f "${API_VERSION_BACKUPS[$i]}" "${API_VERSION_PATHS[$i]}" || rollback_failed=1
  done
  API_VERSION_INSTALLED=0
  api_version_cleanup_temps
  [[ $rollback_failed -eq 0 ]] || echo "✗ API 版號 transaction rollback 失敗；請立即檢查三個版號檔" >&2
}

prepare_api_version_transaction() {
  local v="$1" root="${KG_ROOT:-$ROOT}" path candidate mode i
  API_VERSION_PATHS=(
    "$root/backend/pyproject.toml"
    "$root/backend/src/kg/api.py"
    "$root/backend/uv.lock"
  )
  API_VERSION_CANDIDATES=()
  API_VERSION_BACKUPS=()
  API_VERSION_INSTALLED=0

  # A readonly target is an operator-visible refusal, even though rename could
  # technically replace it through a writable parent directory.
  for path in "${API_VERSION_PATHS[@]}"; do
    if [[ ! -f "$path" || ! -w "$path" || ! -w "$(dirname "$path")" ]]; then
      api_version_cleanup_temps
      err "API 版號檔不可寫，未修改任何檔案：${path#$root/}"
    fi
    if ! candidate="$(mktemp "${path}.tmp.XXXXXX")"; then
      api_version_cleanup_temps
      err "無法在版號檔旁建立 transaction candidate：${path#$root/}"
    fi
    API_VERSION_CANDIDATES+=("$candidate")
  done

  if ! KG_RELEASE_VERSION="$v" perl -0pe '
    $n = s{^version = "[^"]+"$}{q{version = "} . $ENV{"KG_RELEASE_VERSION"} . q{"}}gme;
    END { exit 1 unless $n == 1 }
  ' "${API_VERSION_PATHS[0]}" > "${API_VERSION_CANDIDATES[0]}"; then
    api_version_cleanup_temps
    err "backend/pyproject.toml 必須恰有一個 project version entry"
  fi
  if ! KG_RELEASE_VERSION="$v" perl -0pe '
    $n = s{version="[^"]*"}{q{version="} . $ENV{"KG_RELEASE_VERSION"} . q{"}}ge;
    END { exit 1 unless $n == 1 }
  ' "${API_VERSION_PATHS[1]}" > "${API_VERSION_CANDIDATES[1]}"; then
    api_version_cleanup_temps
    err "backend/src/kg/api.py 必須恰有一個 API version entry"
  fi
  if ! KG_RELEASE_VERSION="$v" perl -0pe '
    $n = s{(^\[\[package\]\]\nname = "kg"\nversion = ")[^"]+("\nsource = \{ editable = "\." \}$)}
           {$1 . $ENV{"KG_RELEASE_VERSION"} . $2}gme;
    END { exit 1 unless $n == 1 }
  ' "${API_VERSION_PATHS[2]}" > "${API_VERSION_CANDIDATES[2]}"; then
    api_version_cleanup_temps
    err "backend/uv.lock 必須恰有一個 editable kg package entry"
  fi

  for ((i=0; i<3; i++)); do
    path="${API_VERSION_PATHS[$i]}"
    mode="$(stat -f '%Lp' "$path" 2>/dev/null || stat -c '%a' "$path")"
    if ! chmod "$mode" "${API_VERSION_CANDIDATES[$i]}"; then
      api_version_cleanup_temps
      err "無法保留 API 版號檔 mode：${path#$root/}"
    fi
  done
}

commit_api_version_transaction() {
  local i path backup
  for ((i=0; i<3; i++)); do
    path="${API_VERSION_PATHS[$i]}"
    if ! backup="$(mktemp "${path}.bak.XXXXXX")"; then
      api_version_cleanup_temps
      err "無法建立 API 版號 transaction backup：${path#${KG_ROOT:-$ROOT}/}"
    fi
    # Cleanup owns the path as soon as mktemp creates it, including a later
    # cp -p failure.
    API_VERSION_BACKUPS+=("$backup")
    if ! cp -p "$path" "$backup"; then
      api_version_cleanup_temps
      err "無法寫入 API 版號 transaction backup：${path#${KG_ROOT:-$ROOT}/}"
    fi
  done

  trap 'api_version_rollback' EXIT
  trap 'exit 1' HUP INT TERM
  for ((i=0; i<3; i++)); do
    # Count the current slot before mv so a signal in the tiny post-rename
    # window still restores it. Restoring an unchanged slot is harmless.
    API_VERSION_INSTALLED=$((i + 1))
    if ! mv -f "${API_VERSION_CANDIDATES[$i]}" "${API_VERSION_PATHS[$i]}"; then
      err "API 版號 transaction 寫入失敗；已回復先前檔案"
    fi
  done
  API_VERSION_INSTALLED=0
  trap - EXIT HUP INT TERM
  api_version_cleanup_temps
}

# ---- bump：委派 primitive（本地檔案寫入；dry-run 預設，--yes 才寫） ----
cmd_bump() {
  local c="${1:?用法: release.sh bump <api|ios> <x.y.z> [--yes]}" v="${2:-}"
  tag_prefix "$c" >/dev/null
  [[ -n "$v" ]] || err "請提供版本號 x.y.z"
  valid_semver "$v" || err "版本號格式錯誤：${v}（需 x.y.z）"
  if [[ $YES -eq 1 ]]; then
    if [[ "$c" == api ]]; then
      prepare_api_version_transaction "$v"
      commit_api_version_transaction
      echo "✓ API version transaction → ${v}（pyproject.toml + api.py + uv.lock）"
    else
      "$ROOT/ops/release_bump.sh" "$c" "$v" --yes
    fi
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
  # resubmit 走的是「同一個 marketing version 的下一顆 build」，而 guard_ios_new_version
  # 專門擋「換版號」——套在重送上會擋掉唯一正確的那條路。用明示的內部旗標開洞，而不是
  # 把 guard 改成可有可無：預設一定跑，只有 cmd_resubmit 會關掉它。
  if [[ "$c" == ios && $IOS_SAME_VERSION_RESUBMIT -eq 0 ]]; then
    guard_ios_new_version "$v"
  fi

  local tp tag files curver branch build
  IOS_BUILD_TAG_STATE=""   # 每次呼叫重新判定，不吃上一次的殘值
  tp="$(tag_prefix "$c")"
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  [[ "$branch" != HEAD ]] || err "detached HEAD —— 先 checkout 一個分支再發版（避免 push origin HEAD）"
  case "$c" in
    api)
      files=(backend/pyproject.toml backend/src/kg/api.py backend/uv.lock)
      tag="${tp}${v}"
      # preflight
      git -C "$ROOT" rev-parse -q --verify "refs/tags/$tag" >/dev/null \
        && err "tag $tag 已存在（重複發版？換版號或先刪 tag）"
      ;;
    ios)
      files=(ios/BooksAndVocab.xcodeproj/project.pbxproj)
      # iOS 這裡封的是 (version, build)，不是 ios/<x.y.z>。後者代表「上架」，而 upload
      # 完成的那一刻沒有任何人知道它會不會過審——那個 tag 由 `shipped ios` 依 ASC 物化。
      build="$(current_build)"
      [[ "$build" =~ ^[0-9]+$ ]] \
        || err "讀不到 pbxproj 的 CURRENT_PROJECT_VERSION（app target 結構異常）：'${build}'"
      tag="$(ios_build_tag "$v" "$build")"
      check_ios_build_tag "$tag"
      ;;
  esac
  curver="$(current_version "$c")"
  [[ "$curver" == "$v" ]] || err "版號檔目前是 ${curver}，非 ${v} —— 先跑 ./ops/release.sh bump ${c} ${v} --yes"

  echo "component=$c  version=$v  tag=$tag  branch=$branch"
  echo "  將 commit 的檔：${files[*]}"
  echo "  commit message：ops: release $c $v"
  [[ "$c" != ios ]] || echo "  ios/${v}（上架標記）不在此步驟產生 —— 過審後跑 ./ops/release.sh shipped ios"

  if [[ $YES -eq 1 ]]; then
    git -C "$ROOT" add -- "${files[@]}"
    if git -C "$ROOT" diff --cached --quiet -- "${files[@]}"; then
      echo "  版號檔已在目前 HEAD，略過空 release commit；tag 將指向 $(git -C "$ROOT" rev-parse --short HEAD)"
    else
      # pathspec 鎖住 release files，避免把 operator 預先 staged 的無關變更一起提交。
      git -C "$ROOT" commit -m "ops: release $c $v" -- "${files[@]}"
    fi
    if [[ "$IOS_BUILD_TAG_STATE" == idempotent ]]; then
      echo "  ${tag} 已指向 $(git -C "$ROOT" rev-parse --short HEAD)，略過重複 tag（仍會確保推上 origin）"
    else
      git -C "$ROOT" tag "$tag"
    fi
    git -C "$ROOT" push origin "$branch" "$tag"
    echo "✓ 已 commit + tag ${tag} + 推送 origin/${branch}（版號標記+備份；生產部署走 release <backend|ios>）。"
  else
    echo "[dry-run] 未送出。確認無誤後加 --yes 才會 commit + 打 tag + 推送 origin："
    echo "  ./ops/release.sh tag $c $v --yes"
  fi
}

# ---- shipped：把「上架」這個事實從 ASC 取回，join build tag，物化成 ios/<x.y.z> ----
# 這是驗證式，不是背書式：repo 不宣稱它不擁有的事實。
#   誰上架了      → ASC（唯一權威，且只保留當前一筆 → 只能現在問，不快取成 repo 內的事實）
#   誰產生了它    → repo 的 build tag（Apple 會銷毀這個資訊）
#   ios/<x.y.z>   → 上兩者的 join，只在確認上架後才落地
#
# KG_ASC_SHIPPED_CMD 是唯一注入點（測試以 stub 覆寫，整節離線可跑）。
# 契約：stdout 一行 "<marketing-version> <build-number>"；非零 exit = 查不到。
asc_shipped_pair() {
  if [[ -n "${KG_ASC_SHIPPED_CMD:-}" ]]; then
    "$KG_ASC_SHIPPED_CMD"
  else
    "$ROOT/ops/asc_shipped.py"
  fi
}

cmd_shipped() {
  local target="${1:?用法: release.sh shipped ios [--commit <sha>] [--yes]}"
  [[ "$target" == ios ]] \
    || err "shipped 只支援 ios（api 的「已上生產」看 origin/prod，見 ./ops/release.sh status）"
  [[ $# -le 1 ]] || err "多餘參數：${*:2}（版本與 build 由 ASC 決定，不從命令列接受）"

  local pair="" rc=0 ver build btag commit vtag existing manual=0 short_commit
  pair="$(asc_shipped_pair)" || rc=$?
  [[ "$rc" -eq 0 && -n "$pair" ]] \
    || err "查不到 App Store 上架版本（ASC 查詢失敗、憑證/網路不可用，或目前沒有 READY_FOR_SALE）。
   不降級成猜測：修好連線後重跑，或人工確認後用 --commit <sha> 指定。"
  read -r ver build _rest <<<"$pair"
  valid_semver "$ver" \
    || err "ASC 回的 versionString 不是 x.y.z：'${ver}'——不拿它去組 tag 名"
  [[ "$build" =~ ^[0-9]+$ ]] \
    || err "ASC 回的 build number 不是數字：'${build}'——不拿它去組 tag 名"

  btag="$(ios_build_tag "$ver" "$build")"
  if [[ -n "$SHIPPED_COMMIT" ]]; then
    commit="$(git -C "$ROOT" rev-parse -q --verify "${SHIPPED_COMMIT}^{commit}")" \
      || err "--commit ${SHIPPED_COMMIT} 不是有效的 commit"
    manual=1
  else
    commit="$(git -C "$ROOT" rev-parse -q --verify "refs/tags/${btag}^{commit}" || true)"
    [[ -n "$commit" ]] || err "App Store 上架的是 ${ver} build ${build}，但 repo 裡沒有 ${btag}。
   這顆 build 沒有留下 build→commit 紀錄（多半發版於本機制上線前）。Apple 只保留當前
   版本、不留歷史，所以這個對應關係已無法自動重建：人工判定後用
   ./ops/release.sh shipped ios --commit <sha> --yes 指定。"
  fi
  short_commit="$(git -C "$ROOT" rev-parse --short "$commit")"

  vtag="ios/${ver}"
  existing="$(git -C "$ROOT" rev-parse -q --verify "refs/tags/${vtag}^{commit}" || true)"
  if [[ -n "$existing" ]]; then
    if [[ "$existing" == "$commit" ]]; then
      echo "✓ ${vtag} 已指向 ${short_commit}，與 ASC 一致，無需變更。"
      return 0
    fi
    # 一個 released marketing version 最終只會有一顆上架 build（Apple 規則：released
    # 之後要再發必須提高 marketing version），所以這個 tag 天生 immutable。工具不移動它。
    err "${vtag} 已存在且指向 $(git -C "$ROOT" rev-parse --short "$existing")，但 ASC 說上架的是 ${short_commit}。
   上架 tag 是 immutable 的，本工具不移動它——兩者之一是錯的，需要人工裁決。
   確認舊 tag 是錯的之後：
     git tag -d ${vtag} && git push origin :refs/tags/${vtag}
   再重跑 ./ops/release.sh shipped ios --yes"
  fi

  echo "App Store 上架版本=${ver}  build=${build}"
  echo "  ASC 來源：${KG_ASC_SHIPPED_CMD:-ops/asc_shipped.py}"
  if [[ $manual -eq 1 ]]; then
    echo "  ⚠ commit 由 --commit 人工指定：${short_commit}（這是人工斷言，不是查證出來的 join）"
  else
    echo "  commit 來自 build tag ${btag}：${short_commit}"
  fi
  echo "  將建立上架 tag：${vtag} → ${short_commit}"

  if [[ $YES -eq 1 ]]; then
    git -C "$ROOT" tag "$vtag" "$commit"
    if git -C "$ROOT" remote get-url origin >/dev/null 2>&1; then
      git -C "$ROOT" push origin "$vtag"
      echo "✓ 已建立 ${vtag} 並推送 origin（另一台 clone 需要同一份紀錄）。"
    else
      echo "✓ 已建立 ${vtag}（無 origin remote，未推送）。"
    fi
  else
    echo "[dry-run] 未建立。確認無誤後加 --yes："
    echo "  ./ops/release.sh shipped ios${SHIPPED_COMMIT:+ --commit $SHIPPED_COMMIT} --yes"
  fi
}

# ---- resubmit：同版號、新 build 的重送（App Review 被拒 / 未上架就要換 binary）----
# 這條路徑原本是 `bump-build ios --yes` + `ios_release.sh --upload` 兩步手動，**不留任何
# 紀錄**：沒有 release commit、沒有 tag。ios/2.0.0 指著 build 5 的 commit、實際上架的卻是
# 五天後的 build 6，成因就是這裡——腳本從來沒有詞彙描述「同版號的第 N 顆 build」。
# 與 cmd_release 對稱：bump → upload → 封版；upload 失敗不留 commit/tag/push。
cmd_resubmit() {
  local target="${1:?用法: release.sh resubmit ios [--yes]}"
  [[ "$target" == ios ]] \
    || err "resubmit 只支援 ios（api 沒有 build number 概念；改版號用 ./ops/release.sh bump api <x.y.z>）"
  [[ $# -le 1 ]] || err "多餘參數：${*:2}（resubmit 不吃版本號——版號不變才叫重送）"

  local branch curver curbuild newbuild
  branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
  [[ "$branch" == main ]] \
    || err "resubmit 須在 main 執行（目前 ${branch}）—— 它發布本地主幹；feature 改動先 cutover 進 main"
  curver="$(current_version ios)"
  valid_semver "$curver" \
    || err "pbxproj 的 MARKETING_VERSION 是 '${curver}'，不是 x.y.z —— 先跑 ./ops/release.sh bump ios <x.y.z> --yes 對齊成三段"
  curbuild="$(current_build)"
  [[ "$curbuild" =~ ^[0-9]+$ ]] || err "讀不到 pbxproj 的 CURRENT_PROJECT_VERSION：'${curbuild}'"
  newbuild=$((curbuild + 1))

  echo "resubmit ios ${curver}  build ${curbuild} → ${newbuild}  branch=${branch}"
  echo "  計畫（dry-run 預設）："
  echo "    1) bump-build ios（CURRENT_PROJECT_VERSION ${curbuild} → ${newbuild}；MARKETING_VERSION 不動）"
  echo "    2) ios_release.sh --upload（archive + 上傳 TestFlight）⚠ 外部不可逆"
  echo "    3) commit 版號檔 + $(ios_build_tag "$curver" "$newbuild") + push origin ${branch}"
  echo "  ios/${curver}（上架標記）不在本流程產生 —— 過審後跑 ./ops/release.sh shipped ios"

  if [[ $YES -ne 1 ]]; then
    echo "[dry-run] 未執行。確認無誤後加 --yes："
    echo "  ./ops/release.sh resubmit ios --yes"
    return 0
  fi

  cmd_bump_build ios
  # 與 cmd_release 同理：封不下去就別送。TestFlight upload 不可逆。
  check_ios_build_tag "$(ios_build_tag "$curver" "$(current_build)")"
  "$ROOT/ops/ios_release.sh" --upload || err "ios_release --upload 失敗，中止（pbxproj 已 bump 但未 commit/tag）"
  IOS_SAME_VERSION_RESUBMIT=1
  cmd_tag ios "$curver"
  IOS_SAME_VERSION_RESUBMIT=0
  echo "✓ resubmit ios ${curver} build ${newbuild}：已上傳 TestFlight + 封版 tag。"
  echo "  過審上架後記得跑 ./ops/release.sh shipped ios --yes 補上上架 tag。"
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
    echo "    3) tag ${comp} ${v}（upload 成功後才 commit 版號檔 + ios/${v}+<build> build tag + push origin main）"
    echo "    ios/${v}（上架標記）不在本流程產生 —— 過審後跑 ./ops/release.sh shipped ios"
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
    # build tag 衝突要在 upload **之前**發現。TestFlight upload 不可逆，而 cmd_tag 的
    # 拒絕發生在 upload 之後——那等於先送出一顆我們已經知道封不下去的 archive。
    # bump 已經跑完，pbxproj 此刻帶的就是本次 archive 的 (version, build)。
    check_ios_build_tag "$(ios_build_tag "$v" "$(current_build)")"
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
      # 靜默忽略是最糟的下場：operator 以為自己還在背書，實際上那個字串已不影響任何判斷。
      err "--new-version-after-ready 已移除。它存在的理由是舊 ios/<x.y.z> tag 不代表上架，
   只能請 operator 背書；現在該 tag 由 ./ops/release.sh shipped ios 依 ASC 驗證後才產生，
   tag 存在本身就是上架證據，guard 直接檢查、不需要 attestation。
   同版號、新 build 的重送改走 ./ops/release.sh resubmit ios。" ;;
    --commit)
      [[ $# -ge 2 && -n "${2:-}" ]] || err "--commit 需要一個 commit-ish"
      SHIPPED_COMMIT="$2"; shift 2 ;;
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
  shipped)   cmd_shipped ${ARGS[@]+"${ARGS[@]}"} ;;
  resubmit)  cmd_resubmit ${ARGS[@]+"${ARGS[@]}"} ;;
  release)   cmd_release ${ARGS[@]+"${ARGS[@]}"} ;;
  ""|help)   usage ;;
  *)         err "unknown subcommand: ${SUB}（release.sh help 看用法）" ;;
esac
