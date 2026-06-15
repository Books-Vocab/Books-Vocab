"""Boundary contract tests for the ops-edit error surface.

``EditError`` carries human-readable, Chinese, *unredacted* failure messages
(internal paths, uids) intended for the offline CLI operator — never for an
HTTP client. Two invariants keep it from leaking into the API layer:

  1. The HTTP layer (routers + the ``api*`` entrypoints) must never import the
     ``ops_edit`` family, so an ``EditError`` is physically unreachable from a
     request handler. The catch-all exception handler then turns any escaped
     ``Exception`` into a redacted 500 — the safest possible behaviour.
  2. ``EditError`` deliberately does NOT subclass ``KGError``. If it did, the
     framework's KGError->HTTP mapping would surface its internal message as a
     4xx body, defeating the redaction philosophy.

NOTE for a future maintainer: if an admin API endpoint ever needs to drive
edit logic, do NOT make ``EditError`` inherit ``KGError`` (that would leak
internals globally). Instead, in that specific endpoint, explicitly
``except EditError`` and convert it to a redacted ``BadRequestError`` so the
client sees a generic message while the original text stays server-side.
"""
from __future__ import annotations

from pathlib import Path

from kg.exceptions import KGError
from kg.ops_edit_shared import EditError

_SRC = Path(__file__).resolve().parents[1] / "src" / "kg"


def _http_layer_files() -> list[Path]:
    """Every source file that can sit on a request path: routers + api*."""
    files = sorted((_SRC / "routers").glob("*.py"))
    files += sorted(_SRC.glob("api*.py"))
    assert files, "expected to find HTTP-layer source files to scan"
    return files


def test_edit_error_not_imported_by_http_layer():
    """No router / api* file may import the ops_edit family.

    A textual scan (not import-graph) so it stays cheap and also catches a
    lazy/in-function import that an import-graph walk might miss. If this goes
    red, the offending file is wiring edit logic into a request handler —
    route it through an explicit redacting ``except EditError`` instead.
    """
    offenders: list[str] = []
    for path in _http_layer_files():
        text = path.read_text(encoding="utf-8")
        if "ops_edit" in text:
            offenders.append(str(path.relative_to(_SRC.parent)))
    assert not offenders, (
        "HTTP-layer files must not reference ops_edit "
        f"(EditError leak risk): {offenders}"
    )


def test_edit_error_is_not_kgerror():
    """EditError must stay off the KGError->HTTP mapping (records the split as
    an intentional decision, not an oversight)."""
    assert not issubclass(EditError, KGError)
