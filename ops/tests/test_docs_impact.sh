#!/usr/bin/env bash
# Regression tests for registry-backed docs impact hints.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

tmpdir="$(mktemp -d "${TMPDIR:-/tmp}/kg_docs_impact.XXXXXX")"
trap 'rm -rf "$tmpdir"' EXIT

./ops/docs_impact.py --help >"$tmpdir/help.out"
grep -q "match_type" "$tmpdir/help.out"

./ops/docs_impact.py --files ops/docs_lint.sh >"$tmpdir/ops.out"
grep -q "reference.tech_index" "$tmpdir/ops.out"
grep -q "sop.doc_sync" "$tmpdir/ops.out"
if grep -q "contract.host_topology" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/ops.out"; then
  echo "docs tooling changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files docs/registry.yml >"$tmpdir/registry.out"
grep -q "sop.doc_sync" "$tmpdir/registry.out"

./ops/docs_impact.py --files CLAUDE.md >"$tmpdir/agent_guide.out"
grep -q "sop.doc_sync" "$tmpdir/agent_guide.out"
grep -q "sop.docs_dogfood" "$tmpdir/agent_guide.out"
grep -q "sop.review_discipline" "$tmpdir/agent_guide.out"

./ops/docs_impact.py --files backend/tests/test_api.py >"$tmpdir/backend_tests.out"
grep -q "reference.testing_backend_strategy" "$tmpdir/backend_tests.out"
if grep -q "policy.safety" "$tmpdir/backend_tests.out"; then
  echo "backend test changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/backend_tests.out"; then
  echo "backend test changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "reference.tech_index" "$tmpdir/backend_tests.out"; then
  echo "backend test changes should not imply tech index impact" >&2
  exit 1
fi
if grep -q "sop.backend" "$tmpdir/backend_tests.out"; then
  echo "backend test changes should not imply backend workflow impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/backend_tests.out"; then
  echo "backend test changes should not imply deploy workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/ios_release.sh backend/src/kg/routers/vocab.py >"$tmpdir/smoke.out"
grep -q "reference.testing_smoke_checklist" "$tmpdir/smoke.out"

./ops/docs_impact.py --files backend/src/kg/llm/providers.py .claude/skills/billing/SKILL.md >"$tmpdir/cost.out"
grep -q "reference.cost_baseline" "$tmpdir/cost.out"
grep -q "sop.cost_review" "$tmpdir/cost.out"
if grep -q "contract.card_format" "$tmpdir/cost.out"; then
  echo "provider pricing changes should not imply card format impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/cost.out"; then
  echo "provider pricing changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/cost.out"; then
  echo "provider pricing changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/cost.out"; then
  echo "provider pricing changes should not imply deploy workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ios/BooksAndVocab/Services/AuthManager.swift backend/src/kg/auth_service.py >"$tmpdir/architecture.out"
grep -q "sop.architecture" "$tmpdir/architecture.out"

./ops/docs_impact.py --files ops/kg_backup.sh ops/cron/kg-backup.cron ops/backup_verify.sh >"$tmpdir/backup.out"
grep -q "sop.backup" "$tmpdir/backup.out"
grep -q "sop.backup_restore" "$tmpdir/backup.out"

./ops/docs_impact.py --files ops/i18n_lint.sh ios/BooksAndVocab/Localization/L10n.swift ios/BooksAndVocab/en.lproj/Localizable.stringsdict >"$tmpdir/i18n.out"
grep -q "sop.i18n_lint" "$tmpdir/i18n.out"
grep -q "sop.i18n_plural_keys" "$tmpdir/i18n.out"

./ops/docs_impact.py --files ops/i18n_lint.sh >"$tmpdir/i18n_tool.out"
grep -q "sop.i18n_lint" "$tmpdir/i18n_tool.out"
if grep -q "contract.host_topology" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.backend" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply backend workflow impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/i18n_tool.out"; then
  echo "i18n lint changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files lab/podcast/pipeline.py ops/podcast_upload.sh .claude/skills/podcast/SKILL.md >"$tmpdir/podcast_pipeline.out"
grep -q "sop.podcast_pipeline" "$tmpdir/podcast_pipeline.out"

