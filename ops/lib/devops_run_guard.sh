#!/usr/bin/env bash
# Source-only: the one destructive-command predicate for the remote shell-string
# surfaces `run` / `container-run` / `migrate-run`.  Sourced by BOTH entrypoints:
#
#   ops/devops_kg_safe.sh   (the agent-facing wrapper)
#   devops.sh               (the base; cmd_run / cmd_container_run / cmd_migrate_run)
#
# so the wrapper is not the only line of defense: calling `devops.sh run ...`
# directly, or pointing the wrapper at a different base, hits the same check.
# (P0 2026-10-09: docs/runbook/incidents/2026-10-09-kg-data-deleted-by-test.md.)
#
# Public API
#   devops_run_is_blocked <sub> <cmd>      exit 0 = blocked, 1 = allowed
#   devops_run_guard_enforce <sub> <cmd>   prints "✗ blocked dangerous command" + exit 1 when blocked
#   <sub> is run | container-run | migrate-run.  container-run / migrate-run (and any
#   `docker exec`) execute with cwd /app, so relative paths there ARE the app tree.
#
# Design: two tiers.
#   1. Legacy roots (`/`, `~`, `$HOME`, /home/ubuntu, /Users/<x>, /root, ...): recursive
#      `rm`, `find -delete`, redirect/tee/truncate/dd — unchanged semantics.
#   2. Protected NAMES (kg-data, kg-prod, /app/data, /app itself, docker volumes): ANY
#      destructive verb that references one, in ANY path form — absolute, `~`, `~user`,
#      `$HOME`, relative, `..`, globbed (`kg-d*`, `~/*`), brace-expanded, or relative to a
#      directory a previous clause `cd`-ed into.  Destructive verbs: rm rmdir unlink mv
#      truncate shred, find -delete, git clean, rsync (--delete, or as destination), cp/
#      install/ln (as destination), tar x, chmod/chown -R, tee, `>`/`>>`, dd of=, and the
#      python equivalents (rmtree, os.remove, ...).
#
# NOT a sandbox: a deny-list cannot see through eval/base64/variable indirection or an
# interpreter that deletes without a verb (sqlite3 DELETE, python open().write).  It
# is the second seal; the first is that tests never reach production
# (ops/lib/hermetic_ops_test.sh + the KG_OPS_TEST tripwire in devops.sh).
# Bash 3.2 compatible (macOS /bin/bash): no associative arrays, no ${x,,}.

