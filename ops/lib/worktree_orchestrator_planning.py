"""Pure planning and gate-routing seam for the worktree orchestrator.

This module owns intent classification and impact-to-gate mapping only.  It performs
no git, subprocess, clock, registry, or delivery mutation; the executable façade
re-exports the historical private names for compatibility.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any, Callable

import worktree_gate as gate_logic
from lib import worktree_gate_tiers as gate_tiers

BACKLOG_STORE_DIR = "docs/runbook/backlog/"
RESOLVED_STATUSES = ("fixed", "wont-fix")
GATE_SCHEMA = "kg.worktree.gate.v1"
GATE_INPUT_SCHEMA = "kg.worktree.gate-input.v1"
GATE_PROGRESS_SCHEMA = "kg.worktree.gate-progress.v1"
FREEZE_SCHEMA = "kg.worktree.freeze.v1"
DELIVERY_SCHEMA = "kg.worktree.delivery.v1"
_INDEPENDENT_NO_TICKET_INTENT = "independent-no-ticket:"
# Local-main-centric topology: local `main` is the trunk. Worktrees fork from it and
# cutover fast-forwards it OFFLINE — origin is only a deploy target (`deploy` pushes
# local main to origin, which the felix reconciler turns into a production rollout).
BASE_DEFAULT = "main"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORKTREE_SCRATCH_REL = Path(".cache") / "agent-scratch"
# git's canonical empty-tree object — diff base for a first-ever publish (all files new)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# The design-system impact surface: the EXACT pattern the pre-commit hook uses
# (.githooks/pre-commit DS_PATTERN). Reused verbatim so orchestrator routing and the
# hook can never disagree about what a "design-system change" is.
DS_RE = re.compile(
    r"^(design-system/"
    r"|ops/(gen_web_tokens|gen_figma_sets|token_drift_check|component_fidelity_check|verify_design_system)\.(py|sh)"
    r"|ios/BooksAndVocab/(Models|UIComponents)/"
    r"|backend/static/kg-(tokens|components)\.css)"
)


# ============================================================================
# PURE layer — the only judgement this tool owns. No git, no clock, no IO.
# ============================================================================
_DEBUG_KW = ("bug", "crash", "fix", "hang", "regression", "broken", "stutter",
             "flaky", "leak", "debug", "root cause", "root-cause")
# Research is signalled by a LEADING verb (research the ..., investigate ...): a
# substring match is too greedy — "the explore tab" / "the analytics screen" are
# feature nouns, not research intents.
_RESEARCH_VERBS = frozenset({"research", "investigate", "audit", "explore", "analyze",
                             "analyse", "survey", "study", "understand", "compare",
                             "evaluate", "assess", "map", "review"})
# Politeness / pronoun filler that can precede a LEADING imperative verb ("please
# investigate …", "can you research …") — transparent to the verb check.
_LEADING_FILLER = frozenset({"please", "can", "could", "you", "lets", "let's", "let",
                             "us", "we", "i", "to", "help", "me", "do"})
# Articles introduce a NOUN phrase, NOT an imperative — deliberately NOT filler. A
# phrase whose first meaningful token is an article ("the explore tab") is a feature
# noun, so the research-verb check must never see through it (nit4).
_ARTICLES = frozenset({"the", "a", "an"})


def classify_intent(text: str) -> str:
    """Map a free-text intent to a branch type: debug | research | feat.

    Precedence: a fix/bug intent is `debug` even when phrased as "investigate … and
    fix it" (a debug keyword anywhere dominates). Otherwise a `research` intent is one
    whose LEADING imperative verb is a research verb (research/investigate/audit/…),
    ignoring politeness filler. A bare noun-phrase — one that opens with an article
    (the/a/an) after any filler — is `feat` even when it CONTAINS a research noun
    ("the explore tab", "the audit log"): an article marks a noun, not an imperative.
    Everything else is `feat`."""
    t = f" {text.lower()} "
    if any(k in t for k in _DEBUG_KW):
        return "debug"          # a fix intent dominates ("investigate … and fix it")
    for word in re.findall(r"[a-z']+", text.lower()):
        if word in _LEADING_FILLER:
            continue
        if word in _ARTICLES:
            return "feat"        # bare noun-phrase, no leading imperative verb (nit4)
        return "research" if word in _RESEARCH_VERBS else "feat"
    return "feat"


def branch_for(
    intent_text: str,
    slug: str,
    branch_type: str | None = None,
) -> str:
    """Branch name = ``<type>/<slug>``; an explicit type beats inference."""
    return f"{branch_type or classify_intent(intent_text)}/{slug}"


def _is_ui_path(p: str) -> bool:
    """A swift path whose change plausibly affects UI/navigation/accessibility — the
    signal to add the UI-scoped iOS test on top of the unit scope."""
    base = p.rsplit("/", 1)[-1]
    return (
        base.endswith("View.swift")
        or "/UIComponents/" in p
        or "/UI/" in p
        or "UITests" in p
        or base.endswith("Screen.swift")
    )


def _is_backend_test(p: str) -> bool:
    base = p.rsplit("/", 1)[-1]
    return base.startswith("test_") or base.endswith("_test.py")


def _is_ops_test(p: str) -> bool:
    return p.startswith("ops/tests/") and p.rsplit("/", 1)[-1].startswith("test_")


def _shell(name: str, category: str, cmd: list[str], level: str,
           cwd: str | None = None, *, preflight: bool = False) -> dict[str, Any]:
    return {"name": name, "category": category, "kind": "shell",
            "cmd": cmd, "level": level, "cwd": cwd, "preflight": preflight}


def _internal(name: str, category: str, level: str, **extra: Any) -> dict[str, Any]:
    g = {"name": name, "category": category, "kind": "internal", "level": level}
    g.update(extra)
    return g


_LIVE_ONLY_UITEST_CLASSES = {"LiveDemoAccessUITests"}


# Shell tools whose test is named after what it exercises rather than after the file.
# Convention (`ops/X.sh` -> `ops/tests/test_X.sh` or `ops/test_X.sh`) resolves most of
# them; this is the remainder.
#
# Every entry below was traced to a line that RUNS the script, not one that mentions it.
# That distinction is the whole risk here, and inference from names is bad at it: of the
# nine entries first written, two were false — test_ios_cache_evict.sh covers
# lib/ios_cache_evict.sh rather than ios_clean_derived_data.sh, and test_release.sh only
# `[[ -f ]]`-checks release_changelog.sh and greps release.sh for a mention of it, so a
# release_changelog.sh gutted to `exit 0` would have passed a BLOCK gate.
#
# The contract test is a necessary condition, not a sufficient one: it requires the
# target to exist, to mention the script, and to be unreachable by convention — the
# release_changelog entry satisfied all three while covering nothing. Proving coverage
# mechanically means mutating the script and requiring the target to go red; filed as
# IMP-0055 rather than bolted on here.
OPS_SHELL_TEST_ALIASES: dict[str, str] = {
    "ops/devops_kg_safe.sh": "ops/tests/test_devops_safe_lightsail_guard.sh",
    "ops/install_lldb_forensics.sh": "ops/tests/test_lldb_crash_forensics.sh",
    "ops/ios_test.sh": "ops/test_ios_test_discovery.sh",
    "ops/ios_build.sh": "ops/test_ios_ops.sh",
    "ops/ios_archive.sh": "ops/test_ios_ops.sh",
    "ops/lib/ios_ops_catalog.sh": "ops/tests/test_catalog_agent_boundary.sh",
    "ops/release_bump.sh": "ops/test_release.sh",
    "ops/review_flip_probe.sh": "ops/tests/test_review_probe.sh",
    # test_script_help.sh EXECUTES it (its non-ASCII-abutment section delegates there), which
    # is the standard this table demands. `ops-shell-scan` also runs the script on
    # every .sh diff, but that is the scanner doing its job, not a test of it.
    "ops/shell_scan.sh": "ops/tests/test_script_help.sh",
}

# Test scripts that must NOT be routed as a block gate, each with the reason. A gate
# that can only ever be red is as harmful as one that can only be green, in the other
# direction: it blocks everyone and the only visible way past it is to leave the process
# (IMP-0039). Naming them here keeps them in the `ops-shell-untested` advisory, which
# says so out loud, instead of silently arming a gate nobody can pass.
OPS_SHELL_UNROUTABLE_TESTS: dict[str, str] = {
    "ops/test_ops.sh": "the aggregate runner — it invokes every group, including the "
                       "ones excluded from CI for needing local assets, so its colour is "
                       "a property of the machine rather than of the change. Duration is "
                       "the reason that holds everywhere: many minutes",
}


def _ops_shell_test_candidates(rel: str) -> list[str]:
    """Test files that could cover a changed shell script, most specific first."""
    base = rel.rsplit("/", 1)[-1]
    if rel in OPS_SHELL_UNROUTABLE_TESTS:
        return []
    if base.startswith("test_"):
        return [rel]  # a changed test script is its own gate (path-exact — no collision)
    alias = OPS_SHELL_TEST_ALIASES.get(rel)
    # The basename convention only holds inside `ops/` and at the repo root. Once the
    # routing filter widened past those (IMP-0057), `lab/podcast/start.sh` would resolve
    # to `ops/test_start.sh` — the candidate for the ROOT `start.sh` — and be reported
    # covered by a test that never executes a line of it. Elsewhere: named alias only.
    if not (rel.startswith("ops/") or "/" not in rel):
        return [alias] if alias else []
    return [c for c in (f"ops/tests/test_{base}", f"ops/test_{base}", alias) if c]
DATA_PLANE_OWNERS: dict[str, tuple[list[str], ...]] = {
    "ops/ui_quality_plane.yml": (
        ["ops/ui_quality_plane.py", "validate"],
        ["ops/tests/test_ui_quality_plane.sh"],
    ),
    "docs/registry.yml": (
        ["ops/docs_lint.sh", "--registry"],
    ),
}

# Agent-facing constitution files change agent behaviour and therefore need a
# contract gate of their own; they are not ordinary docs and docs_lint rejects
# them as invalid --files inputs.
AGENT_CONSTITUTION: tuple[str, ...] = ("CLAUDE.md", "AGENTS.md")


# Paths that legitimately select no gate, each with the reason. Deny-by-default:
# Compatibility names for callers/tests that historically imported these helpers
# from the CLI module.  The implementation now lives in the side-effect-free gate
# module so it can be tested and reused without loading the delivery lifecycle.
NEUTRAL_RULES = gate_logic.NEUTRAL_RULES
GATE_STATUSES = gate_logic.GATE_STATUSES
UnknownGateStatus = gate_logic.UnknownGateStatus
assert_known_statuses = gate_logic.assert_known_statuses
aggregate_verdict = gate_logic.aggregate_verdict
GATE_TIERS = gate_tiers.GATE_TIERS
TIER_RANK = gate_tiers.TIER_RANK
DEFAULT_GATE_TIER = gate_tiers.DEFAULT_GATE_TIER
GateTierError = gate_tiers.GateTierError
normalize_gate_tier = gate_tiers.normalize_gate_tier
classify_gate_tier = gate_tiers.classify_gate_tier
select_gate_plan = gate_tiers.select_plan
required_cutover_tier = gate_tiers.required_cutover_tier


def _neutral_rule(rel: str) -> str | None:
    return gate_logic.neutral_rule(rel)


def _coverage(changed_files: list[str], covered: set[str]) -> dict[str, Any]:
    return gate_logic.coverage(changed_files, covered)


def plan_gates(changed_files: list[str],
               ops_test_exists: Callable[[str], bool] | None = None,
               base: str | None = None,
               ops_tests_dir_exists: Callable[[], bool] | None = None,
               path_exists: Callable[[str], bool] | None = None) -> list[dict[str, Any]]:
    """Route changed files to the project's EXISTING gate tools. This is the one real
    judgement the orchestrator owns; it never decides pass/fail itself.

      ios/**            -> ios_ops.sh build  AND  build --catalyst (sim green != Catalyst
                           green) + quality impact (swift) + test --unit. If UITest
                           classes changed, also test --ui --file <class> per changed
                           UITest (impacted-scope, --dataset marketing_demo) — NOT the
                           whole --ui suite, which false-blocks on unrelated flaky tests.
                           A live-only exact-device class cannot truthfully execute in
                           that fixture simulator route: compile it as Release iphoneos
                           and emit a runtime-evidence advisory instead.
      design-system/**  -> verify_design_system.sh   (tokens / generated CSS / Models /
      | tokens | *.css     UIComponents — the pre-commit DS_PATTERN, verbatim).
      docs/**.md        -> docs_lint.sh --files + conflict-marker scan + verified_against
                           reachability.
      backend/**.py     -> targeted pytest on the changed TEST files; a src-only change
                           with no targeted test is a WARN advisory (never the full
                           suite — it carries known pre-existing false failures).
      ops/**.py         -> targeted pytest via the pinned uv sandbox (`uv run
                           --no-project --python 3.13 --with pytest --with pyjwt
                           --with cryptography` — never touching backend/uv.lock): a
                           changed ops/tests/test_*.py runs itself;
                           a changed src file runs its ops/tests/test_<basename>. EVERY
                           target must pass `ops_test_exists` (a deleted test file is
                           in the diff too — a gone path would make pytest exit 4);
                           any changed ops .py that resolves to no existing test falls
                           back to the whole ops/tests suite (which subsumes the
                           targeted files, and which sandbox-unsafe tests must dep-guard
                           with a skip — see test_demo_ios_spec_emitter).
      **.sh             -> every tracked shell script: a syntax floor on each — the
                           interpreter read
                           from its shebang, an unrecognised one SKIPPED and named
                           rather than guessed at — which is the only check covering
                           the ~1/3 with no test, plus the test that resolves for each.
                           The `ops/tests/test_<base>` / `ops/test_<base>` convention
                           applies only inside `ops/` and at the repo root, where
                           basenames are unique; anywhere else only an explicit
                           OPS_SHELL_TEST_ALIASES entry counts, because a shared
                           basename would report coverage by a test that never runs
                           the script. The remainder is named in a warn advisory
                           rather than left anonymous.
                           `ops_test_exists` and `path_exists` are injected by cmd_gate
                           (both anchored at the WORKTREE, so files added in the same diff
                           are seen); the pure defaults remain conservative.
      **.yml | **.yaml  -> the tool that asserts it, per DATA_PLANE_OWNERS (ui_quality
                           _plane.yml -> its validate + its test; registry.yml ->
                           docs_lint.sh --registry). No universal syntax floor exists
                           the way `bash -n` does, so anything with no owner is NAMED in
                           a warn. Files under a NEUTRAL_RULES tree stay neutral.

    Levels: `block` fails the verdict; `warn` is ADVISORY — it degrades the aggregate
    to `warn` but does NOT block cutover (a warn LANDS "with warnings"; its disposition
    belongs to the driving agent). Informational gates (backend-src-only advisory,
    verified_against reachability) are `warn` so they surface without blocking. A
    neutral file selects nothing."""
    gates: list[dict[str, Any]] = []

    # Official-deck specs are a fixed-set gate, not a diff-routed gate. A new spec can
    # be present in the worktree without changing any tracked file; the check must still
    # compare the on-disk set with the git index and name the omitted deck (IMP-20260808-
    # 88c404). Synthetic repos without this tool are intentionally left alone.
    if (ops_test_exists is not None
            and ops_test_exists("ops/official_decks/build_official.py")):
        gates.append(_shell(
            "official-decks-check", "data",
            ["uv", "run", "python", "../ops/official_decks/build_official.py",
             "check", "--json"],
            "block", cwd="backend",
        ))

    ios = [p for p in changed_files if p.startswith("ios/")]
    ds = [p for p in changed_files if DS_RE.search(p)]
    docs = [p for p in changed_files if p.startswith("docs/") and p.endswith(".md")]
    backend = [p for p in changed_files if p.startswith("backend/") and p.endswith(".py")]

    if ios:
        # Static lints first: ~21s against minutes of xcodebuild, and a red here
        # is far cheaper to act on than a red after two builds and a unit suite.
        #
        # This replaces `ios_ops.sh quality impact`, which sat at warn level and
        # could not fail by construction: it routes to ui_quality_plane's
        # PLANNER, whose every return is 0. It printed which lints would apply to
        # the changed files and reported pass — the plan mistaken for the check.
        # cutover is offline and never pushes, so it is the only gate on this
        # path; CI cannot cover for it.
        gates.append(_shell("ui-quality-fast", "ios",
                            ["ops/ui_quality_gate.sh", "--tier", "fast",
                             "--execute", "--all-mechanisms"], "block"))
        gates.append(_shell("ios-build", "ios", ["ops/ios_ops.sh", "build"], "block"))
        gates.append(_shell("ios-build-catalyst", "ios",
                            ["ops/ios_ops.sh", "build", "--catalyst"], "block"))
        swift = [p for p in ios if p.endswith(".swift")]
        if swift:
            # Kept, but honestly named and honestly scoped: this reports the
            # SLOW mechanisms the diff touches that cutover deliberately does
            # not run (for example, full UI flows). It is
            # advisory because it is a cost/coverage trade, not a check.
            gates.append(_internal("ui-quality-slow-pending", "ios", "warn",
                                   note="slow UI mechanisms triggered by this diff were not "
                                        "executed by cutover — run ops/ui_quality_gate.sh "
                                        "--tier slow --execute-slow if this change needs them",
                                   files=swift))
        # `--lease` claims a pool simulator for the run and releases it on exit.
        # Without it these runs contend for the single default device ("iPhone 17
        # Pro Max"), whose lock has a 600s ceiling — with several worktrees under
        # gate at once that ceiling is reached routinely, and the timeout surfaces
        # as rc=1, i.e. indistinguishable from a real test failure. A cutover gate
        # that turns red because a *neighbour* was testing is worse than a slow
        # one: it trains the operator to disbelieve the gate.
        gates.append(_shell("ios-test-unit", "ios",
                            ["ops/ios_ops.sh", "test", "--unit", "--lease"], "block"))
        if any(_is_ui_path(p) for p in ios):
            # Impacted-scope UI gate: run only the UI *test classes* that changed
            # in this diff — NOT the whole --ui suite. The full suite as a block
            # gate false-blocks every iOS cutover on unrelated, pre-existing/flaky
            # UI tests (UI flakiness is well documented here), and costs ~tens of
            # minutes. This mirrors ios-quality-impact's --files scoping.
            # ios_test.sh --ui requires a UI World dataset (the SoT for UI runs);
            # the committed default world is marketing_demo. Filter to *Tests.swift
            # so page-object/helper files (e.g. AppPage.swift) are excluded.
            # A UI-source change with no changed UITest is covered by build +
            # unit + quality-impact; a full-suite run here would just reintroduce
            # the flaky false-block.
            present = ops_test_exists or (lambda rel: True)
            ui_test_classes = sorted({
                p.rsplit("/", 1)[-1].removesuffix(".swift")
                for p in ios
                if "UITests/" in p and p.endswith("Tests.swift")
                and present(p)
            })
            ui_tests_removed = sorted({
                p for p in ios
                if "UITests/" in p and p.endswith("Tests.swift")
                and not present(p)
            })
            live_only_classes = sorted(set(ui_test_classes) & _LIVE_ONLY_UITEST_CLASSES)
            for cls in sorted(set(ui_test_classes) - _LIVE_ONLY_UITEST_CLASSES):
                ui_cmd = ["ops/ios_ops.sh", "test", "--ui", "--json", "--lease"]
                if cls == "FixtureDatasetUITests":
                    # P9's app-written evidence contract requires the unique screenshot
                    # directory staged by the visual runner. A behavior-only invocation
                    # cannot satisfy that test and would fail late inside XCTest.
                    ui_cmd.append("--visual")
                ui_cmd.extend(["--dataset", "marketing_demo", "--file", cls])
                gates.append(_shell(f"ios-test-ui:{cls}", "ios",
                                    ui_cmd, "block"))
            if live_only_classes:
                gates.append(_shell(
                    "ios-live-demo-uitest-compile", "ios",
                    ["ops/ios_ops.sh", "test", "--ui", "--configuration", "Release",
                     "--destination", "generic/platform=iOS", "--prepare-cache", "--json"],
                    "block",
                ))
                gates.append(_internal(
                    "ios-live-demo-runtime-advisory", "ios", "warn",
                    note=("live-only UITest compiled for Release iphoneos; runtime was "
                          "intentionally not executed with simulator/fixture evidence — "
                          "App Review submission still requires app_review_evidence.py "
                          "demo-run exact-device evidence"),
                    files=[
                        f"ios/BooksAndVocabUITests/{cls}.swift"
                        for cls in live_only_classes
                    ],
                ))
            if ui_tests_removed:
                gates.append(_internal(
                    "ios-ui-tests-removed", "ios", "warn",
                    note=("changed UI test files were deleted in this worktree and were "
                          "not executed; verify the product/test topology explicitly"),
                    files=ui_tests_removed,
                ))

    if ds:
        gates.append(_shell("design-system", "design-system",
                            ["ops/verify_design_system.sh"], "block"))

    if docs:
        # All three of these gates READ the file. A doc DELETED in this diff is still
        # a changed path, and handing it to `docs_lint --files` makes it exit 2 with
        # "--files 路徑不存在" — so **any commit that removes a doc is blocked**, by an
        # error phrased as if the caller mistyped a path. Measured on the commit that
        # removed the generated ledger view (IMP-20260807-b9526c).
        #
        # Not silently dropped: the removal is named in its own advisory, the same way
        # `ops-shell-untested` and `data-plane-unowned` name what they could not cover.
        # A gate list that quietly shrinks reads as "everything was checked".
        present = ops_test_exists or (lambda rel: True)
        docs_live = [p for p in docs if present(p)]
        docs_removed = [p for p in docs if p not in docs_live]
        if docs_live:
            gates.append(_shell("docs-lint", "docs",
                                ["ops/docs_lint.sh", "--files", *docs_live], "block"))
            gates.append(_internal("docs-conflict-markers", "docs", "block", files=docs_live))
            gates.append(_internal("docs-verified-against", "docs", "warn", files=docs_live))
        if docs_removed:
            gates.append(_internal("docs-removed", "docs", "warn", files=docs_removed))

    if backend:
        present = ops_test_exists or (lambda rel: True)
        tests = [p for p in backend if _is_backend_test(p)]
        live_tests = [p for p in tests if present(p)]
        removed_tests = [p for p in tests if not present(p)]
        if live_tests:
            rel = [p[len("backend/"):] for p in live_tests]
            gates.append(_shell("backend-pytest", "backend",
                                ["uv", "run", "pytest", "-q", *rel], "block", cwd="backend"))
        if removed_tests:
            gates.append(_internal(
                "backend-tests-removed", "backend", "warn",
                note=("deleted backend test files were not passed to pytest; verify their "
                      "replacement topology explicitly"),
                files=removed_tests,
            ))
        if not live_tests:
            gates.append(_internal("backend-tests-advisory", "backend", "warn",
                                   note="backend src changed but no targeted test in the diff — "
                                        "run the relevant tests manually (the full suite carries "
                                        "known pre-existing false failures)", files=backend))

    # Duplicate module-level definitions are a language-level invariant, not an
    # ops-only concern: backend/ and lab/ Python diffs must receive the same cheap
    # repository scan.  Keep this gate outside the coverage buckets below; one
    # repo-wide lint cannot claim that every non-ops path has a domain test.
    py_any = [p for p in changed_files if p.endswith(".py")]
    if py_any:
        gates.append(_shell("ops-python-scan", "ops", ["ops/python_scan.py"], "block"))

    ops_py = [p for p in changed_files if p.startswith("ops/") and p.endswith(".py")]
    if ops_py:
        exists = ops_test_exists or (lambda rel: False)
        targets: set[str] = set()
        fallback = False
        for p in ops_py:
            # a changed test file must ALSO prove existence: a DELETED test is in
            # the diff too, and passing a gone path to pytest exits 4 -> false block
            candidate = p if _is_ops_test(p) else f"ops/tests/test_{p.rsplit('/', 1)[-1]}"
            if exists(candidate):
                targets.add(candidate)
            else:
                fallback = True
        # The whole-suite fallback subsumes every targeted file, but only when the
        # worktree actually carries an ops test tree. Synthetic git fixtures used by
        # provenance/identity checks intentionally contain just the copied
        # orchestrator; invoking pytest on their absent directory exits rc=4 and turns
        # unavailable infrastructure into a false BLOCK. The callback is injected by
        # cmd_gate so pure routing tests retain their conservative fallback semantics.
        ops_tests_changed = any(p.startswith("ops/tests/") for p in changed_files)
        if (fallback and not ops_tests_changed and ops_tests_dir_exists is not None
                and not ops_tests_dir_exists()):
            gates.append(_internal(
                "ops-pytest-unavailable", "ops", "warn",
                files=ops_py,
                note=("ops-pytest was not run: the worktree has no ops/tests directory; "
                      "this is unavailable test infrastructure, not a change verdict"),
            ))
        else:
            if fallback and targets:
                # Keep the conservative whole-suite fallback for S2, but do not make
                # hand-back S1 a static-only ceremony when the diff contains concrete
                # existing tests.  The focused gate is the honest cheap functional
                # smoke; the whole suite remains the higher-cost regression floor.
                gates.append(_shell(
                    "ops-pytest-focused", "ops",
                    ["uv", "run", "--no-project", "--python", "3.13",
                     "--with", "pytest", "--with", "pyjwt",
                     "--with", "cryptography", "pytest", "-q", *sorted(targets)],
                    "block",
                ))
            selected = ["ops/tests"] if fallback else sorted(targets)
            gates.append(_shell("ops-pytest", "ops",
                                ["uv", "run", "--no-project", "--python", "3.13",
                                 "--with", "pytest", "--with", "pyjwt",
                                 "--with", "cryptography", "pytest", "-q", *selected], "block"))

    # Before 2026-08-04 a changed shell script selected NOTHING: `ops/devops_kg_safe.sh`
    # is iron law 7's enforcement point and `ops/release.sh` is the only path to
    # production, and both previously lacked an explicit shell gate route (IMP-0051).
    # Three layers, because no single one covers the whole surface: a universal syntax
    # floor (needs only bash, so no machine skips it), the script's own test where one
    # resolves, and a named advisory for the rest — an enumerated hole beats an
    # anonymous one.
    # Repo-root scripts count too. The original `ops/`-prefixed filter quietly excluded
    # `devops.sh` — the production deploy command, and the single shell script in the
    # tree with the highest blast radius (IMP-0052).
    # And the same defect one directory further out: `ops/` + root still missed 12
    # tracked scripts, one of which (`backend/view_logs.sh`) already had a test
    # watching it (IMP-0057). The routing surface is every tracked `*.sh`.
    # A deletion is a changed path, but it has no shell body left to parse, scan, or
    # route to a test. The real gate injects a worktree-anchored existence predicate;
    # the pure planner remains conservative when no predicate is supplied.
    shell_changed = [p for p in changed_files if p.endswith(".sh")]
    live_exists = path_exists or (lambda rel: True)
    ops_sh = [p for p in shell_changed if live_exists(p)]
    if ops_sh:
        gates.append(_internal("ops-shell-syntax", "ops", "block", files=ops_sh))
        # The cross-file layer (IMP-20260808-3bbfa2). The two layers below are
        # per-script by construction — `bash -n` on each changed file, and each
        # file's own test — so a check that is ABOUT the whole tree belongs to no
        # single script and was therefore reachable from no diff at all. The
        # non-ASCII-abutment guard (`$VAR` followed by any byte >= 0x80; eleven
        # full-width punctuation characters and nothing else until 2026-08-08) lived in
        # that hole since 2026-08-05: correct,
        # positively controlled, and never once executed by a gate.
        #
        # ONE instance regardless of how many .sh changed: it scans the whole repo,
        # so per-file instances would be N identical runs. Block, because the thing
        # it catches is fatal at runtime on the error path — where the script's job
        # is to explain a failure and it instead dies mid-sentence.
        gates.append(_shell("ops-shell-scan", "ops", ["ops/shell_scan.sh"], "block"))
        exists = ops_test_exists or (lambda rel: False)
        sh_targets: set[str] = set()
        untested: list[str] = []
        for p in ops_sh:
            # existence is proven against the WORKTREE: a test added in this same diff
            # is visible, and one deleted in it is not handed back to the runner
            hit = next((c for c in _ops_shell_test_candidates(p) if exists(c)), None)
            if hit:
                sh_targets.add(hit)
            else:
                untested.append(p)
        for t in sorted(sh_targets):
            gates.append(_shell(f"ops-shell:{t.rsplit('/', 1)[-1]}", "ops", [t], "block"))
        if untested:
            why = ", ".join(
                f"{p} ({OPS_SHELL_UNROUTABLE_TESTS[p]})" if p in OPS_SHELL_UNROUTABLE_TESTS
                else p
                for p in untested)
            gates.append(_internal(
                "ops-shell-untested", "ops", "warn",
                note=f"no test runs for {why} — syntax is the only gate they get",
                files=untested))

    # yml/yaml control files. The promotion tree is excluded up front:
    # they already have a declared reason to select nothing, and re-adopting them would
    # grow a warn on every marketing-manifest edit — a warn that always fires is a warn
    # nobody reads.
    # Lint watermarks. Five of these are checked in and changing ANY of them must
    # select their own validator, or the debt ceiling could be raised and the
    # cutover gate would stay green. A ratchet whose watermark is not itself gated
    # is a ratchet in name only.
    # `test_lint_baselines.sh` already enumerates every checked-in baseline and
    # fails on one it does not cover, so a single owner routes all of them and
    # every future one — a pattern, not a file list (same rule NEUTRAL_RULES states).
    baselines = [p for p in changed_files
                 if re.fullmatch(r"ops/[a-z0-9_]+_baseline\.txt", p)]
    if baselines:
        gates.append(_shell("data-plane:ops/tests/test_lint_baselines.sh", "data",
                            ["ops/tests/test_lint_baselines.sh"], "block"))

    data_yml = [p for p in changed_files
                if p.endswith((".yml", ".yaml")) and _neutral_rule(p) is None]
    if data_yml:
        # `None` (no probe injected) means assume-present; the ops_sh default is the
        # opposite because there a missing test is a meaningful verdict rather than a
        # missing prerequisite.
        present = ops_test_exists or (lambda rel: True)
        planned_cmds = [g["cmd"] for g in gates if g.get("cmd")]
        docs_lint_files_planned = any(
            cmd[:2] == ["ops/docs_lint.sh", "--files"] for cmd in planned_cmds)
        unowned: list[str] = []
        deleted: list[str] = []
        for p in data_yml:
            owners = DATA_PLANE_OWNERS.get(p)
            if not owners:
                unowned.append(p)
                continue
            if not present(p):
                # deleted in this diff: running its validator is a false red. But
                # skipping silently while still counting the file as covered would make
                # `coverage` say "every changed file is routed" about a file nothing
                # looked at — the exact anonymous hole this router exists to close.
                deleted.append(p)
                continue
            for cmd in owners:
                if (cmd in planned_cmds
                        or (docs_lint_files_planned
                            and cmd == ["ops/docs_lint.sh", "--registry"])):
                    # docs_lint validates the registry before dispatching its mode and
                    # shares the same error counter, so --files fully covers --registry.
                    continue
                planned_cmds.append(cmd)
                # Named by TOOL PATH, not basename: the name is the key for the plan
                # JSON, the result lookup and the history journal, and two owners whose
                # tools differ only by directory would otherwise overwrite each other's
                # verdict while the plan still read complete.
                gates.append(_shell(f"data-plane:{cmd[0]}", "data", list(cmd), "block"))
        if unowned:
            gates.append(_internal(
                "data-plane-unowned", "data", "warn",
                note=("no tool asserts " + ", ".join(unowned)
                      + " — declare one in DATA_PLANE_OWNERS or accept that a typo "
                        "in it lands unchallenged"),
                files=unowned))
        if deleted:
            gates.append(_internal(
                "data-plane-deleted", "data", "warn",
                note=("deleted in this diff, so its owner tool was NOT run: "
                      + ", ".join(deleted)
                      + " — check by hand that nothing still reads it"),
                files=deleted))

    # The kaizen ledger. One file per entry under a fixed directory, so the route
    # keys on that directory rather than on `.json` under docs/ — a `.json` route
    # would hand unrelated data files to a validator that knows nothing about them
    # and pass vacuously, which is the failure this router exists to prevent.
    #
    # `validate` reads the WHOLE store, not just the changed entries: it is a
    # store-level invariant check, so a deleted entry needs no special case (unlike
    # DATA_PLANE_OWNERS above, where each file has its own validator and a deletion
    # would be a false red).
    #
    # Why this route did not exist until now (IMP-20260805-9a51e9): `validate` has
    # had ZERO automatic callers since it was written — not CI, not any ops/*.sh,
    # not this file. Its only mention outside its own tests is a prose instruction
    # in .claude/agents/platform-steward.md, so it ran only when an agent happened
    # to read that line. Meanwhile the generated VIEW is machine-checked (registry
    # `check:` -> render --check). The tool guaranteed the table matched the store
    # and guaranteed nothing about whether the store was true.
    # Top level only: `validate_store` globs `*.json` non-recursively, so a nested
    # path would be routed, counted as covered, and never actually read — a vacuous
    # pass one directory deeper than the one this route guards.
    backlog_entries = [p for p in changed_files
                       if p.startswith(BACKLOG_STORE_DIR)
                       and p.endswith(".json")
                       and "/" not in p[len(BACKLOG_STORE_DIR):]]
    # Keyed on the VALIDATOR too, not just the data. Otherwise the checker can change
    # without anyone running it against real entries: a commit touching only
    # ops/backlog.py passes ops-pytest on its own fixtures, cuts over green, and can
    # leave the whole store invalid — after which the next unrelated agent to edit any
    # entry eats problems they did not cause, which is how a gate earns a reputation
    # for false alarms and gets muted. IMP-20260805-9a51e9 schedules exactly this: its
    # plan states the real store must go to 7 problems the moment its checks land.
    if backlog_entries or "ops/backlog.py" in changed_files:
        # `--baseline-check` turns the ratchet on: schema problems AND any entry
        # newly closed with no attributable verification. Without it the queue
        # (`list --unverified`) has zero automatic callers, which is the whole
        # difference between a mechanism and a ritual — and `validate` was
        # already on this rail, so the queue rides for free.
        gates.append(_shell("backlog-validate", "data",
                            ["ops/backlog.py", "validate", "--baseline-check"], "block"))
    if backlog_entries:
        # `validate` answers "is each entry well-formed"; it says NOTHING about whether
        # the generated view still matches the store. Mutating the store stales the
        # view, and that is the most-hit trap in this repo today. Without this, a
        # store-only diff would report "every changed file is routed" while the one
        # thing that actually breaks in that diff shape goes unwatched — strictly worse
        # than before this route existed, when `coverage` at least NAMED the file.
        # registry `check:` for runbook.improvement_backlog is `render --check`.
        registry_cmd = ["ops/docs_lint.sh", "--registry"]
        if registry_cmd not in [g["cmd"] for g in gates if g.get("cmd")]:
            gates.append(_shell(f"data-plane:{registry_cmd[0]}", "data",
                                registry_cmd, "block"))

    constitution_files = sorted(set(changed_files) & set(AGENT_CONSTITUTION))
    if constitution_files:
        gates.append(_shell("agent-constitution", "docs",
                            ["ops/tests/test_docs_lint.sh"], "block"))

    covered: set[str] = set()
    for bucket in (ios, ds, docs, backend, ops_py, shell_changed, data_yml,
                   backlog_entries, baselines, constitution_files):
        covered.update(bucket)
    cov = _coverage(changed_files, covered)
    note = "every changed file is routed to a gate or declared neutral"
    if cov["uncovered"]:
        note = ("no gate and no neutral rule covers: "
                + ", ".join(cov["uncovered"][:5])
                + (" …" if len(cov["uncovered"]) > 5 else ""))
    # Always planned, so `plan` is never empty and aggregate_verdict's
    # "pass (incl. empty)" branch is unreachable from cmd_gate.
    gates.append(_internal("coverage", "meta", "warn", note=note, **cov))
    return gate_tiers.annotate_plan(gates)


def gate_probe_corpus() -> list[list[str]]:
    """Return representative paths for every gate family the router can expose.

    Route facts that already have a data table are derived from that table.  The
    remaining paths are representative shapes: the AST extractor below is the
    guard that reports when this corpus misses a future route.
    """
    return (
        [[], ["CLAUDE.md"]]
        + [[key] for key in sorted(DATA_PLANE_OWNERS)]
        + [[f"{BACKLOG_STORE_DIR}IMP-0001.json"], ["ops/backlog.py"]]
        + [[f"ios/BooksAndVocabUITests/{name}.swift"]
           for name in sorted(_LIVE_ONLY_UITEST_CLASSES)]
        + [
            ["ios/BooksAndVocab/Views/X.swift"],
            ["ios/BooksAndVocabUITests/FooTests.swift"],
            ["docs/reference/tech_index.md"],
            ["backend/src/kg/app.py"],
            ["backend/tests/test_x.py"],
            ["ops/worktree_orchestrate.py"],
            ["ops/python_scan.py"],
            ["ops/docs_lint.sh"],
            ["design-system/tokens.json"],
            ["ops/i18n_baseline.txt"],
            ["CLAUDE.md"],
            ["README.md"],
        ]
    )


GATE_PROBE_UNDERIVABLE: dict[str, str] = {}


def _ast_gate_name(expr: ast.expr) -> str | None:
    """Extract the static family prefix from a gate name expression."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        name = expr.value
    elif isinstance(expr, ast.JoinedStr):
        if not expr.values or not (
            isinstance(expr.values[0], ast.Constant)
            and isinstance(expr.values[0].value, str)
        ):
            return None
        name = expr.values[0].value
    else:
        return None
    return name.split(":", 1)[0]


def block_gate_families_declared(source: str | None = None) -> set[str]:
    """AST-extract block gate families declared inside ``plan_gates``.

    Reading ``__file__`` rather than a repository-relative path is important for
    mutation probes that load a modified copy of this module from a temporary
    directory.
    """
    source_text = Path(__file__).read_text() if source is None else source
    tree = ast.parse(source_text, filename=str(Path(__file__)))
    plan = next(
        (node for node in ast.walk(tree)
         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
         and node.name == "plan_gates"),
        None,
    )
    if plan is None:
        return set()

    families: set[str] = set()
    level_positions = {"_shell": 3, "_internal": 2}
    for node in ast.walk(plan):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        position = level_positions.get(node.func.id)
        if position is None or len(node.args) <= position:
            continue
        level = node.args[position]
        if not (isinstance(level, ast.Constant) and level.value == "block"):
            continue
        if not node.args:
            continue
        family = _ast_gate_name(node.args[0])
        if family:
            families.add(family)
    return families


def gate_probe_coverage() -> dict[str, list[str]]:
    """Compare AST-declared block families with reachable corpus families."""
    declared = block_gate_families_declared()
    reachable: set[str] = set()
    for files in gate_probe_corpus():
        for gate in plan_gates(files, ops_test_exists=lambda rel: True, base="main"):
            if gate.get("level") == "block":
                reachable.add(str(gate["name"]).split(":", 1)[0])
    derivable_exceptions = set(GATE_PROBE_UNDERIVABLE)
    return {
        "declared": sorted(declared),
        "reachable": sorted(reachable),
        "unprobed": sorted(declared - reachable - derivable_exceptions),
        "stale": sorted(reachable - declared),
    }


# The closed vocabulary a gate result may carry. Named once so `aggregate_verdict`
# cannot drift from the producers: every `{"status": ...}` this module writes, plus
# `inconclusive`, which `_run_gate` sets when the refs probe could not be measured.
GATE_STATUSES = ("pass", "warn", "block", "inconclusive")


class UnknownGateStatus(Exception):
    """A gate reported something the aggregator has no rule for.

    An exception rather than a return value because there is no verdict to give: the
    caller asked "what did this batch come to" and the honest answer is "I cannot read
    one of the answers". Callers turn it into a block with the message attached.
    """


def assert_known_statuses(results: list[dict[str, Any]]) -> None:
    """Refuse, by name, any result whose status is outside `GATE_STATUSES`.

    Names BOTH the gate and the value it carried. A refusal that says only "unknown
    status" sends the reader to diff the payload by hand, and the payload is the one
    artefact they do not have in front of them when this fires.
    """
    unknown = [(str(r.get("name") or "<unnamed gate>"), r.get("status"))
               for r in results if r.get("status") not in GATE_STATUSES]
    if unknown:
        detail = ", ".join(f"{name} -> {value!r}" for name, value in unknown)
        raise UnknownGateStatus(
            f"gate result(s) carry a status this aggregator has no rule for: {detail}. "
            f"Known: {', '.join(GATE_STATUSES)}. Treated as BLOCK — an aggregator that "
            f"cannot read an answer has not been told the batch is fine.")


def aggregate_verdict(results: list[dict[str, Any]]) -> str:
    """block if any gate blocked or carried an unreadable status; else warn if any
    warned OR was inconclusive; else pass (incl. empty).

    `inconclusive` folds to WARN, and both of the other two folds would be wrong.
    `block` would kill a session's work for someone else's tag surgery — the red was
    real but not the branch's (IMP-20260805-4ec901). `pass` would be a claim nobody
    made: the gate never produced an attributable answer. `warn` is what this module
    already means by "degraded, named, disposition belongs to the driving agent", which
    is exactly the situation.

    An UNKNOWN status folds to BLOCK, and that is a different judgement from the one
    above (IMP-20260808-c6982d). Until 2026-08-09 the tail of this function was a bare
    `return "pass"`, so anything outside the two membership tests — including the
    `None` that `.get()` yields for a result dict with no `status` key at all — came
    out green. No producer emits an unknown value today, which is exactly what made it
    survive: it is armed for whoever adds the next status, and `timeout` is already
    named by two open entries. Not `warn`, because `warn` is a state somebody JUDGED;
    an unrecognised status is a state nobody judged.
    """
    try:
        assert_known_statuses(results)
    except UnknownGateStatus as exc:
        # Printed, not swallowed. The first draft caught this bare and returned
        # "block" — which satisfied the ticket's first half (fold to block) while
        # silently dropping its second (name the gate and the value), leaving that
        # half with no production path at all and only a unit test calling
        # `assert_known_statuses` directly to make it look covered.
        print(f"[worktree][gate] {exc}", file=sys.stderr, flush=True)
        return "block"
    statuses = {r.get("status") for r in results}
    if "block" in statuses:
        return "block"
    if "warn" in statuses or "inconclusive" in statuses:
        return "warn"
    return "pass"