./ops/docs_impact.py --files ops/podcast_upload.sh >"$tmpdir/podcast_upload.out"
grep -q "sop.podcast_pipeline" "$tmpdir/podcast_upload.out"
if grep -q "contract.host_topology" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.backend" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply backend workflow impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/podcast_upload.out"; then
  echo "podcast upload changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files lab/llm_eval/prompts/manifest.yaml lab/llm_eval/llm_eval/scoring.py >"$tmpdir/llm_eval.out"
grep -q "reference.llm_eval" "$tmpdir/llm_eval.out"
grep -q "sop.llm_eval" "$tmpdir/llm_eval.out"

./ops/docs_impact.py --files ops/ios_release.sh >"$tmpdir/ios_release.out"
grep -q "sop.ios" "$tmpdir/ios_release.out"
grep -q "reference.testing_smoke_checklist" "$tmpdir/ios_release.out"
if grep -q "contract.host_topology" "$tmpdir/ios_release.out"; then
  echo "iOS release script changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/ios_release.out"; then
  echo "iOS release script changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "sop.backend" "$tmpdir/ios_release.out"; then
  echo "iOS release script changes should not imply backend workflow impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/ios_release.out"; then
  echo "iOS release script changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/ios_release.out"; then
  echo "iOS release script changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ios/BooksAndVocab/Views/Reader/ReaderView.swift >"$tmpdir/ios.out"
if grep -q "contract.sync_lifecycle" "$tmpdir/ios.out"; then
  echo "ordinary reader view changes should not imply sync lifecycle contract impact" >&2
  exit 1
fi
grep -q "reference.feature_boundary.reader" "$tmpdir/ios.out"

./ops/docs_impact.py --files ios/BooksAndVocab/Views/Settings/SettingsView.swift >"$tmpdir/settings.out"
if grep -q "contract.sync_lifecycle" "$tmpdir/settings.out"; then
  echo "ordinary settings view changes should not imply sync lifecycle contract impact" >&2
  exit 1
fi
grep -q "reference.feature_boundary.settings" "$tmpdir/settings.out"

./ops/docs_impact.py --files ios/BooksAndVocab/Services/KGService+Sync.swift ios/BooksAndVocab/Views/Vocabulary/Scenes/SyncCoordinator.swift >"$tmpdir/sync_sources.out"
grep -q "contract.sync_lifecycle" "$tmpdir/sync_sources.out"

./ops/docs_impact.py --files ios/BooksAndVocab/UIComponents/AppShellComponents.swift >"$tmpdir/ui_components.out"
grep -q "reference.ui_components" "$tmpdir/ui_components.out"
grep -q "reference.ui_state_matrix" "$tmpdir/ui_components.out"

./ops/docs_impact.py --files ios/BooksAndVocab/Models/AppMetrics.swift ops/ui_token_lint.sh >"$tmpdir/ui_design.out"
grep -q "sop.ui_design" "$tmpdir/ui_design.out"
grep -q "reference.ui_review_checklist" "$tmpdir/ui_design.out"

./ops/docs_impact.py --files design-system/tokens.json ops/gen_figma_sets.py ops/verify_design_system.sh >"$tmpdir/figma_tokens.out"
grep -q "sop.figma_token_workflow" "$tmpdir/figma_tokens.out"
grep -q "sop.ui_design" "$tmpdir/figma_tokens.out"

./ops/docs_impact.py --files ops/ui_token_lint.sh >"$tmpdir/ui_token_lint.out"
grep -q "sop.ui_design" "$tmpdir/ui_token_lint.out"
grep -q "reference.ui_review_checklist" "$tmpdir/ui_token_lint.out"
if grep -q "contract.host_topology" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply host topology impact" >&2
  exit 1
fi
if grep -q "policy.safety" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q "reference.product_surface" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply product surface impact" >&2
  exit 1
fi
if grep -q "sop.backend" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply backend workflow impact" >&2
  exit 1
fi
if grep -q "sop.deploy" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q "sop.debug" "$tmpdir/ui_token_lint.out"; then
  echo "UI token lint changes should not imply debug workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files README.md >"$tmpdir/none.out"
grep -q "docs_impact: no registry impacts" "$tmpdir/none.out"

./ops/docs_impact.py --files backend/src/kg/routers/vocab.py --json >"$tmpdir/backend.json"
grep -q '"id": "reference.tech_index"' "$tmpdir/backend.json"
grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/backend.json"
if grep -q '"id": "policy.safety"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply production safety impact" >&2
  exit 1
fi
if grep -q '"id": "sop.deploy"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply deploy workflow impact" >&2
  exit 1
