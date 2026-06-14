"""Emitter: demo SoT -> iOS UI World FixtureDatasetDocument.

Phase B implementation. Mirrors the Phase-A mapping contract below, byte-for-byte
deterministic so `--check` is a true drift gate.

OUTPUT PATH(S)
  ops/demo/generated/ios_fixture_dataset.json   (FixtureDatasetDocument JSON)

INJECTION SEAM (no Swift logic change to the loader)
  The fixture JSON is injected into the running app via the env var
  KG_FIXTURE_DATASET_B64 (base64 of the JSON file's bytes) — see
  ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift
  This emitter writes the *plaintext* JSON; the UITest harness base64s it into the
  env var via the existing seam:
      ./ops/ios_test.sh --ui --dataset-file ops/demo/generated/ios_fixture_dataset.json ...
  ios_test.sh base64-encodes the file into the runner's KG_FIXTURE_DATASET_B64, and
  UITestAppLaunch.swift (UITestLaunchConfiguration.launchEnvironment) already forwards
  that var into the app process. emit() also prints the ready-to-export base64 when
  commit so it can be exported directly without the shell helper.

SCHEMA NOTE
  The Phase-A skeleton planned schema "kg.fixture_dataset.v1". The Swift SoT
  (FixtureDatasetStore.decode + RepoFixtureDatasetsContractTests) is authoritative.
  Repo UI Worlds now use "kg.fixture.dataset.v2", which adds the top-level
  asset manifest. The generated demo world is emitted from the repo UI World
  manifest baseline, then only identity-owned auth fields and datasetID are
  overlaid from demo_identity.json. This keeps Catalog, UITest, visual capture,
  and generated demo on the same fixture shape instead of maintaining a second
  partial iOS fixture skeleton.

DOCUMENT SHAPE  (FixtureDatasetDocument top-level keys — exact, see Swift struct)
  schema       <- "kg.fixture.dataset.v2"
  datasetID    <- "demo-" + identity.user_id
  assets/settings/bookshelf/todayReview/notebook/podcast/runtimePodcast/reader/
                 vocabulary/reviewDeck <- copied from ops/fixtures/ui_worlds/marketing_demo.json
  auth         <- baseline auth fixture set, with signedIn identity fields
                 overlaid from demo identity and explicit keychain/UI auth state
  entitlements <- copied from the baseline UI World so generated demo exposes
                  the same free/pro/cancelled/admin catalog states

  Keyed decoding silently ignores unknown top-level keys; emit() MUST NOT add keys
  outside FixtureDatasetDocument.knownTopLevelKeys, and the domain sub-keys must
  be declared fixture IDs known by the Swift manifest contract.

CHECK MODE
  Re-emit the UI World file in memory, byte-compare against the committed artifact,
  return a drift verdict (exit 1 on drift via build_demo.py).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sot import DemoSoT

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent  # ops/demo -> ops -> repo root

GENERATED_DIR = _HERE / "generated"
FIXTURE_JSON_PATH = GENERATED_DIR / "ios_fixture_dataset.json"

FIXTURE_SCHEMA = "kg.fixture.dataset.v2"
BASE_UI_WORLD_PATH = _REPO_ROOT / "ops/fixtures/ui_worlds/marketing_demo.json"


def _build_fixture_document(sot: DemoSoT) -> dict[str, Any]:
    identity = sot.identity
    document = _load_base_ui_world()
    document["schema"] = FIXTURE_SCHEMA
    document["datasetID"] = f"demo-{identity['user_id']}"
    auth = dict(document["auth"])
    signed_in = dict(auth["signedIn"])
    signed_in.update(
        {
            "isLoggedIn": True,
            "userId": identity["user_id"],
            "token": identity["access_token"],
            "displayName": identity["display_name"],
            "email": identity["email"],
            "provider": identity["provider"],
            "providerUserId": identity["provider_user_id"],
            "keychainTokenState": "available",
            "authError": None,
            "isAuthenticating": False,
        }
    )
    auth["signedIn"] = signed_in
    document["auth"] = auth
    return document


def _load_base_ui_world() -> dict[str, Any]:
    data = json.loads(BASE_UI_WORLD_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{BASE_UI_WORLD_PATH} top-level must be a JSON object")
    if data.get("schema") != FIXTURE_SCHEMA:
        raise ValueError(
            f"{BASE_UI_WORLD_PATH} schema must be {FIXTURE_SCHEMA!r}, got {data.get('schema')!r}"
        )
    return data


def _json_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON: 2-space indent, UTF-8, no key reordering, trailing NL."""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _artifacts(sot: DemoSoT) -> list[tuple[Path, bytes]]:
    document = _build_fixture_document(sot)
    return [(FIXTURE_JSON_PATH, _json_bytes(document))]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        return str(path)


def emit(sot: DemoSoT, *, check: bool = False, commit: bool = False) -> dict:
    """Emit the iOS UI World FixtureDatasetDocument JSON from the SoT.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-emit in memory and byte-compare against the committed
            artifact(s); return a drift report instead of writing.
        commit: write the generated file(s) to disk (and print the base64 the
            harness exports as KG_FIXTURE_DATASET_B64). When False (and check
            False), dry-run returning the planned output paths.

    Returns:
        A dict describing the action (paths written / drift verdict / base64).
    """
    artifacts = _artifacts(sot)

    if check:
        drifted: list[dict[str, Any]] = []
        missing: list[str] = []
        for path, expected in artifacts:
            if not path.exists():
                missing.append(_rel(path))
                drifted.append({"path": _rel(path), "reason": "missing"})
                continue
            actual = path.read_bytes()
            if actual != expected:
                drifted.append(
                    {
                        "path": _rel(path),
                        "reason": "content-mismatch",
                        "committed_bytes": len(actual),
                        "fresh_bytes": len(expected),
                    }
                )
        return {
            "action": "check",
            "drift": bool(drifted),
            "drifted": drifted,
            "missing": missing,
            "checked": [_rel(p) for p, _ in artifacts],
        }

    if commit:
        written: list[str] = []
        for path, content in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written.append(_rel(path))
        fixture_b64 = base64.b64encode(artifacts[0][1]).decode("ascii")
        return {
            "action": "commit",
            "drift": False,
            "written": written,
            "datasetID": json.loads(artifacts[0][1])["datasetID"],
            "fixture_dataset_b64": fixture_b64,
            "inject_hint": (
                "export KG_FIXTURE_DATASET_B64=<fixture_dataset_b64>  # or: "
                "./ops/ios_test.sh --ui --dataset-file "
                f"{_rel(FIXTURE_JSON_PATH)} ..."
            ),
        }

    # dry-run
    return {
        "action": "dry-run",
        "drift": False,
        "planned_paths": [_rel(p) for p, _ in artifacts],
        "datasetID": json.loads(artifacts[0][1])["datasetID"],
    }
