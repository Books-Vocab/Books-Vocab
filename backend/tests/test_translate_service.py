from __future__ import annotations

from types import SimpleNamespace

from kg.api_models import TranslateRequest
from kg.translate_service import (
    _parse_json_payload as parse_json_payload,
    run_explain_translate,
    run_phrase_translate,
    run_quick_translate,
)


def _fake_client(content: str):
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
                    usage=None,
                )
            )
        )
    )


def test_parse_json_payload_supports_list_and_dict():
    assert parse_json_payload('{"t":"喚起"}') == {"t": "喚起"}
    assert parse_json_payload('[{"t":"喚起"}]') == {"t": "喚起"}
    assert parse_json_payload(None) == {}


def test_run_quick_translate_returns_expected_shape():
    req = TranslateRequest(word="evoke", context="The story can evoke deep memories.")
    result = run_quick_translate(
        req,
        {"id": "u_test"},
        client=_fake_client('{"t":"喚起","p":"v.","r":"evoke"}'),
        logger=SimpleNamespace(error=lambda *args, **kwargs: None),
    )
    assert result.t == "喚起"
    assert result.p == "v."
    assert result.r == "evoke"


def test_run_phrase_and_explain_translate_return_expected_shapes():
    req = TranslateRequest(word="on trial", context="He was on trial for fraud.")

    phrase = run_phrase_translate(
        req,
        {"id": "u_test"},
        client=_fake_client('{"t":"受審"}'),
    )
    assert phrase == {"t": "受審"}

    explain = run_explain_translate(
        req,
        {"id": "u_test"},
        client=_fake_client('{"e":"這裡表示因案件而受審。"}'),
    )
    assert explain.e == "這裡表示因案件而受審。"