if [[ -n "${_KG_DEVOPS_RUN_GUARD_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
_KG_DEVOPS_RUN_GUARD_LOADED=1

devops_run_guard_enforce() {  # <sub> <cmd>
  if devops_run_is_blocked "$1" "$2"; then
    echo "✗ blocked dangerous command" >&2
    echo "  protected: kg-data, kg-prod, /app/data, /app, home/root dirs, docker volumes (docs/policy/safety.md)" >&2
    exit 1
  fi
}

devops_run_is_blocked() {  # <sub> <cmd>
  local sub="$1" raw="$2"
  if _devops_run_legacy_blocked "$raw"; then return 0; fi
  if _devops_run_names_blocked "$sub" "$raw"; then return 0; fi
  return 1
}

# ── Tier 1: legacy protected roots (behavior preserved; `~user` added) ────────
_devops_run_legacy_blocked() {
  # Normalise so equivalent-but-differently-typed destructive commands can't
  # slip past a literal match:
  #   - lowercase (RM -RF)
  #   - drop quotes/backticks ("/home/ubuntu", '/')
  #   - ${HOME} brace form -> $home
  #   - collapse repeated slashes (/home//ubuntu)
  #   - turn shell separators ; | & ( ) into spaces so a protected path is
  #     always whitespace/EOL/'>'-bounded (rm -rf /home/ubuntu;)
  local cmd
  cmd="$(printf '%s' "$1" \
    | LC_ALL=C tr '[:upper:]' '[:lower:]' \
    | LC_ALL=C tr -d '\042\047\140' \
    | sed -E 's#\$\{home\}#$home#g; s#/+#/#g; s/[;|&()]/ /g')"

  # delete-user CLI
  [[ "$cmd" =~ delete-user ]] && return 0

  # Docker destructive cleanup: prune (system/volume/image/builder), volume rm,
  # and `compose down` with volume removal — all cause prod data loss.
  [[ "$cmd" =~ docker[[:space:]]+(system|volume|image|builder)[[:space:]]+prune ]] && return 0
  [[ "$cmd" =~ docker[[:space:]]+volume[[:space:]]+rm[[:space:]] ]] && return 0
  if [[ "$cmd" =~ (^|[[:space:]])down([[:space:]]|$) ]] \
     && [[ "$cmd" =~ (^|[[:space:]])(-v|--volume|--volumes)([[:space:]]|=|$) ]]; then
    return 0
  fi

  # Reference to a protected production path. Bare `/`, `~`, `~user`, `$HOME` need a
  # trailing boundary so ordinary paths (/tmp/foo) don't match; named dirs
  # match themselves or any sub-path.
  # Bare `/` includes `*` and `.` in its trailing boundary so `rm -rf /*` and
  # `/.` (machine-wipe equivalents) are caught, not just a lone `rm -rf /`.
  local prot='(/([[:space:]>*.]|$)|~[^[:space:]/>]*([[:space:]/>]|$)|\$home([[:space:]/>]|$)|/home/ubuntu([[:space:]/>]|$)|/users(/[^[:space:]/]+)?([[:space:]/>]|$)|/root([[:space:]/>]|$)|/app/data([[:space:]/>]|$)|knowledge_graph_api|knowledge-graph-api_data)'

  # Recursive `rm` (any flag order/long form; also /bin/rm) at a protected path.
  if [[ "$cmd" =~ (^|[[:space:]]|/)rm[[:space:]] ]] \
     && [[ "$cmd" =~ ((^|[[:space:]])-[a-z]*r[a-z]*([[:space:]]|$)|--recursive|--no-preserve-root) ]] \
     && [[ "$cmd" =~ [[:space:]]$prot ]]; then
    return 0
  fi

  # find-based recursive deletion at a protected path.
  if [[ "$cmd" =~ (^|[[:space:]]|/)find[[:space:]] ]] \
     && [[ "$cmd" =~ (-delete|-exec[[:space:]]+rm) ]] \
     && [[ "$cmd" =~ [[:space:]]$prot ]]; then
    return 0
  fi

  # Clobbering a protected file: redirect, tee, truncate, or dd of=.
  [[ "$cmd" =~ \>[[:space:]]*$prot ]] && return 0
  if [[ "$cmd" =~ (^|[[:space:]]|/)(truncate|dd|tee)[[:space:]] ]] && [[ "$cmd" =~ $prot ]]; then
    return 0
  fi

  return 1
}

# ── Tier 2: protected NAMES in any path form ──────────────────────────────────

# Is word <w> a reference to a protected path?  <st> is the clause's cwd state:
#   home       default cwd of a host `run` (the user's home; kg-data/kg-prod live there)
#   app        default cwd inside the container (/app; ./data is the production volume)
#   protected  a previous clause cd-ed into a protected dir (everything relative is inside it)
#   other      cd-ed somewhere unprotected (only the protected NAMES still count)
# exit 0 = protected.
_dg_ref_protected() {  # <word> <state>
  local p w="$1" st="$2"
  [[ "$w" == -* && "$w" != *=* ]] && return 1          # a bare option, not a path
  w="${w#>}"
  for p in "$w" "${w##*=}"; do
    [[ -n "$p" ]] || continue
    _dg_path_protected "$p" "$st" && return 0
  done
  return 1
}

_dg_glob_hits() {  # <component> <name...>  — does glob component match any of the names?
  local comp="$1" name
  shift
  case "$comp" in *'*'*|*'?'*|*'['*) ;; *) return 1 ;; esac
  for name in "$@"; do
    # shellcheck disable=SC2053  # unquoted on purpose: the component IS the glob
    [[ "$name" == $comp ]] && return 0
  done
  return 1
}

