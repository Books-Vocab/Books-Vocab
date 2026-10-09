"""Canonical PR body contract and durable hard-hold projection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..domain.candidate_issues import issue_number_from_external_id
from ..domain.errors import InvalidReceipt, PolicyViolation
from ..domain.models import HandbackOutcome, HandbackReceipt
from ..domain.observations import PullRequestSnapshot
from ..domain.states import HoldKind

_RECEIPT_BEGIN = "<!-- kg.delivery.receipt.v1\n"
_RECEIPT_END = "\n-->"
_HOLDS_BEGIN = "<!-- kg.delivery.holds.v1\n"
_HOLDS_END = "\n-->"
_ISSUES_HEADING = "## Issues"
_BRANCH_ISSUE = re.compile(r"(?:^|/)issue-(?P<number>[1-9][0-9]*)(?:-|$)")
_ISSUE_LINE = re.compile(r"(?P<kind>Closes|Refs) #(?P<number>[1-9][0-9]*)")
_HOLD_LABELS = {
    "delivery-hold:p0": HoldKind.P0,
    "delivery-hold:p1": HoldKind.P1,
    "delivery-hold:security": HoldKind.SECURITY,
}


@dataclass(frozen=True)
class IssueLinks:
    """Issues a PR resolves (`Closes`) or only advances (`Refs`)."""

    closes: tuple[int, ...] = ()
    refs: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        closes = tuple(sorted(set(self.closes)))
        refs = tuple(sorted(set(self.refs)))
        if any(type(n) is not int or n < 1 for n in closes + refs) or set(closes) & set(
            refs
        ):
            raise PolicyViolation(
                "PR Issues must be distinct positive numbers across Closes and Refs"
            )
        object.__setattr__(self, "closes", closes)
        object.__setattr__(self, "refs", refs)

    @classmethod
    def from_external_ids(cls, external_ids: tuple[str, ...]) -> IssueLinks:
        """Registry external IDs naming an Issue close it (same rule as claims)."""
        numbers = (issue_number_from_external_id(value) for value in external_ids)
        return cls(closes=tuple(n for n in numbers if n is not None))

    @classmethod
    def from_branch(cls, branch: str) -> IssueLinks:
        """An `issue-<N>` branch segment names the Issue its PR resolves (#2654)."""
        number = issue_number_from_branch(branch)
        return cls(closes=(number,)) if number is not None else cls()

    def merged_with(self, other: IssueLinks) -> IssueLinks:
        """Union where this side's Closes/Refs choice wins for a shared number."""
        closes = set(self.closes) | {n for n in other.closes if n not in self.refs}
        refs = set(self.refs) | {n for n in other.refs if n not in closes}
        return IssueLinks(closes=tuple(closes), refs=tuple(refs))

    def __bool__(self) -> bool:
        return bool(self.closes or self.refs)

    def render(self) -> str:
        lines = [f"Closes #{n}" for n in self.closes]
        lines += [f"Refs #{n}" for n in self.refs]
        return f"{_ISSUES_HEADING}\n" + "\n".join(lines) + "\n\n" if lines else ""


NO_ISSUES = IssueLinks()


def issue_number_from_branch(branch: str) -> int | None:
    match = _BRANCH_ISSUE.search(branch)
    return int(match["number"]) if match is not None else None


def parse_body_issues(body: str) -> IssueLinks:
    """Read the `## Issues` section; keywords elsewhere in the body are prose."""
    lines = body.split("\n")
    starts = [i for i, line in enumerate(lines) if line == _ISSUES_HEADING]
    if not starts:
        return IssueLinks()
    if len(starts) != 1:
        raise PolicyViolation("PR body must contain at most one Issues section")
    found: dict[str, list[int]] = {"Closes": [], "Refs": []}
    for line in lines[starts[0] + 1 :]:
        if not line:
            break
        match = _ISSUE_LINE.fullmatch(line)
        if match is None:
            raise PolicyViolation("PR body Issues section is malformed")
        found[match["kind"]].append(int(match["number"]))
    return IssueLinks(closes=tuple(found["Closes"]), refs=tuple(found["Refs"]))


def salvage_body_issues(body: str) -> IssueLinks:
    """Issues of a body being repaired or replaced; a malformed section drops."""
    try:
        return parse_body_issues(body)
    except PolicyViolation:
        return IssueLinks()


def without_issues_section(body: str) -> str:
    """The body minus every `## Issues` block, for scans that must not see it."""
    kept: list[str] = []
    skipping = False
    for line in body.split("\n"):
        if line == _ISSUES_HEADING:
            skipping = True
        elif skipping and not line:
            skipping = False
        if not skipping:
            kept.append(line)
    return "\n".join(kept)


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
    parse_body_issues(body)
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
    issues: IssueLinks = NO_ISSUES,
) -> str:
    scope_lines = "\n".join(
        f"- `{item.operation.value}` `{item.path}`" for item in receipt.scope.files
    )
    validation_items: list[str] = []
    for index, item in enumerate(receipt.validation, start=1):
        if isinstance(item, HandbackOutcome):
            validation_items.append(
                f"- Handback outcome {index}: `{item.canonical_json}`"
            )
        else:
            validation_items.append(
                f"- exit `{item.exit_code}`: "
                f"`{json.dumps(list(item.command), ensure_ascii=False)}`"
            )
    if validation_items:
        validation_lines = "\n".join(validation_items)
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
    declared_initial_holds = (
        ", ".join(f"`{item}`" for item in receipt.initial_holds) or "none declared"
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
        f"- Handback initial holds: {declared_initial_holds}\n"
        f"- Explicit hard holds: {hold_summary}\n"
        f"- Documentation: {documentation_impact}.\n"
        "- Release/deploy: not declared by the local handback; release remains a separate SOP.\n\n"
        f"{issues.render()}"
        f"{_RECEIPT_BEGIN}{machine_receipt}{_RECEIPT_END}\n"
        f"{_HOLDS_BEGIN}{machine_holds}{_HOLDS_END}\n"
    )


def validate_pull_request_body(
    body: str, *, expected_head_sha: str, head_ref: str | None = None
) -> HandbackReceipt:
    receipt = parse_pull_request_body(body)
    if receipt.head_sha != expected_head_sha:
        raise PolicyViolation("PR body receipt differs from the exact PR HEAD")
    linked = parse_body_issues(body)
    for branch in (receipt.branch, head_ref):
        number = issue_number_from_branch(branch) if branch else None
        if number is not None and number not in linked.closes + linked.refs:
            raise PolicyViolation(
                f"branch {branch} names issue-{number} but the PR body has "
                f"neither Closes #{number} or Refs #{number}"
            )
    return receipt
