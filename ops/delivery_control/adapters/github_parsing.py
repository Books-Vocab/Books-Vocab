"""Pure parsing of GitHub query payloads into delivery observations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from ..domain.candidate_issues import (
    CANDIDATE_ISSUE_LABEL,
    CandidateIssue,
    CandidateIssueInventory,
)
from ..domain.errors import PolicyViolation
from ..domain.observations import (
    InventoryProblem,
    PullRequestInventory,
    PullRequestSnapshot,
)
from ..services.candidate_contract import parse_candidate_body
from .errors import AdapterPayloadError
from .timestamps import parse_optional_timestamp


def parse_pull_request(payload: Mapping[str, Any]) -> PullRequestSnapshot:
    required = {
        "id": str,
        "number": int,
        "url": str,
        "headRefName": str,
        "baseRefName": str,
        "baseRefOid": str,
        "headRefOid": str,
        "state": str,
        "isDraft": bool,
        "mergeable": str,
        "title": str,
        "body": str,
    }
    if any(type(payload.get(key)) is not expected for key, expected in required.items()):
        raise AdapterPayloadError("GitHub PR payload is malformed")
    auto_merge_request = payload.get("autoMergeRequest")
    if auto_merge_request is not None and not isinstance(auto_merge_request, Mapping):
        raise AdapterPayloadError("GitHub auto-merge payload is malformed")
    raw_labels = payload.get("labels", [])
    if not isinstance(raw_labels, list) or any(
        not isinstance(item, Mapping) or type(item.get("name")) is not str for item in raw_labels
    ):
        raise AdapterPayloadError("GitHub PR labels payload is malformed")
    return PullRequestSnapshot(
        number=payload["number"],
        url=payload["url"],
        branch=payload["headRefName"],
        base_branch=payload["baseRefName"],
        base_sha=payload["baseRefOid"],
        head_sha=payload["headRefOid"],
        state=payload["state"],
        draft=payload["isDraft"],
        mergeable=payload["mergeable"].upper() == "MERGEABLE",
        title=payload["title"],
        body=payload["body"],
        auto_merge_enabled=auto_merge_request is not None,
        node_id=payload["id"],
        labels=tuple(sorted({item["name"] for item in raw_labels})),
        created_at=parse_optional_timestamp(payload.get("createdAt"), field="GitHub PR createdAt"),
        merged_at=parse_optional_timestamp(payload.get("mergedAt"), field="GitHub PR mergedAt"),
    )


def parse_pull_request_inventory(
    payload: object,
    *,
    parse_record: Callable[[Mapping[str, Any]], PullRequestSnapshot] = parse_pull_request,
) -> PullRequestInventory:
    if not isinstance(payload, list):
        raise AdapterPayloadError("GitHub PR list must be a JSON list")
    records: list[PullRequestSnapshot] = []
    problems: list[InventoryProblem] = []
    for index, item in enumerate(payload):
        identity = f"entry[{index}]"
        if isinstance(item, Mapping):
            identity = f"PR#{item.get('number', index)}"
            try:
                records.append(parse_record(item))
                continue
            except AdapterPayloadError as error:
                reason = str(error)
        else:
            reason = "PR entry is not an object"
        problems.append(InventoryProblem("github", identity, reason))
    return PullRequestInventory(records=tuple(records), problems=tuple(problems))


def parse_candidate_issue(payload: Mapping[str, Any]) -> CandidateIssue:
    number = payload.get("number")
    url = payload.get("url")
    state = payload.get("state")
    labels = payload.get("labels")
    body = payload.get("body")
    if (
        type(number) is not int
        or type(url) is not str
        or state != "OPEN"
        or type(body) is not str
        or not isinstance(labels, list)
        or any(not isinstance(item, Mapping) or type(item.get("name")) is not str for item in labels)
    ):
        raise AdapterPayloadError("GitHub candidate Issue payload is malformed")
    if CANDIDATE_ISSUE_LABEL not in {item["name"] for item in labels}:
        raise AdapterPayloadError("GitHub candidate Issue lacks the exact delivery:candidate label")
    try:
        spec = parse_candidate_body(body)
        return CandidateIssue(number=number, url=url, spec=spec)
    except (PolicyViolation, ValueError) as error:
        raise AdapterPayloadError(str(error)) from error


def parse_candidate_issue_inventory(
    payload: object,
    *,
    parse_record: Callable[[Mapping[str, Any]], CandidateIssue] = parse_candidate_issue,
) -> CandidateIssueInventory:
    if not isinstance(payload, list):
        raise AdapterPayloadError("GitHub candidate Issue list must be a JSON list")
    records: list[CandidateIssue] = []
    problems: list[InventoryProblem] = []
    seen_numbers: set[int] = set()
    seen_urls: set[str] = set()
    for index, item in enumerate(payload):
        identity = f"entry[{index}]"
        if isinstance(item, Mapping):
            identity = f"Issue#{item.get('number', index)}"
            try:
                issue = parse_record(item)
                if issue.number in seen_numbers or issue.url in seen_urls:
                    raise AdapterPayloadError("GitHub candidate Issue inventory contains a duplicate")
                seen_numbers.add(issue.number)
                seen_urls.add(issue.url)
                records.append(issue)
                continue
            except AdapterPayloadError as error:
                reason = str(error)
        else:
            reason = "candidate Issue entry is not an object"
        problems.append(InventoryProblem("github", identity, reason))
    return CandidateIssueInventory(tuple(records), tuple(problems))


def parse_merge_times(payload: object) -> tuple[datetime, ...]:
    if not isinstance(payload, list):
        raise AdapterPayloadError("GitHub merge history must be a JSON list")
    observed: list[datetime] = []
    for index, item in enumerate(payload):
        if not isinstance(item, Mapping) or type(item.get("mergedAt")) is not str:
            raise AdapterPayloadError(f"GitHub merge history[{index}] is malformed")
        try:
            timestamp = datetime.fromisoformat(item["mergedAt"].replace("Z", "+00:00"))
        except ValueError as error:
            raise AdapterPayloadError(f"GitHub merge history[{index}] has an invalid timestamp") from error
        if timestamp.utcoffset() is None:
            raise AdapterPayloadError(f"GitHub merge history[{index}] timestamp is not aware")
        observed.append(timestamp)
    return tuple(sorted(observed))


def parse_changed_paths(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        raise AdapterPayloadError("GitHub PR files payload is malformed")
    pages = payload if all(isinstance(item, list) for item in payload) else [payload]
    paths: set[str] = set()
    item_index = 0
    for page in pages:
        if not isinstance(page, list):
            raise AdapterPayloadError("GitHub PR files page is malformed")
        for item in page:
            if not isinstance(item, Mapping):
                raise AdapterPayloadError(f"GitHub PR file[{item_index}] is malformed")
            filename = item.get("filename")
            status = item.get("status")
            if type(filename) is not str or type(status) is not str:
                raise AdapterPayloadError(f"GitHub PR file[{item_index}] is malformed")
            paths.add(filename)
            previous = item.get("previous_filename")
            if status == "renamed":
                if type(previous) is not str:
                    raise AdapterPayloadError(f"GitHub renamed file[{item_index}] lacks previous_filename")
                paths.add(previous)
            elif previous is not None and type(previous) is not str:
                raise AdapterPayloadError(f"GitHub PR file[{item_index}] previous_filename is malformed")
            item_index += 1
    return tuple(sorted(paths))
