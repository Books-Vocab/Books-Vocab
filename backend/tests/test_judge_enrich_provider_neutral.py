"""Phase 5: judge / enrich must not hardcode the Gemini provider.

`judge/batch.py` and `judge/manual.py` defaulted `model` to the literal
`"gemini-2.5-flash-lite"`; a caller that forgot to pass `model` would
send a Gemini model name to whatever endpoint the bound provider points
at (e.g. DeepSeek) — a silent footgun. `enrich.py`'s retry message was
hardcoded "Gemini API rate limit" though enrich can route to DeepSeek.
"""

from __future__ import annotations

import inspect


def test_judge_model_default_not_hardcoded_provider():
    """Judge.__init__ must not default `model` to a literal provider
    model name — it should be None so an omitted model fails loud at the
    call site rather than silently using a Gemini name."""
    from kg.judge.batch import Judge

    default = inspect.signature(Judge.__init__).parameters["model"].default
    assert default is None, f"model default should be None, got {default!r}"


def test_manual_link_judge_model_default_not_hardcoded_provider():
    from kg.judge.manual import ManualLinkJudge

    default = inspect.signature(ManualLinkJudge.__init__).parameters["model"].default
    assert default is None, f"model default should be None, got {default!r}"


def test_enrich_retry_detail_is_provider_neutral():
    """The enrich retry progress message must not name a specific
    provider — enrich routes via provider_for('enrich'), which can be
    DeepSeek."""
    from kg.enrich import _retry_detail

    msg = _retry_detail(4)
    assert "Gemini" not in msg
    assert "gemini" not in msg
    assert "retrying" in msg
    assert "4" in msg
