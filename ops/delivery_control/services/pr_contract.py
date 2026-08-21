"""Canonical PR body contract and durable hard-hold projection."""

from __future__ import annotations

import json

from ..domain.errors import InvalidReceipt, PolicyViolation
from ..domain.models import HandbackReceipt
from ..domain.observations import PullRequestSnapshot
from ..domain.states import HoldKind

_RECEIPT_BEGIN = "<!-- kg.delivery.receipt.v1\n"
_RECEIPT_END = "\n-->"
_HOLDS_BEGIN = "<!-- kg.delivery.holds.v1\n"
_HOLDS_END = "\n-->"
_HOLD_LABELS = {
    "delivery-hold:p0": HoldKind.P0,
    "delivery-hold:p1": HoldKind.P1,
    "delivery-hold:security": HoldKind.SECURITY,
}


def _machine_block(body: str, *, begin: str, end: str, name: str) -> object | None:
    count = body.count(begin)
    if count == 0:
        return None
    if count != 1:
        raise PolicyViolation(f"PR body must contain at most one typed {name}")
    start = body.index(begin) + len(begin)
    finish = body.find(end, start)
    if finish < 0 or begin in body[finish:]:
        raise PolicyViolation(f"PR body typed {name} is malformed")
    try:
        return json.loads(body[start:finish])
    except json.JSONDecodeError as error:
        raise PolicyViolation(f"PR body typed {name} is invalid JSON") from error


def parse_pull_request_body(body: str) -> HandbackReceipt:
    payload = _machine_block(
        body,
        begin=_RECEIPT_BEGIN,
        end=_RECEIPT_END,
        name="delivery receipt",
    )
    if payload is None:
        raise PolicyViolation("PR body must contain one typed delivery receipt")
    if not isinstance(payload, dict):
        raise PolicyViolation("PR body typed delivery receipt must be an object")
    try:
        receipt = HandbackReceipt.from_payload(payload)
    except InvalidReceipt as error:
        raise PolicyViolation("PR body typed delivery receipt is invalid") from error
    parse_body_holds(body)
    return receipt


def parse_body_holds(body: str) -> frozenset[HoldKind]:
    payload = _machine_block(
        body,
        begin=_HOLDS_BEGIN,
        end=_HOLDS_END,
        name="delivery holds",
    )
    holds: set[HoldKind] = set()
    if payload is not None:
        if (
            not isinstance(payload, dict)
            or payload.get("schema") != "kg.delivery.holds.v1"
        ):
            raise PolicyViolation("PR body typed delivery holds are invalid")
        raw_holds = payload.get("holds")
        if not isinstance(raw_holds, list):
            raise PolicyViolation("PR body typed delivery holds must be a list")
        try:
            holds.update(HoldKind(value) for value in raw_holds)
        except (TypeError, ValueError) as error:
            raise PolicyViolation(
                "PR body typed delivery hold is unsupported"
            ) from error

    legacy = body.lower()
    if (
        "publish only" in legacy
        or "security_hold" in legacy
        or "security hold" in legacy
    ):
        holds.add(HoldKind.SECURITY)
    if "p0 hold" in legacy or "hold:p0" in legacy:
        holds.add(HoldKind.P0)
    if "p1 hold" in legacy or "hold:p1" in legacy:
        holds.add(HoldKind.P1)
    return frozenset(holds)


def pull_request_holds(pull_request: PullRequestSnapshot | None) -> frozenset[HoldKind]:
    if pull_request is None:
        return frozenset()
    holds = set(parse_body_holds(pull_request.body))
    holds.update(pull_request_label_holds(pull_request))
    return frozenset(holds)


def pull_request_label_holds(
    pull_request: PullRequestSnapshot | None,
) -> frozenset[HoldKind]:
    if pull_request is None:
        return frozenset()
    holds: set[HoldKind] = set()
    for label in pull_request.labels:
        hold = _HOLD_LABELS.get(label.strip().lower())
        if hold is not None:
            holds.add(hold)
    return frozenset(holds)


def render_pull_request_body(
    receipt: HandbackReceipt,
    *,
    holds: frozenset[HoldKind] = frozenset(),
) -> str:
    scope_lines = "\n".join(
        f"- `{item.operation.value}` `{item.path}`" for item in receipt.scope.files
    )
    if receipt.validation:
        validation_lines = "\n".join(
            f"- exit `{item.exit_code}`: `{json.dumps(list(item.command), ensure_ascii=False)}`"
            for item in receipt.validation
        )
    else:
        validation_lines = (
            "- Local quality gates are not required before publication; "
            "GitHub required checks are authoritative."
        )
    ordered_holds = tuple(sorted(hold.value for hold in holds))
    hold_summary = ", ".join(f"`{hold}`" for hold in ordered_holds) or "none declared"
    documentation_impact = (
        "Scope includes documentation paths"
        if any(path.startswith("docs/") for path in receipt.scope.paths)
        else "no documentation path declared in Scope"
    )
    machine_receipt = json.dumps(
        receipt.to_payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    machine_holds = json.dumps(
        {"schema": "kg.delivery.holds.v1", "holds": list(ordered_holds)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        "## Scope\n"
        f"{scope_lines}\n\n"
        "## Handback\n"
        "- Registry handback schema: `kg.worktree.handback.v1`\n"
        f"- Normalized schema: `{receipt.schema}`\n"
        f"- Lane: `{receipt.lane_id}`\n"
        f"- Owner: `{receipt.owner_thread_id}`\n"
        f"- Claim generation: `{receipt.claim_generation}`\n"
        f"- Base SHA: `{receipt.base_sha}`\n"
        f"- Parent SHA: `{receipt.parent_sha}`\n"
        f"- Head SHA: `{receipt.head_sha}`\n"
        f"- Origin main observed by owner: `{receipt.origin_main_sha}`\n"
        f"- Scope fingerprint: `{receipt.scope.digest}`\n"
        f"- Digest: `{receipt.content_digest}`\n\n"
        "## Validation\n"
        f"{validation_lines}\n\n"
        "## Impact\n"
        f"- Explicit hard holds: {hold_summary}\n"
        f"- Documentation: {documentation_impact}.\n"
        "- Release/deploy: not declared by the local handback; release remains a separate SOP.\n\n"
        f"{_RECEIPT_BEGIN}{machine_receipt}{_RECEIPT_END}\n"
        f"{_HOLDS_BEGIN}{machine_holds}{_HOLDS_END}\n"
    )


def validate_pull_request_body(body: str, *, expected_head_sha: str) -> HandbackReceipt:
    receipt = parse_pull_request_body(body)
    if receipt.head_sha != expected_head_sha:
        raise PolicyViolation("PR body receipt differs from the exact PR HEAD")
    return receipt