fi
if grep -q '"id": "sop.backend"' "$tmpdir/backend.json"; then
  echo "ordinary backend router changes should not imply backend workflow impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/devops_kg_safe.sh --json >"$tmpdir/devops_safe.json"
grep -q '"id": "policy.safety"' "$tmpdir/devops_safe.json"
grep -q '"id": "runbook.system"' "$tmpdir/devops_safe.json"
grep -q '"id": "reference.tech_index"' "$tmpdir/devops_safe.json"
grep -q '"id": "sop.deploy"' "$tmpdir/devops_safe.json"
grep -q '"id": "sop.debug"' "$tmpdir/devops_safe.json"
if grep -q '"id": "contract.host_topology"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply host topology impact by default" >&2
  exit 1
fi
if grep -q '"id": "reference.product_surface"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply product surface impact by default" >&2
  exit 1
fi
if grep -q '"id": "sop.backend"' "$tmpdir/devops_safe.json"; then
  echo "safe wrapper changes should not imply backend workflow impact by default" >&2
  exit 1
fi

./ops/docs_impact.py --files ios/BooksAndVocab/Models/Book.swift --json >"$tmpdir/book_model.json"
grep -q '"id": "reference.feature_boundary.bookshelf"' "$tmpdir/book_model.json"
if grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/book_model.json"; then
  echo "book model changes should not imply vocabulary sync lifecycle impact by default" >&2
  exit 1
fi
if grep -q '"id": "sop.ios"' "$tmpdir/book_model.json"; then
  echo "ordinary iOS model changes should not imply iOS workflow SOP impact" >&2
  exit 1
fi

# generator: 欄的輸出（docs_impact.py 的人類與 JSON 兩條輸出路徑）——用**合成 registry**
# 驗，不用真實 registry。這兩條斷言原本拿 generated.ios_baseline 當素材，而那筆 entry 已於
# IMP-20260808-b63206 隨產物移出版控而刪除，真實 registry 今天一筆 kind=generated 都沒有。
# 若跟著把斷言刪掉，這段輸出邏輯就會變成沒有任何測試碰得到的死角，等下一個人加回 generated
# entry 時才發現它壞了。--registry 旗標本來就在（docs_impact.py:307），改道即可。
cat > "$tmpdir/synthetic_registry.yml" <<'SYNTHREG'
documents:
  - id: generated.probe
    path: docs/snapshot/probe_not_on_disk.md
    kind: generated
    authority: generated
    generator: ops/probe_generator.sh
    triggers:
      - probe_changed
    sources:
      - ios/BooksAndVocab/Models/
  - id: reference.plain_probe
    path: docs/reference/probe_not_on_disk.md
    kind: reference
    authority: SoT
    triggers:
      - probe_changed
    sources:
      - ios/BooksAndVocab/Models/
SYNTHREG
./ops/docs_impact.py --registry "$tmpdir/synthetic_registry.yml" \
  --files ios/BooksAndVocab/Models/Book.swift >"$tmpdir/synth.out"
grep -q "generator=ops/probe_generator.sh" "$tmpdir/synth.out"
./ops/docs_impact.py --registry "$tmpdir/synthetic_registry.yml" \
  --files ios/BooksAndVocab/Models/Book.swift --json >"$tmpdir/synth.json"
grep -q '"generator": "ops/probe_generator.sh"' "$tmpdir/synth.json"
# 反面：沒宣告 generator 的 entry 不得長出 generator 欄。少了這條，上面兩條會被「對每筆
# entry 都印同一個字串」這種壞法滿足——同一份輸出裡兩筆 entry，只有一筆該帶這個欄位。
#
# 數 key 而不是 `grep -c`：後者數的是**行**，只因為 --json 今天是 pretty-print 才碰巧等價；
# 哪天輸出改成 compact，兩個 generator 會擠在同一行而守衛無聲弱化成「>=1」。
synth_impacts="$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
impacts = d["impacts"]
print(len(impacts), sum(1 for i in impacts if "generator" in i))
' "$tmpdir/synth.json")"
if [ "$synth_impacts" != "2 1" ]; then
  echo "synthetic registry should yield 2 impacts of which exactly 1 carries generator; got '$synth_impacts'" >&2
  cat "$tmpdir/synth.json" >&2
  exit 1
