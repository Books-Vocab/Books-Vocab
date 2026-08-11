"""Pure, per-evidence evaluators for the App Review gate.

The evaluator layer deliberately has no filesystem, network, or subprocess
access.  The gate owns loading/hash-closure; these functions only validate an
already loaded value and return an immutable ``EvidenceResult``.  Keeping the
side-effect boundary here makes each evidence kind independently testable and
prevents a reducer from sharing mutable ``blocks``/claim state with a sibling
evaluator.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

JOURNEY_SCHEMA = "kg.app_review.journey.v1"
DEMO_SCHEMA = "kg.app_review.demo_access.v1"
URL_SCHEMA = "kg.app_review.url_checks.v1"
ATTESTATION_SCHEMA = "kg.app_review.attestation.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
JOURNEY_EVIDENCE_KINDS = frozenset({"exact-device", "release-equivalent-simulator"})
DEMO_EVIDENCE_KINDS = frozenset({"exact-device", "live-demo"})


@dataclass(frozen=True)
class EvidenceResult:
    """The only value an evidence evaluator may hand to the reducer.

    ``blocks`` is a tuple and claim evidence is frozen to tuples behind a
    read-only mapping.  The nested block dictionaries intentionally retain the
    existing JSON shape; the gate copies them when it renders its report.
    """

    blocks: tuple[Mapping[str, Any], ...] = ()
    files: Mapping[str, bytes] = field(default_factory=dict)
    evidence_by_claim: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    summary: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "blocks",
            tuple(_freeze(dict(block)) for block in self.blocks),
        )
        object.__setattr__(self, "files", _freeze(dict(self.files)))
        object.__setattr__(
            self,
            "evidence_by_claim",
            _freeze(dict(self.evidence_by_claim)),
        )
        object.__setattr__(self, "summary", _freeze(dict(self.summary)))
        object.__setattr__(self, "state", _freeze(dict(self.state)))


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a mutable JSON-shaped copy at the orchestration boundary."""

    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [thaw(item) for item in value]
    return value


def merge_result(
    blocks: list[dict[str, Any]],
    evidence_by_claim: dict[str, list[str]],
    result: EvidenceResult,
) -> None:
    """Apply one result at the orchestration boundary, preserving order."""

    blocks.extend(thaw(block) for block in result.blocks)
    for claim_id, evidence in result.evidence_by_claim.items():
        evidence_by_claim.setdefault(claim_id, []).extend(evidence)


def _block(blocks: list[dict[str, Any]], code: str, expected: Any, actual: Any) -> None:
    blocks.append({"code": code, "expected": expected, "actual": actual})


def _exact_keys(
    value: Any,
    expected: set[str],
    *,
    code: str,
    blocks: list[dict[str, Any]],
) -> bool:
    actual = set(value) if isinstance(value, dict) else set()
    if not isinstance(value, dict) or actual != expected:
        _block(blocks, code, sorted(expected), sorted(actual))
        return False
    return True


def _target_matches(
    target: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    prefix: str,
    blocks: list[dict[str, Any]],
) -> None:
    mapping = {
        "bundleID": "bundleId",
        "marketingVersion": "marketingVersion",
        "buildNumber": "buildNumber",
        "sourceCommit": "sourceCommit",
    }
    for expected_key, actual_key in mapping.items():
        if actual.get(actual_key) != target.get(expected_key):
            _block(blocks, f"{prefix}.target.{expected_key}", target.get(expected_key), actual.get(actual_key))


def _parse_time(value: Any, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a timezone-aware ISO8601 datetime")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a timezone-aware ISO8601 datetime") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _fresh(
    value: Any,
    *,
    observed_at: datetime,
    max_age_hours: Any = 24,
    label: str,
) -> tuple[bool, str | None]:
    try:
        timestamp = _parse_time(value, label=label)
        if not isinstance(max_age_hours, (int, float)) or max_age_hours <= 0:
            return False, f"{label} maxAgeHours must be positive"
    except (TypeError, ValueError) as exc:
        return False, str(exc)
    age_hours = (observed_at - timestamp).total_seconds() / 3600
    if age_hours < 0:
        return False, f"{label} is in the future"
    if age_hours > float(max_age_hours):
        return False, f"{label} is stale by {age_hours:.2f} hours"
    return True, None


