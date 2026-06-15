"""Single Source-of-Truth loader for the KG demo identity + dataset.

This module is the ONE authoritative entry point every emitter reads. It loads
and lightly validates the two authored JSON files that live next to it:

  - demo_identity.json  (schema "kg.demo_identity.v1")  -> load_identity()
  - demo_dataset.json   (schema "kg.demo_dataset.v1")   -> load_dataset()

"Lightly validate" means: presence of required keys + a couple of structural /
format invariants the downstream emitters and the backend `ops_edit seed`
prevalidator both rely on. It deliberately does NOT re-implement the full
backend seed prevalidation (that runs for real in emit_backend / `ops_edit
seed`); the goal here is to fail loud and early on an obviously broken SoT.

Pure: the only side effect is reading the two JSON files. No env, no network,
no writes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEMO_DIR = Path(__file__).resolve().parent
IDENTITY_PATH = DEMO_DIR / "demo_identity.json"
DATASET_PATH = DEMO_DIR / "demo_dataset.json"

IDENTITY_SCHEMA = "kg.demo_identity.v1"
DATASET_SCHEMA = "kg.demo_dataset.v1"

# Mirrors backend/src/kg/user_context.py::_USER_ID_ALLOWED. A demo user_id is
# joined into a filesystem path (data_dir/users/<user_id>); keep it path-safe.
_USER_ID_ALLOWED = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Mirrors backend ops_edit seed prevalidate: link.kind allowlist + review states.
_VALID_LINK_KINDS = {"contrasts_with", "shares_usage"}
_VALID_REVIEW_STATES = {"new", "due", "reviewed"}

_IDENTITY_REQUIRED = (
    "schema",
    "user_id",
    "email",
    "display_name",
    "provider",
    "provider_user_id",
    "access_token",
)


class SoTError(ValueError):
    """Raised when the authored demo SoT is missing/malformed."""


@dataclass(frozen=True)
class DemoSoT:
    """Validated bundle handed to every emitter.

    `identity` and `dataset` are the raw (validated) JSON dicts. Emitters read
    from them directly; this dataclass exists so a caller can load once and pass
    a single object around (build_demo.py does exactly this).
    """

    identity: dict[str, Any]
    dataset: dict[str, Any]


def _read_json(path: Path) -> Any:
    if not path.exists():
        raise SoTError(f"demo SoT file missing: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SoTError(f"{path.name} is not valid JSON: {exc}") from exc


def load_identity(path: Path = IDENTITY_PATH) -> dict[str, Any]:
    """Load + lightly validate the demo identity. Returns the raw dict."""
    data = _read_json(path)
    if not isinstance(data, dict):
        raise SoTError(f"{path.name} top-level must be a JSON object")
    if data.get("schema") != IDENTITY_SCHEMA:
        raise SoTError(
            f"{path.name} schema must be {IDENTITY_SCHEMA!r}, got {data.get('schema')!r}"
        )
    for key in _IDENTITY_REQUIRED:
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise SoTError(f"{path.name} missing/empty required string field: {key!r}")
    uid = data["user_id"]
    if ".." in uid or not _USER_ID_ALLOWED.match(uid):
        raise SoTError(
            f"{path.name} user_id {uid!r} is not path-safe "
            f"(must match [a-zA-Z0-9_.-]+ and contain no '..')"
        )
    if data["provider"] not in ("google", "apple", "demo"):
        raise SoTError(
            f"{path.name} provider must be one of google/apple/demo, got {data['provider']!r}"
        )
    return data


def load_dataset(path: Path = DATASET_PATH) -> dict[str, Any]:
    """Load + lightly validate the demo dataset (ops_edit seed-spec superset)."""
    data = _read_json(path)
    if not isinstance(data, dict):
        raise SoTError(f"{path.name} top-level must be a JSON object")
    if data.get("schema") != DATASET_SCHEMA:
        raise SoTError(
            f"{path.name} schema must be {DATASET_SCHEMA!r}, got {data.get('schema')!r}"
        )
    if not isinstance(data.get("review_anchor"), str) or not data["review_anchor"].strip():
        raise SoTError(f"{path.name} missing required string field: review_anchor")

    notebooks = data.get("notebooks")
    cards = data.get("cards")
    links = data.get("links", [])
    if not isinstance(notebooks, list) or not notebooks:
        raise SoTError(f"{path.name} notebooks must be a non-empty list")
    if not isinstance(cards, list) or not cards:
        raise SoTError(f"{path.name} cards must be a non-empty list")
    if not isinstance(links, list):
        raise SoTError(f"{path.name} links must be a list")

    nb_names: set[str] = set()
    for i, nb in enumerate(notebooks):
        name = (nb.get("name") if isinstance(nb, dict) else None) or ""
        if not name.strip():
            raise SoTError(f"{path.name} notebooks[{i}] missing name")
        if name in nb_names:
            raise SoTError(f"{path.name} duplicate notebook name: {name!r}")
        nb_names.add(name)

    # Cards must explicitly reference an existing (spec-declared) notebook,
    # carry non-empty content+meaning, and use a legal review.state. This is the
    # subset of the backend prevalidator that downstream emitters depend on for
    # a clean join.
    contents_by_nb: dict[str, set[str]] = {}
    for i, c in enumerate(cards):
        if not isinstance(c, dict):
            raise SoTError(f"{path.name} cards[{i}] must be an object")
        content = (c.get("content") or "").strip()
        if not content:
            raise SoTError(f"{path.name} cards[{i}] content empty")
        if not (c.get("meaning") or "").strip():
            raise SoTError(f"{path.name} cards[{i}] meaning empty: {content!r}")
        nb = c.get("notebook")
        if not isinstance(nb, str) or not nb.strip():
            raise SoTError(f"{path.name} cards[{i}] missing notebook")
        if nb not in nb_names:
            raise SoTError(
                f"{path.name} cards[{i}] notebook {nb!r} not declared in notebooks[]"
            )
        rv = c.get("review")
        if isinstance(rv, dict):
            st = rv.get("state")
            if st not in (None, "") and st not in _VALID_REVIEW_STATES:
                raise SoTError(
                    f"{path.name} cards[{i}] review.state {st!r} not in {_VALID_REVIEW_STATES}"
                )
        contents_by_nb.setdefault(nb, set()).add(content)

    for i, lk in enumerate(links):
        if not isinstance(lk, dict):
            raise SoTError(f"{path.name} links[{i}] must be an object")
        for k in ("from", "to", "kind", "confidence", "reason"):
            if lk.get(k) in (None, ""):
                raise SoTError(f"{path.name} links[{i}] missing {k}")
        if lk["kind"] not in _VALID_LINK_KINDS:
            raise SoTError(f"{path.name} links[{i}] kind {lk['kind']!r} not in {_VALID_LINK_KINDS}")
        try:
            conf = float(lk["confidence"])
        except (TypeError, ValueError) as exc:
            raise SoTError(f"{path.name} links[{i}] confidence not numeric") from exc
        if not 0.0 <= conf <= 1.0:
            raise SoTError(f"{path.name} links[{i}] confidence {conf} out of [0,1]")
        # Links are per-notebook: both endpoints must live in the link's notebook
        # (the backend resolves card refs within nb_id). Enforce the same join key
        # here so a malformed cross-notebook edge fails at the SoT, not at emit time.
        nb = lk.get("notebook")
        if not isinstance(nb, str) or not nb.strip():
            raise SoTError(f"{path.name} links[{i}] missing notebook")
        members = contents_by_nb.get(nb, set())
        for end in ("from", "to"):
            if lk[end] not in members:
                raise SoTError(
                    f"{path.name} links[{i}] {end} {lk[end]!r} is not a card in notebook {nb!r}"
                )

    return data


def load_sot(
    identity_path: Path = IDENTITY_PATH, dataset_path: Path = DATASET_PATH
) -> DemoSoT:
    """Load both files and return a single validated bundle."""
    return DemoSoT(
        identity=load_identity(identity_path),
        dataset=load_dataset(dataset_path),
    )