_dg_path_protected() {  # <path> <state>
  local p="$1" st="$2" kind rest i n comp prev
  local -a comps
  while [[ "$p" == */ && "${#p}" -gt 1 ]]; do p="${p%/}"; done
  case "$p" in
    '~'*)
      kind=home
      if [[ "$p" == */* ]]; then rest="${p#*/}"; else rest=""; fi ;;
    '$home'*)
      kind=home; rest="${p#\$home}"; rest="${rest#/}" ;;
    '$'*) return 1 ;;                                   # unresolved variable: caller's rule
    /*) kind=abs; rest="${p#/}" ;;
    *) kind=rel; rest="$p" ;;
  esac
  if [[ -z "$rest" ]]; then
    # `~`, `~user`, `$home`, `/` — the dir itself.  (`.` is handled in the rel branch.)
    [[ "$kind" == home || "$kind" == abs ]] && return 0
  fi
  IFS=/ read -r -a comps <<<"$rest"
  n=${#comps[@]}

  # /app and everything under it (incl. /app/data); glob forms (/ap?, /a*).
  if [[ "$kind" == abs && "$n" -ge 1 ]]; then
    [[ "${comps[0]}" == app ]] && return 0
    _dg_glob_hits "${comps[0]}" app && return 0
    # a glob directly at / (rm /*) can hit anything
    _dg_glob_hits "${comps[0]}" kg-data kg-prod app users home && return 0
  fi

  # The protected names, wherever they sit in the path.
  i=0
  while [[ "$i" -lt "$n" ]]; do
    comp="${comps[$i]}"
    case "$comp" in
      kg-data|kg-prod) return 0 ;;
    esac
    # Globs only count where they can actually hit the data: directly under a home
    # dir (~, $HOME, /Users/<u>, /home/<u>) or the cwd when cwd is home-ish.
    if _dg_glob_hits "$comp" kg-data kg-prod; then
      case "$kind" in
        home) [[ "$i" -eq 0 ]] && return 0 ;;
        abs)
          case "${comps[0]}" in
            users|home) [[ "$i" -eq 2 ]] && return 0 ;;
          esac ;;
        rel)
          [[ "$i" -eq 0 ]] && case "$st" in home|protected) return 0 ;; esac ;;
      esac
    fi
    i=$((i + 1))
  done

  if [[ "$kind" == rel ]]; then
    # Drop leading ./ components: `./data` is `data`, `.` is the cwd itself.
    i=0
    while [[ "$i" -lt "$n" && ( "${comps[$i]}" == "." || -z "${comps[$i]}" ) ]]; do i=$((i + 1)); done
    case "$st" in
      protected) return 0 ;;                            # anything relative is inside the protected dir
      home|app)
        [[ "$i" -ge "$n" ]] && return 0                 # the cwd itself (rm -rf . / find . -delete)
        [[ "${comps[$i]}" == ".." ]] && return 0        # its parent
        if [[ "$st" == app ]]; then
          [[ "${comps[$i]}" == data ]] && return 0      # cwd /app: ./data is the production volume
          _dg_glob_hits "${comps[$i]}" data && return 0
        fi ;;
    esac
  fi
  return 1
}

# New cwd state after `cd <arg>` (or pushd).  <cur> is the state before.
_dg_cd_state() {  # <arg> <cur> <container 0|1>
  local arg="$1" cur="$2" container="$3"
  case "$arg" in
    ''|'~'|'$home')
      if [[ "$container" -eq 1 ]]; then echo other; else echo home; fi
      return 0 ;;
    -) echo "$cur"; return 0 ;;
  esac
  if _dg_path_protected "$arg" "$cur"; then echo protected; return 0; fi
  case "$arg" in
    /*|'~'*|'$'*) echo other ;;
    *)
      case "$cur" in
        protected|app) echo "$cur" ;;                    # a subdir of /app or a protected dir
        *) echo other ;;
      esac ;;
  esac
}

_devops_run_names_blocked() {  # <sub> <cmd>
  local sub="$1" raw="$2" cmd container=0 state clause rc=1 noglob=0
  local -a words
  # Clause-aware normalisation (the legacy tier flattens separators; here `;`, `&&`,
  # `||`, `&`, newline start a NEW clause so `cd X && rm Y` can be tracked, while a pipe
  # stays inside one clause so `ls kg-data | xargs rm -rf` is one unit).
  # BSD sed has no \n in replacements, so clause breaks go through tr.
  cmd="$(printf '%s' "$raw" \
    | LC_ALL=C tr '[:upper:]' '[:lower:]' \
    | LC_ALL=C tr -d '\042\047\140\134' \
    | sed -E 's#\$\{([a-z_][a-z0-9_]*)\}#$\1#g; s#/+#/#g; s/&&/;/g; s/\|\|/;/g; s/>/ > /g' \
    | LC_ALL=C tr ';&' '\n\n' \
    | LC_ALL=C tr '|(){},' '      ')"

  case "$sub" in container-run|migrate-run) container=1 ;; esac
  if [[ "$cmd" =~ docker(-|[[:space:]]+)(compose[[:space:]]+)?exec ]]; then container=1; fi
  if [[ "$container" -eq 1 ]]; then state=app; else state=home; fi

  [[ $- == *f* ]] && noglob=1
  set -f
  while IFS= read -r clause; do
    words=($clause)
    if _dg_clause_blocked "$container"; then rc=0; break; fi
  done <<<"$cmd"
  [[ "$noglob" -eq 1 ]] || set +f
  return "$rc"
}

# Evaluates ${words[@]} against and updates the caller's $state (dynamic scope).
_dg_clause_blocked() {  # <container>
  local container="$1" n=${#words[@]} i w base nxt lastw
  local v1=0 find=0 del=0 rs=0 rsdel=0 v2=0 chm=0 rec=0 git=0 clean=0 tar_ex=0 tee_i=-1
  local ed=0 inplace=0 sqlt=0 sqlw=0

  [[ "$n" -gt 0 ]] || return 1

  # cd / pushd anywhere in the clause (sh -c 'cd /app') moves the cwd state.
  i=0
  while [[ "$i" -lt "$n" ]]; do
    case "${words[$i]}" in
      cd|pushd)
        nxt=""
        if [[ $((i + 1)) -lt "$n" ]]; then nxt="${words[$((i + 1))]}"; fi
        [[ "$nxt" == -* ]] && nxt=""
        state="$(_dg_cd_state "$nxt" "$state" "$container")" ;;
    esac
    i=$((i + 1))
  done

  i=0
  while [[ "$i" -lt "$n" ]]; do
    w="${words[$i]}"; base="${w##*/}"
    case "$base" in
      rm|rmdir|unlink|mv|truncate|shred) v1=1 ;;
      find) find=1 ;;
      rsync) rs=1 ;;
      cp|install|ln) v2=1 ;;
      chmod|chown|chgrp) chm=1 ;;
      sed|perl|ruby) ed=1 ;;
      sqlite3|sqlite) sqlt=1 ;;
      git) git=1 ;;
      clean) clean=1 ;;
      tee) tee_i=$i ;;
      tar)
        if [[ $((i + 1)) -lt "$n" ]]; then
          nxt="${words[$((i + 1))]}"
          if [[ "$nxt" =~ ^-?[a-z]*x[a-z]*$ || "$nxt" == --extract || "$nxt" == --get ]]; then tar_ex=1; fi
        fi ;;
    esac
    case "$w" in
      -delete) del=1 ;;
      --delete*|--remove-source-files) rsdel=1 ;;
      --recursive) rec=1 ;;
      --in-place*) inplace=1 ;;
      -*)
        if [[ "$w" =~ ^-[a-z]*r[a-z]*$ ]]; then rec=1; fi
        if [[ "$w" =~ ^-[a-z]*i([^a-z]|$) ]]; then inplace=1; fi ;;
      delete|drop|update|insert|alter|vacuum|replace) sqlw=1 ;;
    esac
    case "$w" in
      *rmtree*|*os.remove*|*os.unlink*|*os.rmdir*|*os.rename*|*shutil.move*|*.unlink|*.rmdir) v1=1 ;;
    esac
    i=$((i + 1))
  done

  # Path-bearing destructive verbs: any reference in the clause is enough.
  if [[ "$v1" -eq 1 || ( "$find" -eq 1 && "$del" -eq 1 ) || ( "$rs" -eq 1 && "$rsdel" -eq 1 ) \
        || ( "$chm" -eq 1 && "$rec" -eq 1 ) || "$tar_ex" -eq 1 || ( "$git" -eq 1 && "$clean" -eq 1 ) \
        || ( "$ed" -eq 1 && "$inplace" -eq 1 ) || ( "$sqlt" -eq 1 && "$sqlw" -eq 1 ) ]]; then
    [[ "$state" == protected ]] && return 0                # cwd is inside a protected dir
    for w in "${words[@]}"; do
      _dg_ref_protected "$w" "$state" && return 0
      # A target we cannot resolve (`rm -rf $DATA_DIR`): refuse rather than guess.
      [[ "$w" =~ ^\$[a-z_] && "$w" != '$home'* ]] && return 0
    done
  fi

  # Destination-style verbs: only the last operand is written.
  if [[ "$v2" -eq 1 || "$rs" -eq 1 ]]; then
    lastw=""
    i=$((n - 1))
    while [[ "$i" -ge 0 ]]; do
      w="${words[$i]}"
      if [[ "$w" != -* ]]; then lastw="$w"; break; fi
      i=$((i - 1))
    done
    if [[ -n "$lastw" ]]; then _dg_ref_protected "$lastw" "$state" && return 0; fi
  fi

  # tee FILE...: every operand after tee.
  if [[ "$tee_i" -ge 0 ]]; then
    i=$((tee_i + 1))
    while [[ "$i" -lt "$n" ]]; do
      _dg_ref_protected "${words[$i]}" "$state" && return 0
      i=$((i + 1))
    done
  fi

  # `> FILE` / `>> FILE` and `dd of=FILE`.
  i=0
  while [[ "$i" -lt "$n" ]]; do
    w="${words[$i]}"
    if [[ "$w" == '>' && $((i + 1)) -lt "$n" ]]; then
      _dg_ref_protected "${words[$((i + 1))]}" "$state" && return 0
    fi
    if [[ "$w" == of=* ]]; then
      _dg_ref_protected "$w" "$state" && return 0
    fi
    i=$((i + 1))
  done
  return 1
}
