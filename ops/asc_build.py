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
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from asc_get import get, mint_token  # noqa: E402


APP_ID = os.environ.get("ASC_APP_ID", "6759816274")


class AscBuildError(RuntimeError):
    """ASC returned an unusable response or could not be queried."""


class NoExactBuild(AscBuildError):
    """The response did not contain exactly one requested build."""


def select_exact_build(
    payload: dict, *, marketing_version: str, build_number: str
) -> dict[str, str]:
    """Validate and normalize one exact iOS build from an ASC response."""

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
            continue
        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            continue
        platform = attrs.get("platform") or attrs.get("appPlatform")
        if platform is not None and platform != "IOS":
            continue
        if attrs.get("versionString") != marketing_version:
            continue
        if str(attrs.get("version", "")) != str(build_number):
            continue
        matches.append(item)

    if len(matches) != 1:
        raise NoExactBuild(
            f"ASC exact build match is not unique for IOS "
            f"{marketing_version} build {build_number}: count={len(matches)}"
        )

    item = matches[0]
    attrs = item["attributes"]
    build_id = item.get("id")
    state = attrs.get("processingState")
    if not isinstance(build_id, str) or not build_id:
        raise AscBuildError("ASC exact build is missing a stable id")
    if not isinstance(state, str) or not state:
        raise AscBuildError("ASC exact build is missing processingState")

    return {
        "schema": "kg.asc.build.v1",
        "id": build_id,
        "version": marketing_version,
        "build": str(build_number),
        "platform": "IOS",
        "processingState": state,
    }


def lookup_exact_build(marketing_version: str, build_number: str) -> dict[str, str]:
    """Fetch the filtered build collection and return exact provenance."""

    encoded_version = quote(marketing_version, safe="")
    encoded_build = quote(str(build_number), safe="")
    payload = get(
        f"/v1/apps/{APP_ID}/builds"
        f"?filter%5BappPlatform%5D=IOS"
        f"&filter%5BversionString%5D={encoded_version}"
        f"&filter%5Bversion%5D={encoded_build}"
        "&limit=50",
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
    except (AscBuildError, OSError) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
