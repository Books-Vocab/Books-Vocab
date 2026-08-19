import pytest

from kg.lexical_rate_limit import LexicalRateLimiter


@pytest.mark.parametrize("limit", [0, -1])
def test_rejects_non_positive_limit_at_construction(limit: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        LexicalRateLimiter(limit=limit)


@pytest.mark.parametrize("window_seconds", [0, -1])
def test_rejects_non_positive_window_at_construction(window_seconds: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        LexicalRateLimiter(window_seconds=window_seconds)


def test_positive_window_preserves_bounded_admission(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr("kg.lexical_rate_limit.monotonic", lambda: now[0])
    limiter = LexicalRateLimiter(limit=1, window_seconds=10)

    assert limiter.admit("user") is True
    assert limiter.admit("user") is False

    now[0] = 111.0
    assert limiter.admit("user") is True