def evaluate_desired(
    desired: Mapping[str, Any],
    *,
    desired_hash: str | None,
    target: Mapping[str, Any],
) -> EvidenceResult:
    """Validate the already hash-closed desired bundle summary."""

    blocks: list[dict[str, Any]] = []
    if desired_hash != target.get("desiredManifestSHA256"):
        _block(blocks, "desired.manifest-sha256", target.get("desiredManifestSHA256"), desired_hash)
    desired_values = {
        "marketingVersion": ((desired.get("build") or {}).get("marketingVersion")),
        "buildNumber": ((desired.get("build") or {}).get("buildNumber")),
        "sourceCommit": ((desired.get("source") or {}).get("commit")),
        "datasetID": ((desired.get("dataset") or {}).get("id")),
        "datasetSHA256": ((desired.get("dataset") or {}).get("sha256")),
        "screenshotDisplayType": desired.get("displayType"),
    }
    for key, actual in desired_values.items():
        if actual != target.get(key):
            _block(blocks, f"desired.target.{key}", target.get(key), actual)
    if ((desired.get("verdict") or {}).get("status")) != "pass":
        _block(blocks, "desired.status", "pass", (desired.get("verdict") or {}).get("status"))
    return EvidenceResult(blocks=tuple(blocks), state={"valid": not blocks})


def evaluate_live_mirror(
    live: Mapping[str, Any],
    *,
    desired: Mapping[str, Any],
    target: Mapping[str, Any],
    observed_at: datetime,
    live_mirror_max_age_hours: Any,
) -> EvidenceResult:
    """Validate the loaded live mirror against desired and target roots."""

    blocks: list[dict[str, Any]] = []
    live_body = live.get("live") if isinstance(live.get("live"), dict) else {}
    if live:
        if ((live.get("verdict") or {}).get("status")) != "pass":
            _block(blocks, "live-mirror.status", "pass", (live.get("verdict") or {}).get("status"))
            for mismatch in live.get("mismatches") or []:
                if isinstance(mismatch, dict) and isinstance(mismatch.get("code"), str):
                    _block(blocks, f"live-mirror.{mismatch['code']}", mismatch.get("expected"), mismatch.get("actual"))
        if ((live.get("desired") or {}).get("manifestSHA256")) != target.get("desiredManifestSHA256"):
            _block(
                blocks,
                "live-mirror.desired-root",
                target.get("desiredManifestSHA256"),
                (live.get("desired") or {}).get("manifestSHA256"),
            )
        desired_outputs = [
            {
                "fileName": str(item.get("file", "")).rsplit("/", 1)[-1],
                "sha256": item.get("sha256"),
                "byteSize": item.get("byteSize"),
            }
            for item in (desired.get("outputs") or [])
            if isinstance(item, dict)
        ]
        mirror_desired_outputs = [
            {
                "fileName": item.get("fileName"),
                "sha256": item.get("sha256"),
                "byteSize": item.get("byteSize"),
            }
            for item in ((live.get("desired") or {}).get("outputs") or [])
            if isinstance(item, dict)
        ]
        if desired_outputs != mirror_desired_outputs:
            _block(blocks, "live-mirror.desired-outputs-root", desired_outputs, mirror_desired_outputs)
        version = live_body.get("version") or {}
        build = live_body.get("build") or {}
        live_targets = {
            "appID": live_body.get("appID"),
            "versionID": version.get("id"),
            "marketingVersion": version.get("versionString"),
            "buildID": build.get("id"),
            "buildNumber": build.get("number"),
            "platform": version.get("platform"),
            "screenshotDisplayType": (live_body.get("screenshots") or {}).get("displayType"),
        }
        for key, actual in live_targets.items():
            if actual != target.get(key):
                _block(blocks, f"live-mirror.target.{key}", target.get(key), actual)
        live_output_bytes = [
            {
                "fileName": item.get("fileName"),
                "sha256": (item.get("liveBytes") or {}).get("sha256"),
                "byteSize": (item.get("liveBytes") or {}).get("byteSize"),
            }
            for item in (((live_body.get("screenshots") or {}).get("items")) or [])
            if isinstance(item, dict)
        ]
        if live_output_bytes != desired_outputs:
            _block(blocks, "live-mirror.live-outputs-root", desired_outputs, live_output_bytes)
        fresh, reason = _fresh(
            live_body.get("observedAt"),
            observed_at=observed_at,
            max_age_hours=live_mirror_max_age_hours,
            label="live mirror observedAt",
        )
        if not fresh:
            _block(blocks, "live-mirror.freshness", "fresh", reason)
    return EvidenceResult(blocks=tuple(blocks), state={"live_body": live_body})


