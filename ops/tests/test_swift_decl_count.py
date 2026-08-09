from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("swift_decl_count", ROOT / "ops/swift_decl_count.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_nested_comments_and_strings_are_opaque() -> None:
    source = '''
    /* outer /* nested ) async @MainActor */ still comment */
    let text = "@MainActor and ) async"
    let raw = #"func fake() async {}"#
    '''
    tokens = MODULE.tokenize(source)
    assert MODULE.count_async_functions(tokens) == 0
    assert MODULE.count_main_actor_lines(tokens) == 0


def test_async_requires_async_after_balanced_parameter_list() -> None:
    source = '''
    func real(a: (Int, Int)) async throws -> Void {}
    func parameterOnly(callback: @escaping () async -> Void) -> Void {}
    func plain() throws -> Void {}
    '''
    assert MODULE.count_async_functions(MODULE.tokenize(source)) == 1


def test_main_actor_counts_attribute_lines_not_mentions() -> None:
    source = '''
    @MainActor final class View {}
    @MainActor
    func render() {}
    // @MainActor is prose
    '''
    assert MODULE.count_main_actor_lines(MODULE.tokenize(source)) == 2
