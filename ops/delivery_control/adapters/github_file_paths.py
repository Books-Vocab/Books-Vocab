"""Strict parsing for the batched GitHub pull-request file inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import AdapterPayloadError

_SAFE_CHANGE_TYPES = frozenset({"ADDED", "DELETED", "MODIFIED"})


@dataclass(frozen=True)
class PullRequestFilePathBatch:
    """Paths that are safe to use inline and PRs requiring exact REST fallback."""

    paths_by_number: Mapping[int, tuple[str, ...]]
    fallback_numbers: frozenset[int]


def parse_open_pull_request_file_pages(payload: object) -> PullRequestFilePathBatch:
    """Parse all pages from ``gh api graphql --paginate --slurp``.

    GraphQL's changed-file connection does not expose the old path for a
    rename.  A rename, an incomplete file connection, or any unknown change
    type therefore deliberately excludes that PR from the inline cache so the
    caller can use the REST endpoint, which preserves the old-path contract.
    """

    pages = _pages(payload)
    paths_by_number: dict[int, tuple[str, ...]] = {}
    fallback_numbers: set[int] = set()

    for page_index, page in enumerate(pages):
        connection = _pull_request_connection(page, page_index)
        nodes = connection["nodes"]
        page_info = connection["pageInfo"]
        has_next = page_info["hasNextPage"]
        if has_next:
            end_cursor = page_info.get("endCursor")
            if type(end_cursor) is not str or not end_cursor:
                raise AdapterPayloadError(
                    f"GitHub open PR page[{page_index}] pagination cursor is missing"
                )
        elif page_index != len(pages) - 1:
            raise AdapterPayloadError(
                f"GitHub open PR page[{page_index}] ended before the supplied pages"
            )

        for node_index, node in enumerate(nodes):
            number = _positive_int(
                node, "number", f"PR page[{page_index}] node[{node_index}]"
            )
            if number in paths_by_number or number in fallback_numbers:
                raise AdapterPayloadError(
                    f"GitHub open PR file inventory contains duplicate PR {number}"
                )
            files = node.get("files")
            if not isinstance(files, Mapping):
                raise AdapterPayloadError(
                    f"GitHub PR {number} files connection is malformed"
                )
            file_nodes = files.get("nodes")
            file_page_info = files.get("pageInfo")
            if not isinstance(file_nodes, list) or not isinstance(
                file_page_info, Mapping
            ):
                raise AdapterPayloadError(f"GitHub PR {number} files page is malformed")
            file_has_next = file_page_info.get("hasNextPage")
            if type(file_has_next) is not bool:
                raise AdapterPayloadError(
                    f"GitHub PR {number} files pageInfo is malformed"
                )
            if file_has_next:
                end_cursor = file_page_info.get("endCursor")
                if type(end_cursor) is not str or not end_cursor:
                    raise AdapterPayloadError(
                        f"GitHub PR {number} files pagination cursor is missing"
                    )

            paths: set[str] = set()
            needs_fallback = file_has_next
            for file_index, file_node in enumerate(file_nodes):
                if not isinstance(file_node, Mapping):
                    raise AdapterPayloadError(
                        f"GitHub PR {number} file[{file_index}] is malformed"
                    )
                path = file_node.get("path")
                change_type = file_node.get("changeType")
                if type(path) is not str or not path:
                    raise AdapterPayloadError(
                        f"GitHub PR {number} file[{file_index}] path is malformed"
                    )
                if type(change_type) is not str or not change_type:
                    raise AdapterPayloadError(
                        f"GitHub PR {number} file[{file_index}] change type is malformed"
                    )
                paths.add(path)
                if change_type not in _SAFE_CHANGE_TYPES:
                    needs_fallback = True

            if needs_fallback:
                fallback_numbers.add(number)
            else:
                paths_by_number[number] = tuple(sorted(paths))

    if pages and _page_has_next(pages[-1]):
        raise AdapterPayloadError("GitHub open PR pagination is incomplete")
    return PullRequestFilePathBatch(paths_by_number, frozenset(fallback_numbers))


def _pages(payload: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(payload, Mapping):
        return (payload,)
    if isinstance(payload, list) and all(isinstance(page, Mapping) for page in payload):
        return tuple(payload)
    raise AdapterPayloadError("GitHub open PR file payload is malformed")


def _pull_request_connection(
    page: Mapping[str, Any], page_index: int
) -> Mapping[str, Any]:
    if page.get("errors"):
        raise AdapterPayloadError("GitHub GraphQL response contains errors")
    data = page.get("data")
    repository = data.get("repository") if isinstance(data, Mapping) else None
    connection = (
        repository.get("pullRequests") if isinstance(repository, Mapping) else None
    )
    if not isinstance(connection, Mapping):
        raise AdapterPayloadError(
            f"GitHub open PR page[{page_index}] connection is malformed"
        )
    nodes = connection.get("nodes")
    page_info = connection.get("pageInfo")
    if not isinstance(nodes, list) or any(
        not isinstance(node, Mapping) for node in nodes
    ):
        raise AdapterPayloadError(
            f"GitHub open PR page[{page_index}] nodes are malformed"
        )
    if (
        not isinstance(page_info, Mapping)
        or type(page_info.get("hasNextPage")) is not bool
    ):
        raise AdapterPayloadError(
            f"GitHub open PR page[{page_index}] pageInfo is malformed"
        )
    return {"nodes": nodes, "pageInfo": page_info}


def _positive_int(node: Mapping[str, Any], key: str, context: str) -> int:
    value = node.get(key)
    if type(value) is not int or value <= 0:
        raise AdapterPayloadError(f"GitHub {context} {key} is malformed")
    return value


def _page_has_next(page: Mapping[str, Any]) -> bool:
    data = page.get("data")
    repository = data.get("repository") if isinstance(data, Mapping) else None
    connection = (
        repository.get("pullRequests") if isinstance(repository, Mapping) else None
    )
    page_info = connection.get("pageInfo") if isinstance(connection, Mapping) else None
    return isinstance(page_info, Mapping) and page_info.get("hasNextPage") is True