def evaluate_journey(
    journey: Mapping[str, Any],
    *,
    ref: Mapping[str, Any],
    claims: list[Mapping[str, Any]],
    target: Mapping[str, Any],
    desired: Mapping[str, Any],
    observed_at: datetime,
    artifacts_ok: bool,
) -> EvidenceResult:
    """Evaluate one journey without reading its artifacts or mutating state."""

    blocks: list[dict[str, Any]] = []
    journey_id = ref.get("id")
    prefix = f"journey.{journey_id}"
    shape_ok = _exact_keys(
        journey,
        {"schema", "id", "claimIDs", "target", "execution", "world", "result", "artifacts"},
        code=f"{prefix}.shape",
        blocks=blocks,
    )
    if journey.get("schema") != JOURNEY_SCHEMA or journey.get("id") != journey_id:
        _block(blocks, f"{prefix}.schema", {"schema": JOURNEY_SCHEMA, "id": journey_id}, {"schema": journey.get("schema"), "id": journey.get("id")})
        return EvidenceResult(blocks=tuple(blocks), summary={"id": journey_id, "status": None, "evidenceKind": None})
    journey_target = journey.get("target") or {}
    shape_ok = _exact_keys(
        journey_target,
        {"bundleId", "marketingVersion", "buildNumber", "sourceCommit"},
        code=f"{prefix}.target.shape",
        blocks=blocks,
    ) and shape_ok
    _target_matches(target, journey_target, prefix=prefix, blocks=blocks)
    world = journey.get("world") or {}
    shape_ok = _exact_keys(world, {"datasetID", "sha256", "fixedClock"}, code=f"{prefix}.world.shape", blocks=blocks) and shape_ok
    for key, target_key in (("datasetID", "datasetID"), ("sha256", "datasetSHA256")):
        if world.get(key) != target.get(target_key):
            _block(blocks, f"{prefix}.world.{key}", target.get(target_key), world.get(key))
    if desired and world.get("fixedClock") != desired.get("fixedClock"):
        _block(blocks, f"{prefix}.world.fixedClock", desired.get("fixedClock"), world.get("fixedClock"))
    result = journey.get("result") or {}
    shape_ok = _exact_keys(result, {"status", "testsExecuted", "startedAt", "finishedAt"}, code=f"{prefix}.result.shape", blocks=blocks) and shape_ok
    status = result.get("status")
    if status != "pass":
        _block(blocks, f"{prefix}.status", "pass", status)
    if not isinstance(result.get("testsExecuted"), int) or result["testsExecuted"] <= 0:
        _block(blocks, f"{prefix}.tests", ">0", result.get("testsExecuted"))
    fresh, reason = _fresh(result.get("finishedAt"), observed_at=observed_at, max_age_hours=ref.get("maxAgeHours"), label=f"{prefix} finishedAt")
    if not fresh:
        _block(blocks, f"{prefix}.freshness", "fresh", reason)
    try:
        started = _parse_time(result.get("startedAt"), label=f"{prefix} startedAt")
        finished = _parse_time(result.get("finishedAt"), label=f"{prefix} finishedAt")
        if started > finished:
            _block(blocks, f"{prefix}.time-order", "startedAt <= finishedAt", result)
            shape_ok = False
    except (TypeError, ValueError) as exc:
        _block(blocks, f"{prefix}.time-order", "valid ordered timestamps", str(exc))
        shape_ok = False
    execution = journey.get("execution") or {}
    shape_ok = _exact_keys(
        execution,
        {"evidenceKind", "configuration", "device", "os", "locale", "timezone", "appearance", "networkMode"},
        code=f"{prefix}.execution.shape",
        blocks=blocks,
    ) and shape_ok
    for field_name in ("configuration", "device", "os", "locale", "timezone", "appearance", "networkMode"):
        if not isinstance(execution.get(field_name), str) or not execution[field_name]:
            _block(blocks, f"{prefix}.execution.{field_name}", "non-empty string", execution.get(field_name))
            shape_ok = False
    evidence_kind = execution.get("evidenceKind")
    if evidence_kind not in JOURNEY_EVIDENCE_KINDS:
        _block(blocks, f"{prefix}.evidence-kind", sorted(JOURNEY_EVIDENCE_KINDS), evidence_kind)
    claim_ids = journey.get("claimIDs")
    expected_claims = sorted(claim["id"] for claim in claims if journey_id in claim.get("journeyIDs", []))
    if not isinstance(claim_ids, list) or sorted(claim_ids) != expected_claims:
        _block(blocks, f"{prefix}.claims", expected_claims, claim_ids)
    valid = status == "pass" and fresh and artifacts_ok and shape_ok and evidence_kind in JOURNEY_EVIDENCE_KINDS and isinstance(claim_ids, list)
    evidence = {claim_id: (f"journey:{journey_id}:{evidence_kind}",) for claim_id in claim_ids} if valid else {}
    return EvidenceResult(
        blocks=tuple(blocks),
        evidence_by_claim=evidence,
        summary={"id": journey_id, "status": status, "evidenceKind": evidence_kind},
        state={"valid": valid, "evidenceKind": evidence_kind},
    )