fi
# 人類路徑的同一條反面（原本只有 JSON 那邊有）。
if [ "$(grep -c 'generator=' "$tmpdir/synth.out")" != "1" ]; then
  echo "human output should carry exactly one generator= (only the kind=generated entry declares one)" >&2
  cat "$tmpdir/synth.out" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/tests/test_docs_lint.sh >"$tmpdir/docs_test.out"
if grep -q "reference.tech_index" "$tmpdir/docs_test.out"; then
  echo "docs tooling test changes should not imply tech index impact" >&2
  exit 1
fi

./ops/docs_impact.py --files ops/docs_lint.sh --explain >"$tmpdir/explain.out"
grep -q "docs_impact: match_type legend" "$tmpdir/explain.out"
grep -q "docs_impact: recommended review order" "$tmpdir/explain.out"
grep -q '^EXCLUDED contract.host_topology ' "$tmpdir/explain.out"
grep -q 'match_type=exact' "$tmpdir/explain.out"
grep -q 'excluded_by=!ops/docs_lint.sh' "$tmpdir/explain.out"
grep -q '^EXCLUDED policy.safety ' "$tmpdir/explain.out"
grep -q '^EXCLUDED reference.product_surface ' "$tmpdir/explain.out"

./ops/docs_impact.py --files ops/docs_lint.sh --json --explain >"$tmpdir/explain.json"
grep -q '"excluded_impacts"' "$tmpdir/explain.json"
grep -q '"id": "contract.host_topology"' "$tmpdir/explain.json"
grep -q '"match_type": "exact"' "$tmpdir/explain.json"
grep -q '"excluded_by": \[' "$tmpdir/explain.json"
grep -q '"!ops/docs_lint.sh"' "$tmpdir/explain.json"

./ops/docs_impact.py --files ops/docs_lint.sh ops/devops_kg_safe.sh --explain >"$tmpdir/explain_partial.out"
grep -q '^IMPACT runbook.system ' "$tmpdir/explain_partial.out"
grep -q '^IMPACT policy.safety ' "$tmpdir/explain_partial.out"
grep -q '^IMPACT policy.safety ' "$tmpdir/explain_partial.out"
grep -q 'match_type=suppressed-partial' "$tmpdir/explain_partial.out"
grep -q 'excluded_changed=ops/docs_lint.sh' "$tmpdir/explain_partial.out"
grep -q 'excluded_by=!ops/docs_lint.sh' "$tmpdir/explain_partial.out"

./ops/docs_impact.py --files ops/docs_lint.sh ops/devops_kg_safe.sh --json --explain >"$tmpdir/explain_partial.json"
grep -q '"id": "policy.safety"' "$tmpdir/explain_partial.json"
grep -q '"match_type": "suppressed-partial"' "$tmpdir/explain_partial.json"
grep -q '"excluded_paths": \[' "$tmpdir/explain_partial.json"
grep -q '"ops/docs_lint.sh"' "$tmpdir/explain_partial.json"

# --- IMP-20260805-e98982: --since must scan merge-base..HEAD, not <rev>..HEAD ---
# Everything above drives --files, so no test ever exercised the --since git path.
# Fixture is a real throwaway git repo under $tmpdir (the KG repo is never written to)
# shaped like the KG norm: local main keeps moving while a worktree branch stays forked
# behind it. Two-dot `<base>..HEAD` then reports the base branch's own commits as this
# branch's changes (direction reversed); three-dot `<base>...HEAD` reports only what this
# branch actually did. The base-side change must be a MODIFICATION of a file that already
# exists at the merge base — an addition on the base side shows up as D in `base..HEAD`
# and is dropped by --diff-filter=ACMR, so it would hide the leak.
divergence_repo="$tmpdir/divergence"
mkdir -p "$divergence_repo/docs"
(
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
  cd "$divergence_repo"
  git -c init.defaultBranch=main init -q .
  git symbolic-ref HEAD refs/heads/main
  git config user.email probe@example.test
  git config user.name probe
  git config commit.gpgsign false

  cat >docs/registry.yml <<'YAML'
version: 1
description: "Minimal registry for the --since divergence fixture."

documents:
  - id: probe.doc
    path: docs/probe.md
    kind: reference
    triggers:
      - probe_changed
    sources:
      - feature_side.md

  - id: leak.doc
    path: docs/leak.md
    kind: reference
    triggers:
      - leak_changed
    sources:
      - main_side.md
YAML
  printf 'v1\n' >main_side.md
  printf 'v1\n' >feature_side.md
  git add -A
  git commit -qm "shared ancestor"

  printf 'v2\n' >main_side.md
  git commit -qam "main advances while the branch is open"

  git checkout -q -b feature main~1
  printf 'v2\n' >feature_side.md
  git commit -qam "this branch's own work"

  # A history sharing no ancestor with feature, for the no-merge-base case below.
  git checkout -q --orphan unrelated
  git commit -qm "unrelated root"
  git checkout -q feature
)

