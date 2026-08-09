#!/usr/bin/env bash
# Shared iOS build/install provenance primitives.

kg_ios_shared_derived_data_root() {
  local project_root="$1"
  local git_common_dir

  if [[ -n "${KG_IOS_BUILD_DERIVED_DATA_ROOT:-}" ]]; then
    printf '%s\n' "$KG_IOS_BUILD_DERIVED_DATA_ROOT"
    return 0
  fi

  git_common_dir="$(git -C "$project_root" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
  if [[ -n "$git_common_dir" && -d "$git_common_dir" ]]; then
    printf '%s/.cache/ios-build-derived-data\n' "$(dirname "$git_common_dir")"
  else
    printf '%s/.cache/ios-build-derived-data\n' "$project_root"
  fi
}

kg_ios_install_sdk_suffix() {
  case "$1" in
    simulator) printf '%s\n' iphonesimulator ;;
    device) printf '%s\n' iphoneos ;;
    *) return 64 ;;
  esac
}

kg_ios_install_app_path() {
  local derived_data_root="$1" configuration="$2" mode="$3"
  local sdk_suffix
  sdk_suffix="$(kg_ios_install_sdk_suffix "$mode")" || return $?
  printf '%s/Build/Products/%s-%s/BooksAndVocab.app\n' \
    "$derived_data_root" "$configuration" "$sdk_suffix"
}

kg_ios_install_provenance_path() {
  printf '%s.kg-provenance.json\n' "$1"
}

kg_ios_write_install_provenance() {
  local project_root="$1" derived_data_root="$2" configuration="$3" destination="$4"
  local sdk_suffix app_path sidecar tmp head

  # Catalyst and other non-iOS compile targets are not installable by this
  # entrypoint; they do not get an iOS install sidecar.
  if [[ "$destination" == *"platform=iOS Simulator"* ]]; then
    sdk_suffix=iphonesimulator
  elif [[ "$destination" == *"platform=iOS"* ]]; then
    sdk_suffix=iphoneos
  else
    return 0
  fi

  head="$(git -C "$project_root" rev-parse HEAD 2>/dev/null)" || {
    echo "[ios_build] error: cannot resolve current HEAD for install provenance" >&2
    return 1
  }
  app_path="$derived_data_root/Build/Products/$configuration-$sdk_suffix/BooksAndVocab.app"
  sidecar="$(kg_ios_install_provenance_path "$app_path")"
  [[ -d "$app_path" ]] || {
    echo "[ios_build] error: build succeeded but installable app is missing: $app_path" >&2
    return 1
  }

  tmp="$sidecar.tmp.$$"
  if ! jq -n \
    --arg schema "kg.ios.install-provenance.v1" \
    --arg projectRoot "$project_root" \
    --arg head "$head" \
    --arg configuration "$configuration" \
    --arg destination "$destination" \
    --arg builtAt "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
    --arg artifact "$app_path" \
    '{schema:$schema, projectRoot:$projectRoot, head:$head,
      configuration:$configuration, destination:$destination,
      builtAt:$builtAt, artifact:$artifact}' >"$tmp"; then
    rm -f "$tmp"
    echo "[ios_build] error: failed to write install provenance: $sidecar" >&2
    return 1
  fi
  if ! mv "$tmp" "$sidecar"; then
    rm -f "$tmp"
    echo "[ios_build] error: failed to publish install provenance: $sidecar" >&2
    return 1
  fi
  echo "[ios_build] install provenance=$sidecar head=$head"
}

kg_ios_validate_install_provenance() {
  local project_root="$1" app_path="$2" sidecar="$3"
  local current_head artifact_root='<missing>' artifact_head='<missing>'

  current_head="$(git -C "$project_root" rev-parse HEAD 2>/dev/null || true)"
  if [[ -f "$sidecar" ]]; then
    artifact_root="$(jq -r '.projectRoot // "<missing>"' "$sidecar" 2>/dev/null || printf '<invalid>')"
    artifact_head="$(jq -r '.head // "<missing>"' "$sidecar" 2>/dev/null || printf '<invalid>')"
  fi

  printf '[ios_install] artifact source: worktree=%s head=%s\n' "$artifact_root" "$artifact_head"
  printf '[ios_install] current HEAD: worktree=%s head=%s\n' "$project_root" "${current_head:-<unavailable>}"

  [[ -d "$app_path" ]] || {
    echo "[ios_install] error: app bundle not found: $app_path" >&2
    return 1
  }
  [[ -n "$current_head" && -f "$sidecar" ]] || {
    echo "[ios_install] error: app has no install provenance sidecar: $sidecar" >&2
    return 1
  }
  if ! jq -e \
    --arg projectRoot "$project_root" \
    --arg head "$current_head" \
    '.schema == "kg.ios.install-provenance.v1" and
     (.projectRoot | type) == "string" and (.head | type) == "string" and
     .projectRoot == $projectRoot and .head == $head' \
    "$sidecar" >/dev/null 2>&1; then
    echo "[ios_install] error: install provenance does not match current worktree HEAD" >&2
    return 1
  fi
  printf '[ios_install] verified HEAD=%s\n' "$current_head"
}