def evaluate_demo(
    demo: Mapping[str, Any],
    *,
    ref: Mapping[str, Any],
    claims: list[Mapping[str, Any]],
    target: Mapping[str, Any],
    live_body: Mapping[str, Any],
    observed_at: datetime,
    artifacts_ok: bool,
) -> EvidenceResult:
    """Evaluate demo-access evidence and return claim tokens by kind."""

    blocks: list[dict[str, Any]] = []
    shape_ok = _exact_keys(demo, {"schema", "evidenceKind", "target", "execution", "account", "observedAt", "result", "artifacts"}, code="demo.shape", blocks=blocks)
    if demo.get("schema") != DEMO_SCHEMA:
        _block(blocks, "demo.schema", DEMO_SCHEMA, demo.get("schema"))
    demo_target = demo.get("target") or {}
    shape_ok = _exact_keys(demo_target, {"bundleId", "marketingVersion", "buildNumber", "sourceCommit"}, code="demo.target.shape", blocks=blocks) and shape_ok
    _target_matches(target, demo_target, prefix="demo", blocks=blocks)
    evidence_kind = demo.get("evidenceKind")
    if evidence_kind not in DEMO_EVIDENCE_KINDS:
        _block(blocks, "demo.evidence-kind", sorted(DEMO_EVIDENCE_KINDS), evidence_kind)
    execution = demo.get("execution") or {}
    shape_ok = _exact_keys(execution, {"configuration", "device", "os", "locale", "timezone", "networkMode", "fixtureDataUsed"}, code="demo.execution.shape", blocks=blocks) and shape_ok
    for field_name in ("configuration", "device", "os", "locale", "timezone", "networkMode"):
        if not isinstance(execution.get(field_name), str) or not execution[field_name]:
            _block(blocks, f"demo.execution.{field_name}", "non-empty string", execution.get(field_name))
            shape_ok = False
    if execution.get("configuration") != "Release":
        _block(blocks, "demo.execution.configuration", "Release", execution.get("configuration"))
        shape_ok = False
    if execution.get("networkMode") != "live":
        _block(blocks, "demo.execution.network-mode", "live", execution.get("networkMode"))
        shape_ok = False
    if execution.get("fixtureDataUsed") is not False:
        _block(blocks, "demo.fixture-data", False, execution.get("fixtureDataUsed"))
        shape_ok = False
    account = demo.get("account") or {}
    shape_ok = _exact_keys(account, {"provenance", "accountRef", "accountIdentitySHA256", "entitlementSource"}, code="demo.account.shape", blocks=blocks) and shape_ok
    live_demo_account = (((live_body.get("reviewDetail") or {}).get("fields") or {}).get("demoAccountName") or {})
    expected_account = {
        "provenance": "live-account",
        "accountRef": live_demo_account.get("ref"),
        "accountIdentitySHA256": live_demo_account.get("identitySHA256"),
        "entitlementSource": "live-backend",
    }
    if live_demo_account.get("identitySHA256") != target.get("demoAccountIdentitySHA256"):
        _block(blocks, "demo.account.target-binding", target.get("demoAccountIdentitySHA256"), live_demo_account.get("identitySHA256"))
        shape_ok = False
    if account != expected_account:
        _block(blocks, "demo.account.live-binding", expected_account, account)
        shape_ok = False
    result = demo.get("result") or {}
    shape_ok = _exact_keys(result, {"status", "login", "entitlements", "testsExecuted"}, code="demo.result.shape", blocks=blocks) and shape_ok
    if result.get("status") != "pass" or result.get("login") != "pass":
        _block(blocks, "demo.status", {"status": "pass", "login": "pass"}, result)
    if "pro" not in (result.get("entitlements") or []):
        _block(blocks, "demo.entitlement", "pro", result.get("entitlements"))
    if not isinstance(result.get("testsExecuted"), int) or result["testsExecuted"] <= 0:
        _block(blocks, "demo.tests", ">0", result.get("testsExecuted"))
        shape_ok = False
    fresh, reason = _fresh(demo.get("observedAt"), observed_at=observed_at, max_age_hours=ref.get("maxAgeHours"), label="demo observedAt")
    if not fresh:
        _block(blocks, "demo.freshness", "fresh", reason)
    valid = demo.get("schema") == DEMO_SCHEMA and evidence_kind in DEMO_EVIDENCE_KINDS and result.get("status") == "pass" and result.get("login") == "pass" and "pro" in (result.get("entitlements") or []) and fresh and artifacts_ok and shape_ok
    evidence = {claim["id"]: (f"demo:{evidence_kind}",) for claim in claims if valid and evidence_kind in claim.get("acceptedEvidenceKinds", [])}
    return EvidenceResult(
        blocks=tuple(blocks),
        evidence_by_claim=evidence,
        summary={"status": result.get("status"), "evidenceKind": evidence_kind},
        state={"valid": valid, "evidenceKind": evidence_kind},
    )