(cd "$divergence_repo" && unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE && \
  "$ROOT/ops/docs_impact.py" --since main --json) >"$tmpdir/divergence.json"
if grep -q '"main_side.md"' "$tmpdir/divergence.json"; then
  echo "--since <rev> leaked the base branch's own commits into changed_paths; use <rev>...HEAD" >&2
  exit 1
fi
# The ticket's actual complaint was spurious IMPACT rows, one layer downstream of
# changed_paths. leak.doc sources main_side.md, so a leak fails at the symptom too.
if grep -q '"id": "leak.doc"' "$tmpdir/divergence.json"; then
  echo "--since leaked the base branch's own commits into IMPACT candidates" >&2
  exit 1
fi
# Positive control: both leak checks above are vacuous unless --since still sees this
# branch's real change, and changed_paths must hold exactly that one path.
if [ "$(tr -d ' \n' <"$tmpdir/divergence.json" | grep -c '"changed_paths":\["feature_side.md"\]')" != "1" ]; then
  echo "--since should report exactly this branch's own changed path" >&2
  exit 1
fi
grep -q '"id": "probe.doc"' "$tmpdir/divergence.json"

# Three-dot introduces a failure mode two-dot never had: with no common ancestor,
# `git diff <rev>...HEAD` exits 128 with EMPTY stdout. Swallowed, that renders as
# "no registry impacts" — a false green claiming nothing changed. Must fail closed.
if (cd "$divergence_repo" && unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE && \
    "$ROOT/ops/docs_impact.py" --since unrelated --json) >"$tmpdir/orphan.out" 2>"$tmpdir/orphan.err"; then
  echo "--since with no merge base must fail closed, not report an empty changeset" >&2
  exit 1
fi
grep -q 'merge-base' "$tmpdir/orphan.err"
# Positive control for the shallow case's discriminator below: that check asserts the
# shallow message does NOT say 無共同祖先. A negative assertion with nothing pinning the
# string down decays into "always true" the day the wording changes. Asserting it here,
# where it must appear, makes any rewording red at the control instead of silently
# hollowing out the discriminator.
grep -q '無共同祖先' "$tmpdir/orphan.err"
# Fail closed means nothing parseable on stdout either, or a caller reading only
# stdout still sees "no changes" and the non-zero exit buys nothing.
if [ -s "$tmpdir/orphan.out" ]; then
  echo "--since must not emit a result payload when it cannot resolve the range" >&2
  exit 1
fi

# A shallow checkout produces the SAME symptom (no merge base) from a different cause:
# the common ancestor exists but was truncated. git itself says nothing here — measured
# stderr from `git merge-base` is 0 bytes — so if this tool blames "unrelated history"
# and prescribes --files, it talks the reader out of the real fix (fetch depth) and into
# hand-listing paths. Cause must be probed, not assumed.
# --no-local rather than file://: a local path clone ignores --depth, leaving a NON-shallow
# fixture that tests nothing. git does warn about this, but the warning lands on a stream
# no assertion reads, so the hollow fixture would not redden anything — hence the explicit
# is-shallow self-check below. file:// also works but percent-decodes the URL, so it breaks
# whenever $TMPDIR holds a decodable escape (measured: `%41` -> rc=128; `%dir` is fine).
# Both the clone and the is-shallow probe need the git env unset: `git -C <dir>` does
# NOT override an inherited GIT_DIR, so the probe would inspect the caller's repo
# (not shallow) and red this test while naming the wrong cause.
(
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
  git clone -q --no-local --depth=1 --no-single-branch "$divergence_repo" "$tmpdir/shallow"
  if [ "$(git -C "$tmpdir/shallow" rev-parse --is-shallow-repository)" != "true" ]; then
    echo "fixture broken: the shallow clone is not actually shallow" >&2
    exit 1
  fi
)
if (cd "$tmpdir/shallow" && unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE && \
    "$ROOT/ops/docs_impact.py" --since origin/main --json) >"$tmpdir/shallow.out" 2>"$tmpdir/shallow.err"; then
  echo "--since must fail closed in a shallow checkout too" >&2
  exit 1
