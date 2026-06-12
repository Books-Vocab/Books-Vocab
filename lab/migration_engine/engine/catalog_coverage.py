#!/usr/bin/env python3
"""
catalog_coverage.py — the loss meter for the AST front-end, measured over the whole
real SwiftUI corpus (ios/BooksAndVocab/Views, ~198 View structs).

Optimizing the migration system "with the catalog as a large training set" is blind
without a measurable loss. This harness IS that loss: it runs the SwiftSyntax dumper
over every View struct and aggregates

  - parse coverage   : structs the dumper produced IR for (vs crashed)
  - contract pass    : IR that validates against ir_contract (the seam)
  - node coverage    : resolved modifiers / total decorations (1 - unparsed_rate)
  - unparsed histogram: which SwiftUI modifiers/constructs degrade most often
                        → the priority queue for what to implement next
  - dirtiest structs : per-struct unparsed counts → where the long tail lives

Run: uv run python lab/migration_engine/engine/catalog_coverage.py [--json out.json] [--top N]
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ENG = ROOT / "lab/migration_engine/engine"
sys.path.insert(0, str(ENG))
from ir_contract import validate_ir  # noqa: E402

BIN = ROOT / "lab/swift_ast_dumper/.build/debug/swift-ast-dumper"
CORPUS = ROOT / "ios/BooksAndVocab/Views"

# unparsed strings are raw source fragments; classify by leading `.modifier(` or mark
# as a non-modifier expression (a bare view call / control-flow the lowerer punted on).
_MOD_RE = re.compile(r"^\.([A-Za-z_][A-Za-z0-9_]*)")


def classify_unparsed(s: str) -> str:
    s = s.strip()
    m = _MOD_RE.match(s)
    if m:
        return f".{m.group(1)}"
    # leading identifier call like `Button(...)` / `if ...` / `ForEach(...)`
    head = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", s)
    return f"<expr:{head.group(1)}>" if head else "<expr:?>"


def walk_nodes(node: dict):
    yield node
    for c in node.get("children", []) or []:
        yield from walk_nodes(c)


def dump_file(path: Path) -> dict | None:
    try:
        out = subprocess.run([str(BIN), str(path)], capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return {"__error__": "timeout"}
    if out.returncode != 0:
        return {"__error__": out.stderr.strip()[:200] or f"exit {out.returncode}"}
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as e:
        return {"__error__": f"bad json: {e}"}


def compute() -> dict:
    """Run the dumper over the whole corpus and aggregate the loss metrics. Returns a
    dict consumed by both main() (pretty print) and the regression gate."""
    files = sorted(CORPUS.rglob("*.swift"))
    n_files = len(files)
    n_structs = n_contract_ok = 0
    n_resolved_mods = n_unparsed = 0
    file_errors: list[tuple[str, str]] = []
    unparsed_hist: Counter[str] = Counter()
    dirtiest: list[tuple[int, str, str]] = []
    contract_violations: list[str] = []
    junk_tokens: list[str] = []  # honesty invariant: a mod token must never be raw closure text

    for f in files:
        ir = dump_file(f)
        if ir is None or "__error__" in ir:
            file_errors.append((str(f.relative_to(ROOT)), (ir or {}).get("__error__", "none")))
            continue
        errs = validate_ir(ir)
        for s in ir.get("structs", []):
            n_structs += 1
            root = s.get("root", {})
            su = sm = 0
            for n in walk_nodes(root):
                su += len(n.get("unparsed", []) or [])
                sm += len(n.get("modifiers", []) or [])
                for u in n.get("unparsed", []) or []:
                    unparsed_hist[classify_unparsed(u)] += 1
                for m in n.get("modifiers", []) or []:
                    tok = m.get("token")
                    if isinstance(tok, str) and ("{" in tok or "}" in tok):
                        junk_tokens.append(f"{s.get('name')}: {m.get('name')} token={tok[:40]!r}")
            n_unparsed += su
            n_resolved_mods += sm
            if su:
                dirtiest.append((su, s.get("name", "?"), str(f.relative_to(ROOT))))
        if not errs:
            n_contract_ok += 1
        else:
            contract_violations.append(f"{f.name}: {errs[0]}")

    total_decor = n_resolved_mods + n_unparsed
    return {
        "files": n_files, "dump_failed": len(file_errors), "structs": n_structs,
        "contract_ok": n_contract_ok, "resolved": n_resolved_mods, "unparsed": n_unparsed,
        "node_coverage": (n_resolved_mods / total_decor) if total_decor else 0.0,
        "histogram": dict(unparsed_hist), "errors": file_errors,
        "dirtiest": dirtiest, "contract_violations": contract_violations,
        "junk_tokens": junk_tokens,
    }


def main(argv: list[str]) -> int:
    if not BIN.exists():
        print(f"AST dumper not built: {BIN.relative_to(ROOT)}", file=sys.stderr)
        return 2
    top_n = 20
    out_json = None
    for i, a in enumerate(argv):
        if a == "--top" and i + 1 < len(argv):
            top_n = int(argv[i + 1])
        if a == "--json" and i + 1 < len(argv):
            out_json = argv[i + 1]

    r = compute()
    n_files = r["files"]; n_structs = r["structs"]; n_contract_ok = r["contract_ok"]
    n_resolved_mods = r["resolved"]; n_unparsed = r["unparsed"]; node_cov = r["node_coverage"]
    file_errors = r["errors"]; unparsed_hist = Counter(r["histogram"])
    dirtiest = r["dirtiest"]; contract_violations = r["contract_violations"]
    node_cov = r["node_coverage"]

    print("=" * 64)
    print("AST FRONT-END COVERAGE  (corpus = ios/BooksAndVocab/Views)")
    print("=" * 64)
    print(f"files                : {n_files}")
    print(f"files dump-failed    : {len(file_errors)}")
    print(f"View structs parsed  : {n_structs}")
    print(f"contract-valid files : {n_contract_ok}/{n_files - len(file_errors)}")
    print(f"resolved modifiers   : {n_resolved_mods}")
    print(f"unparsed decorations : {n_unparsed}")
    print(f"NODE COVERAGE        : {node_cov*100:.1f}%   (1 - unparsed_rate)")
    print()
    print(f"--- unparsed histogram (top {top_n}; = implement-next priority) ---")
    for name, cnt in unparsed_hist.most_common(top_n):
        print(f"  {cnt:4d}  {name}")
    print()
    print("--- dirtiest structs (top 12) ---")
    for su, name, f in sorted(dirtiest, reverse=True)[:12]:
        print(f"  {su:3d}  {name}  ({f})")
    if file_errors:
        print()
        print(f"--- dump-failed files ({len(file_errors)}) ---")
        for f, e in file_errors[:12]:
            print(f"  {f}: {e}")
    if contract_violations:
        print()
        print(f"--- contract violations ({len(contract_violations)}) ---")
        for v in contract_violations[:12]:
            print(f"  {v}")

    if out_json:
        Path(out_json).write_text(json.dumps({
            "files": n_files, "dump_failed": len(file_errors), "structs": n_structs,
            "contract_ok": n_contract_ok, "resolved": n_resolved_mods,
            "unparsed": n_unparsed, "node_coverage": node_cov,
            "histogram": dict(unparsed_hist), "errors": file_errors,
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {out_json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