def evaluate_urls(
    urls: Mapping[str, Any],
    *,
    required_urls: list[Mapping[str, Any]],
    target: Mapping[str, Any],
    live_body: Mapping[str, Any],
    observed_at: datetime,
    max_age_hours: Any = 24,
) -> EvidenceResult:
    """Evaluate the closed URL-check result and map passing URLs to claims."""

    blocks: list[dict[str, Any]] = []
    shape_ok = _exact_keys(urls, {"schema", "observedAt", "results"}, code="urls.shape", blocks=blocks)
    if urls.get("schema") != URL_SCHEMA:
        _block(blocks, "urls.schema", URL_SCHEMA, urls.get("schema"))
    fresh, reason = _fresh(urls.get("observedAt"), observed_at=observed_at, max_age_hours=max_age_hours, label="URL checks observedAt")
    if not fresh:
        _block(blocks, "urls.freshness", "fresh", reason)
    results = urls.get("results") if isinstance(urls.get("results"), list) else []
    for index, item in enumerate(results):
        shape_ok = _exact_keys(item, {"id", "url", "status", "httpStatus", "finalUrl", "contentSHA256"}, code=f"urls.result.{index}.shape", blocks=blocks) and shape_ok
    by_id = {item.get("id"): item for item in results if isinstance(item, dict) and isinstance(item.get("id"), str)}
    if len(by_id) != len(results):
        _block(blocks, "urls.closed", "unique result per required URL", results)
        shape_ok = False
    required_ids = {item["id"] for item in required_urls}
    if set(by_id) != required_ids:
        _block(blocks, "urls.closed", sorted(required_ids), sorted(by_id))
        shape_ok = False
    evidence: dict[str, tuple[str, ...]] = {}
    for required in required_urls:
        result = by_id.get(required["id"])
        fields = ((live_body.get("metadata") or {}).get("fields") or {})
        metadata_field = {"marketing": "marketingUrl", "support": "supportUrl"}.get(required["id"])
        if metadata_field and fields.get(metadata_field) != required["url"]:
            _block(blocks, f"url.{required['id']}.live-metadata", required["url"], fields.get(metadata_field))
        if required["id"] == "terms" and required["url"] not in str(fields.get("description") or ""):
            _block(blocks, "url.terms.live-metadata", f"description contains {required['url']}", "missing")
        if not isinstance(result, dict):
            _block(blocks, f"url.{required['id']}.missing", required["url"], "missing")
            continue
        ok = result.get("url") == required["url"] and result.get("finalUrl") == required["url"] and result.get("status") == "pass" and isinstance(result.get("httpStatus"), int) and 200 <= result["httpStatus"] < 400 and isinstance(result.get("contentSHA256"), str) and bool(_SHA_RE.fullmatch(result["contentSHA256"])) and fresh and shape_ok
        if not ok:
            _block(blocks, f"url.{required['id']}.status", "fresh exact HTTPS 2xx/3xx", result)
        else:
            for claim_id in required.get("claimIDs", []):
                evidence.setdefault(claim_id, ())
                evidence[claim_id] = evidence[claim_id] + (f"url:{required['id']}:live-url",)
    return EvidenceResult(blocks=tuple(blocks), evidence_by_claim=evidence, state={"valid": not blocks})