fi
if [ -s "$tmpdir/shallow.out" ]; then
  echo "--since must not emit a result payload for an unresolvable shallow range" >&2
  exit 1
fi
# 'shallow checkout', not 'shallow': the latter is a substring of the remedy word
# "unshallow", so it would be satisfied by the cure alone and assert nothing about
# whether the cause was named.
if ! grep -q 'shallow checkout' "$tmpdir/shallow.err" || ! grep -q 'unshallow\|fetch-depth' "$tmpdir/shallow.err"; then
  echo "shallow checkout must be named as the cause, with the fetch-depth remedy; got:" >&2
  cat "$tmpdir/shallow.err" >&2
  exit 1
fi
if grep -q '無共同祖先' "$tmpdir/shallow.err"; then
  echo "shallow truncation must not be reported as unrelated history; got:" >&2
  cat "$tmpdir/shallow.err" >&2
  exit 1
fi

# --help must teach the semantics the code implements, since `--since main` is the
# natural thing to type and the old help actively taught the two-dot form.
grep -q '\.\.\.HEAD' "$tmpdir/help.out"
grep -q 'merge-base' "$tmpdir/help.out"

# Agent-facing surface paths are registry-owned and must include dot-directories
# without widening the scan to frozen backlog records.
./ops/docs_impact.py --surface-paths >"$tmpdir/surface_paths.out"
grep -qxF '.claude/agents/' "$tmpdir/surface_paths.out"
grep -qxF 'docs/reference/tech_index.md' "$tmpdir/surface_paths.out"
grep -qxF 'docs/runbook/system.md' "$tmpdir/surface_paths.out"
if grep -qxF 'docs/runbook/' "$tmpdir/surface_paths.out"; then
  echo "surface paths must not include the frozen docs/runbook backlog" >&2
  exit 1
fi

# The scan must traverse dot-directories itself, not delegate to rg (which skips
# them by default). A fixture keeps this long-lived test independent of repo prose.
mkdir -p "$tmpdir/tree/.claude/agents"
printf '%s\n' 'NEEDLE-XYZ in agent' >"$tmpdir/tree/.claude/agents/w.md"
printf '%s\n' 'NEEDLE-XYZ in top' >"$tmpdir/tree/top.md"
cat >"$tmpdir/tree/reg.yml" <<'EOF'
version: 1
description: fixture
agent_facing_surface:
  paths:
    - .claude/agents/
    - top.md
EOF
scan_out="$($ROOT/ops/docs_impact.py --root "$tmpdir/tree" --registry "$tmpdir/tree/reg.yml" --surface-scan 'NEEDLE-XYZ')"
printf '%s\n' "$scan_out" | grep -qE '^SURFACE \.claude/agents/w\.md:1:'
printf '%s\n' "$scan_out" | grep -qE '^SURFACE top\.md:1:'

# Missing registry control data must fail closed and emit no path payload.
cat >"$tmpdir/tree/no-surface.yml" <<'EOF'
version: 1
description: fixture without the control plane
EOF
if "$ROOT/ops/docs_impact.py" --root "$tmpdir/tree" --registry "$tmpdir/tree/no-surface.yml" --surface-paths \
    >"$tmpdir/no_surface.out" 2>"$tmpdir/no_surface.err"; then
  echo "missing agent_facing_surface.paths must fail closed" >&2
  exit 1
fi
if [ -s "$tmpdir/no_surface.out" ]; then
  echo "fail-closed surface lookup must not emit a partial path list" >&2
  exit 1
fi
grep -q 'agent_facing_surface.paths' "$tmpdir/no_surface.err"

# A stale path must not silently shrink the surface scan.
cat >"$tmpdir/tree/missing-path.yml" <<'EOF'
version: 1
description: fixture with a stale path
agent_facing_surface:
  paths:
    - missing/
EOF
if "$ROOT/ops/docs_impact.py" --root "$tmpdir/tree" --registry "$tmpdir/tree/missing-path.yml" \
    --surface-scan 'NEEDLE-XYZ' >"$tmpdir/missing_path.out" 2>"$tmpdir/missing_path.err"; then
  echo "missing surface path must fail closed" >&2
  exit 1
fi
grep -q 'missing/' "$tmpdir/missing_path.err"
