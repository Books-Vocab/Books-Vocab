import pytest
from pydantic import ValidationError

from kg.api_models.review import ReviewStateEntry

_BASE_ENTRY = {
    "word": "example",
    "review_interval_hours": 24.0,
    "next_review_at": "2026-09-14T00:00:00Z",
    "last_reviewed_at": "2026-09-13T00:00:00Z",
    "review_count": 1,
    "lapse_count": 0,
    "review_streak": 1,
    "last_review_feedback": 1,
}


@pytest.mark.parametrize("field", ["review_count", "lapse_count", "review_streak"])
@pytest.mark.parametrize("value", [False, True])
def test_review_state_rejects_boolean_counter_values(field: str, value: bool) -> None:
    payload = {**_BASE_ENTRY, field: value}

    with pytest.raises(ValidationError):
        ReviewStateEntry.model_validate(payload)


@pytest.mark.parametrize("field", ["review_count", "lapse_count", "review_streak"])
def test_review_state_rejects_counters_above_int32(field: str) -> None:
    ReviewStateEntry.model_validate({**_BASE_ENTRY, field: 2_147_483_647})
    with pytest.raises(ValidationError):
        ReviewStateEntry.model_validate({**_BASE_ENTRY, field: 10**30})


@pytest.mark.parametrize("field", ["reviewCount", "lapseCount", "reviewStreak"])
def test_external_review_rejects_counters_above_int32(field: str) -> None:
    from kg.api_models.external_api import ExternalCardReviewRequest

    base = {
        "reviewIntervalHours": 24.0,
        "nextReviewAt": "2026-09-14T00:00:00Z",
        "lastReviewedAt": "2026-09-13T00:00:00Z",
        "reviewCount": 1,
        "lapseCount": 0,
        "reviewStreak": 1,
        "lastReviewFeedback": 1,
    }
    ExternalCardReviewRequest.model_validate({**base, field: 2_147_483_647})
    with pytest.raises(ValidationError):
        ExternalCardReviewRequest.model_validate({**base, field: 10**30})
