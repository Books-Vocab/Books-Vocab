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
grep -q "generated.ios_baseline" "$tmpdir/ios.out"
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
grep -q '"id": "generated.ios_baseline"' "$tmpdir/book_model.json"
grep -q '"generator": "ops/gen_ios_baseline.sh"' "$tmpdir/book_model.json"
if grep -q '"id": "contract.sync_lifecycle"' "$tmpdir/book_model.json"; then
  echo "book model changes should not imply vocabulary sync lifecycle impact by default" >&2
  exit 1
fi
if grep -q '"id": "sop.ios"' "$tmpdir/book_model.json"; then
  echo "ordinary iOS model changes should not imply iOS workflow SOP impact" >&2
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