def evaluate_attestation(
    attestation: Mapping[str, Any],
    *,
    actor: str,
    claim_ids: list[str],
    pre_root: str,
    observed_at: datetime,
    max_age_hours: Any,
) -> EvidenceResult:
    """Evaluate one human/agent attestation and produce its redacted summary."""

    blocks: list[dict[str, Any]] = []
    _exact_keys(attestation, {"schema", "actorType", "subject", "attestationKind", "claimIDs", "status", "preAttestationRootSHA256", "observedAt", "expiresAt"}, code=f"attestation.{actor}.shape", blocks=blocks)
    if attestation.get("schema") != ATTESTATION_SCHEMA or attestation.get("actorType") != actor:
        _block(blocks, f"attestation.{actor}.schema", {"schema": ATTESTATION_SCHEMA, "actorType": actor}, {"schema": attestation.get("schema"), "actorType": attestation.get("actorType")})
    if attestation.get("status") != "attested":
        _block(blocks, f"attestation.{actor}.status", "attested", attestation.get("status"))
    if attestation.get("attestationKind") != "semantic":
        _block(blocks, f"attestation.{actor}.kind", "semantic", attestation.get("attestationKind"))
    if attestation.get("claimIDs") != claim_ids:
        _block(blocks, f"attestation.{actor}.claims", claim_ids, attestation.get("claimIDs"))
    if not isinstance(attestation.get("subject"), str) or not attestation["subject"]:
        _block(blocks, f"attestation.{actor}.subject", "non-empty string", attestation.get("subject"))
    if attestation.get("preAttestationRootSHA256") != pre_root:
        _block(blocks, f"attestation.{actor}.root", pre_root, attestation.get("preAttestationRootSHA256"))
    fresh, reason = _fresh(attestation.get("observedAt"), observed_at=observed_at, max_age_hours=max_age_hours, label=f"{actor} attestation observedAt")
    try:
        expires = _parse_time(attestation.get("expiresAt"), label=f"{actor} attestation expiresAt")
        unexpired = expires >= observed_at
    except (TypeError, ValueError) as exc:
        unexpired = False
        reason = str(exc)
    if not fresh or not unexpired:
        _block(blocks, f"attestation.{actor}.freshness", "fresh and unexpired", reason or attestation.get("expiresAt"))
    summary = {"subject": attestation.get("subject"), "attestationKind": attestation.get("attestationKind"), "claimIDs": attestation.get("claimIDs"), "status": attestation.get("status"), "observedAt": attestation.get("observedAt"), "expiresAt": attestation.get("expiresAt")}
    return EvidenceResult(blocks=tuple(blocks), summary=summary, state={"valid": not blocks})


