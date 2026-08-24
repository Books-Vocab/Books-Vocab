from __future__ import annotations

import math

import pytest

_ISO_NOW = "2026-05-14T12:00:00+00:00"


def _post_progress(api, *, position_literal: str, duration_literal: str):
    return api.client.post(
        "/api/podcasts/series_a/1/progress",
        content=(
            f'{{"position_sec": {position_literal}, "duration_sec": {duration_literal}, "updated_at": "{_ISO_NOW}"}}'
        ),
        headers={**api.headers, "content-type": "application/json"},
    )


@pytest.mark.parametrize(
    "field,bad_literal",
    [
        ("position_sec", "1e309"),
        ("position_sec", "Infinity"),
        ("position_sec", "NaN"),
        ("position_sec", "-Infinity"),
        ("duration_sec", "1e309"),
        ("duration_sec", "Infinity"),
        ("duration_sec", "NaN"),
        ("duration_sec", "-Infinity"),
    ],
)
def test_progress_rejects_nonfinite_values_before_persistence(isolated_api, field: str, bad_literal: str):
    values = {"position_sec": "10.0", "duration_sec": "100.0"}
    values[field] = bad_literal

    response = _post_progress(
        isolated_api,
        position_literal=values["position_sec"],
        duration_literal=values["duration_sec"],
    )

    assert response.status_code == 422
    assert response.json()
    stored = isolated_api.client.get(
        "/api/podcasts/series_a/1/progress",
        headers=isolated_api.headers,
    )
    assert stored.status_code == 404


def test_progress_preserves_finite_non_negative_values(isolated_api):
    response = _post_progress(
        isolated_api,
        position_literal="0.0",
        duration_literal="300.5",
    )

    assert response.status_code == 200
    assert response.json()["position_sec"] == 0.0
    assert response.json()["duration_sec"] == 300.5
    assert math.isfinite(response.json()["position_sec"])
    assert math.isfinite(response.json()["duration_sec"])
