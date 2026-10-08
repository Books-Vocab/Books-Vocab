from __future__ import annotations

import pytest
from pydantic import ValidationError

from kg.api_models.billing import AdminGrantRequest


@pytest.mark.parametrize("bad", ["2026-13-01", "next month", "10/31/2026"])
def test_unparseable_expires_at_is_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        AdminGrantRequest(expires_at=bad)


def test_valid_expires_at_is_normalized_to_aware_utc() -> None:
    expected = "2030-01-01T00:00:00+00:00"
    assert AdminGrantRequest(expires_at="2030-01-01").expires_at == expected
    assert AdminGrantRequest(expires_at="2030-01-01T08:00:00+08:00").expires_at == expected
    assert AdminGrantRequest(expires_at="2030-01-01T00:00:00Z").expires_at == expected


def test_empty_or_missing_expires_at_means_permanent() -> None:
    assert AdminGrantRequest().expires_at is None
    assert AdminGrantRequest(expires_at="  ").expires_at is None