def evaluate_claims(
    claims: list[Mapping[str, Any]],
    *,
    evidence_by_claim: Mapping[str, list[str]],
    journey_evidence_by_id: Mapping[str, str],
    live_names: set[str],
    desired_names: set[str],
    required_url_ids: set[str],
    live_body: Mapping[str, Any],
) -> EvidenceResult:
    """Reduce per-kind evidence into the stable claim report."""

    blocks: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    for claim in claims:
        claim_id = claim["id"]
        accepted = [evidence for evidence in evidence_by_claim.get(claim_id, []) if evidence.rsplit(":", 1)[-1] in claim.get("acceptedEvidenceKinds", [])]
        missing_journeys = [journey_id for journey_id in claim.get("journeyIDs", []) if journey_evidence_by_id.get(journey_id) not in claim.get("acceptedEvidenceKinds", [])]
        if missing_journeys:
            _block(blocks, f"claim.{claim_id}.journeys", claim.get("journeyIDs", []), sorted(set(claim.get("journeyIDs", [])) - set(missing_journeys)))
        if not accepted or missing_journeys:
            _block(blocks, f"claim.{claim_id}.evidence", claim.get("acceptedEvidenceKinds", []), evidence_by_claim.get(claim_id, []))
        surface = claim["surface"]
        if surface["kind"] == "metadata":
            value = ((live_body.get("metadata") or {}).get("fields") or {}).get(surface["ref"])
            if not isinstance(value, str) or not value:
                _block(blocks, f"claim.{claim_id}.surface", f"live metadata {surface['ref']}", value)
        elif surface["kind"] == "review-notes":
            value = (((live_body.get("reviewDetail") or {}).get("fields") or {}).get(surface["ref"]))
            if not isinstance(value, dict) or value.get("present") is not True:
                _block(blocks, f"claim.{claim_id}.surface", f"present review field {surface['ref']}", value)
        elif surface["kind"] == "screenshot-copy" and (surface["ref"] not in live_names or surface["ref"] not in desired_names):
            _block(blocks, f"claim.{claim_id}.surface", {"desired": surface["ref"], "live": surface["ref"]}, {"desired": surface["ref"] in desired_names, "live": surface["ref"] in live_names})
        elif surface["kind"] == "website" and surface["ref"] not in required_url_ids:
            _block(blocks, f"claim.{claim_id}.surface", sorted(required_url_ids), surface["ref"])
        report.append({"id": claim_id, "surface": f"{surface['kind']}:{surface['ref']}", "statement": claim["statement"], "feature": claim["feature"], "entitlement": claim["entitlement"], "evidence": accepted})
    return EvidenceResult(blocks=tuple(blocks), summary={"claims": report}, state={"valid": not blocks})
