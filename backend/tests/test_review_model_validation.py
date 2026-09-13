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
