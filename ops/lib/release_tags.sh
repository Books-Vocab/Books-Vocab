#!/usr/bin/env bash
# release_tags.sh — version tag 語意的單一實作（release.sh 與 release_changelog.sh 共用）。
#
# 為什麼是一份而不是兩份：這段邏輯原本在 release.sh 與 release_changelog.sh 各有一份逐字
# 副本。收緊了 release.sh 那份、漏掉 changelog 那份的後果，是 `changelog ios` 靜默錨到
# build tag、印出「無變更」——沒有錯誤、沒有徵兆，而它就站在 status 建議的
# bump → changelog → release 流程正中間。
#
# 兩種 tag 的語意（完整說明見 ops/release.sh 檔頭）：
#   <prefix>x.y.z        released marketing version
#   ios/x.y.z+<build>    某 (version, build) 的封版 commit —— 只代表出過 archive，不代表上架
# 本檔的 released_last_tag 只認前者。
#
# 這是 sourced library，不獨立執行。

release_tag_prefix() {  # $1=component → 印 tag prefix；未知 component 回非零
  case "$1" in
    api) printf 'api/\n' ;;
    ios) printf 'ios/\n' ;;
    *)   return 1 ;;
  esac
}

# 最新的 released marketing version tag。
# 回傳：0=正常（找不到時印空字串，那是合法狀態：首發、或目前只有 build tag）
#       1=未知 component   2=git 失敗（不靜默當成「沒有 tag」）
release_last_tag() {  # $1=component  $2=repo root
  local tp all line ver
  tp="$(release_tag_prefix "$1")" || return 1
  all="$(git -C "$2" tag -l "${tp}*" --sort=-v:refname)" || return 2
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    # 先剝前綴再驗形狀，不把 prefix 塞進 regex：未來若出現含 `.`/`+` 的 component
    # prefix，塞進去的 `.` 會退化成萬用字元，放行本不該放行的 tag。
    ver="${line#"$tp"}"
    [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
    printf '%s\n' "$line"
    return 0
  done <<< "$all"
  return 0
}
