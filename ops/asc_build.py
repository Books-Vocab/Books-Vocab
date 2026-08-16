#!/usr/bin/env -S uv run --with pyjwt --with cryptography python
"""Exact App Store Connect iOS build lookup.

The release transaction needs a read-only proof that ASC accepted the exact
``(marketing version, build number)`` it just uploaded.  The API query is
filtered for efficiency, but the response is still checked client-side for
identity and uniqueness before anything is treated as proof.

Exit codes:
  0 exact build found; JSON provenance is printed to stdout
  3 no exact build yet (usually ASC propagation/processing delay)
  1 API, auth, schema, or other lookup failure
"""

from __future__ import annotations

import json
import os
import sys
from urllib.parse import urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from asc_get import get, mint_token  # noqa: E402


APP_ID = os.environ.get("ASC_APP_ID", "6759816274")


class AscBuildError(RuntimeError):
    """ASC returned an unusable response or could not be queried."""


class NoExactBuild(AscBuildError):
    """The response did not contain the requested build yet."""


class AmbiguousExactBuild(AscBuildError):
    """More than one exact build matched; retrying cannot resolve this."""


ALLOWED_RELEASE_STATES = frozenset({"PROCESSING", "VALID"})


def _pre_release_attributes(payload: dict, item: dict) -> dict:
    relationships = item.get("relationships")
    if not isinstance(relationships, dict):
        raise AscBuildError("ASC exact build is missing preReleaseVersion relationship")
    relationship = relationships.get("preReleaseVersion")
    if not isinstance(relationship, dict):
        raise AscBuildError("ASC exact build has invalid preReleaseVersion relationship")
    linkage = relationship.get("data")
    if not isinstance(linkage, dict) or linkage.get("type") != "preReleaseVersions":
        raise AscBuildError("ASC exact build has invalid preReleaseVersion relationship")
    prerelease_id = linkage.get("id")
    if not isinstance(prerelease_id, str) or not prerelease_id:
        raise AscBuildError("ASC exact build has no preReleaseVersion relationship id")

    included = payload.get("included")
    if not isinstance(included, list):
        raise AscBuildError("ASC exact build response did not include preReleaseVersion")
    matches = [
        resource
        for resource in included
        if isinstance(resource, dict)
        and resource.get("type") == "preReleaseVersions"
        and resource.get("id") == prerelease_id
    ]
    if len(matches) != 1:
        raise AscBuildError(
            f"ASC preReleaseVersion relationship is not unique: id={prerelease_id} count={len(matches)}"
        )
    attributes = matches[0].get("attributes")
    if not isinstance(attributes, dict):
        raise AscBuildError("ASC preReleaseVersion is missing attributes")
    if not isinstance(attributes.get("version"), str) or not isinstance(
        attributes.get("platform"), str
    ):
        raise AscBuildError("ASC preReleaseVersion is missing version/platform")
    return attributes


def select_exact_build(
    payload: dict, *, marketing_version: str, build_number: str
) -> dict[str, str]:
    """Validate and normalize one exact iOS build from an ASC response."""

    if not isinstance(payload, dict):
        raise AscBuildError("ASC build lookup response is not an object")
    if "_httpError" in payload:
        raise AscBuildError(
            f"ASC build lookup failed: HTTP {payload.get('_httpError')} "
            f"{payload.get('_detail', '')}"
        )

    data = payload.get("data")
    if not isinstance(data, list):
        raise AscBuildError("ASC build lookup response has no data list")

    matches: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise AscBuildError("ASC build lookup response has malformed data entry")
        if item.get("type") != "builds":
            raise AscBuildError("ASC build lookup response has unexpected resource type")
        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            raise AscBuildError("ASC build lookup response has malformed data entry attributes")
        build_version = attrs.get("version")
        if not isinstance(build_version, str) or not build_version:
            raise AscBuildError("ASC build lookup response has invalid build version")
        if build_version != str(build_number):
            continue
        prerelease = _pre_release_attributes(payload, item)
        if prerelease["platform"] != "IOS" or prerelease["version"] != marketing_version:
            continue
        matches.append(item)

    if not matches:
        raise NoExactBuild(
            f"ASC exact build was not found for IOS {marketing_version} build {build_number}"
        )
    if len(matches) > 1:
        raise AmbiguousExactBuild(
            f"ASC exact build is ambiguous for IOS {marketing_version} build {build_number}: count={len(matches)}"
        )

    item = matches[0]
    attrs = item["attributes"]
    build_id = item.get("id")
    state = attrs.get("processingState")
    if not isinstance(build_id, str) or not build_id:
        raise AscBuildError("ASC exact build is missing a stable id")
    if not isinstance(state, str) or not state:
        raise AscBuildError("ASC exact build is missing processingState")
    if state not in ALLOWED_RELEASE_STATES:
        raise AscBuildError(
            f"ASC exact build processingState={state} is not release-eligible"
        )

    return {
        "schema": "kg.asc.build.v1",
        "id": build_id,
        "version": marketing_version,
        "build": str(build_number),
        "platform": "IOS",
        "processingState": state,
    }


def lookup_exact_build(marketing_version: str, build_number: str) -> dict[str, str]:
    """Fetch the app's filtered build collection and return exact provenance."""

    query = urlencode(
        [
            ("filter[app]", APP_ID),
            ("filter[version]", str(build_number)),
            ("include", "preReleaseVersion"),
            ("limit", "50"),
        ]
    )
    payload = get(
        f"/v1/builds?{query}",
        mint_token(),
    )
    return select_exact_build(
        payload, marketing_version=marketing_version, build_number=str(build_number)
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or not args[0] or not args[1].isdigit():
        print("用法：asc_build.py <marketing-version> <build-number>", file=sys.stderr)
        return 64

    try:
        result = lookup_exact_build(args[0], args[1])
    except NoExactBuild as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 3
    except AmbiguousExactBuild as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except (AscBuildError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - last-resort fail-closed boundary
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
