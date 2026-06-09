"""Policy unit tests for ops/ui_deadcode.py — the orphan judgement, no build needed.

Locks the rules that the throwaway Swift tool got wrong, especially that a
same-file reference counts as production use (the bug that hid CardDocumentHeroBlock
as a false orphan in the original scan).
"""
import importlib.util
import json
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent
FIXTURES = OPS / "fixtures" / "ui_deadcode"

_spec = importlib.util.spec_from_file_location("ui_deadcode", OPS / "ui_deadcode.py")
ui_deadcode = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui_deadcode)


def _records():
    return json.loads((FIXTURES / "records_sample.json").read_text())


def _names(orphans):
    return [o["name"] for o in orphans]


def test_default_kinds_orphan_set():
    # default kinds are struct+class only; the enum ProdOrphanTestOnly is excluded.
    orphans = ui_deadcode.classify_orphans(_records())
    # ordered by (totalRefs asc, name): 0 refs (struct), then 2 (class, debug-only)
    assert _names(orphans) == ["ProdOrphanNoRefs", "ProdOrphanDebugOnly"]


def test_enum_excluded_by_default_included_when_requested():
    default = ui_deadcode.classify_orphans(_records())
    assert "ProdOrphanTestOnly" not in _names(default)  # enum not in default kinds
    widened = ui_deadcode.classify_orphans(_records(), kinds=("struct", "class", "enum"))
    assert "ProdOrphanTestOnly" in _names(widened)


def test_coding_keys_is_never_an_orphan():
    """Codable CodingKeys is compiler-synthesized — never an explicit ref, never dead."""
    records = {
        "version": 1,
        "sourceRoot": "ios/BooksAndVocab/",
        "symbols": [
            {
                "kind": "enum",
                "name": "CodingKeys",
                "usr": "s:ck",
                "def": {"path": "/repo/ios/BooksAndVocab/Models/M.swift", "line": 20},
                "refs": [],
            }
        ],
    }
    orphans = ui_deadcode.classify_orphans(records, kinds=("enum",))
    assert orphans == []


def test_same_file_ref_counts_as_production():
    """Regression: a type referenced only within its own file is NOT an orphan."""
    orphans = ui_deadcode.classify_orphans(_records())
    assert "NotOrphanSameFile" not in _names(orphans)


def test_other_production_ref_is_not_orphan():
    orphans = ui_deadcode.classify_orphans(_records())
    assert "NotOrphanOtherProd" not in _names(orphans)


def test_debug_defined_type_is_not_a_production_orphan():
    """A type DEFINED under /Debug/ is debug code, never a production orphan."""
    orphans = ui_deadcode.classify_orphans(_records())
    assert "DebugDefIgnored" not in _names(orphans)


def test_kind_filter_excludes_unwanted_kinds():
    orphans = ui_deadcode.classify_orphans(_records())  # default excludes "extension"
    assert "WrongKindExtension" not in _names(orphans)


def test_explicit_kind_widening_includes_extension():
    orphans = ui_deadcode.classify_orphans(_records(), kinds=("extension",))
    assert _names(orphans) == ["WrongKindExtension"]


def test_custom_nonprod_markers():
    """Treating /Debug/ as production flips the debug-only orphan to non-orphan."""
    orphans = ui_deadcode.classify_orphans(
        _records(), nonprod_path_markers=("Tests/",), kinds=("struct", "class", "enum")
    )
    names = _names(orphans)
    assert "ProdOrphanDebugOnly" not in names  # debug refs now count as prod
    assert "ProdOrphanTestOnly" in names       # test (enum) refs still excluded


def test_orphan_record_shape():
    orphans = ui_deadcode.classify_orphans(_records())
    rec = next(o for o in orphans if o["name"] == "ProdOrphanDebugOnly")
    assert rec["kind"] == "class"
    assert rec["totalRefs"] == 2
    assert rec["prodRefs"] == 0
    assert rec["usr"] == "s:orphan2"
    assert rec["def"]["line"] == 8


def test_definition_role_ref_is_skipped_by_policy():
    """Defense: a ref carrying the 'definition' role must not count, independent
    of kgindex already stripping definitions upstream."""
    records = {
        "version": 1,
        "sourceRoot": "ios/BooksAndVocab/",
        "symbols": [
            {
                "kind": "struct",
                "name": "OnlyDefRoleRef",
                "usr": "s:defrole",
                "def": {"path": "/repo/ios/BooksAndVocab/Views/D.swift", "line": 1},
                "refs": [
                    {"path": "/repo/ios/BooksAndVocab/Views/Other.swift", "line": 9, "roles": ["definition"]}
                ],
            }
        ],
    }
    orphans = ui_deadcode.classify_orphans(records)
    rec = orphans[0]
    assert rec["name"] == "OnlyDefRoleRef"
    assert rec["totalRefs"] == 0  # the definition-role ref was skipped
    assert rec["prodRefs"] == 0


def test_build_payload_schema():
    records = _records()
    orphans = ui_deadcode.classify_orphans(records)
    payload = ui_deadcode.build_payload(records, orphans, records["sourceRoot"])
    assert payload["schema"] == "kg.ui.deadcode.v1"
    assert payload["scanned"] == len(records["symbols"])
    assert payload["orphanCount"] == len(orphans)
    assert "generated_at" in payload
