from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import HTTPException

from .api_models import ExplainResponse, QuickTranslateResponse, TranslateRequest


def quick_translate_prompt(req: TranslateRequest) -> str:
    return f'''英→繁中。給出翻譯、詞性、字典原形（lemma）。
詞性限定: n. / v. / adj. / adv. / conj. / prep.
字: "{req.word}"
句: "{req.context[:300]}"

lemma（r）規則：
- 必須是合法英文字，可在字典查到
- 禁止跨詞性（形容詞 lemma 仍是形容詞，非其衍生名詞）
- 動詞屈折形→動詞原形（例：hurrying→hurry, gazed→gaze）
- 名詞複數→單數（例：berries→berry）；無單數形式則回傳原字
- 形容詞/副詞若本身即原形，r 回傳原字
- 不確定時 r 回傳原字；絕不捏造不存在的英文字

輸出純 JSON（無 Markdown）：{{ "t": "...", "p": "...", "r": "..." }}'''


def phrase_translate_prompt(req: TranslateRequest) -> str:
    return f'''將以下英文片語/短語翻譯成繁體中文，給出最精確的中文對應。
片語: "{req.word}"
語境句子: "{req.context[:300]}"
輸出純 JSON（無 Markdown）：{{ "t": "..." }}'''


def explain_translate_prompt(req: TranslateRequest) -> str:
    return f'''用繁體中文簡短說明「{req.word}」在以下語境中的含義（1-2句）。
語境: "{req.context[:300]}"
請以純 JSON 格式回答，包含一個 key: "e" 為解釋內容。不要包含任何 Markdown 標記，直接輸出 {{ "e": "..." }}'''


def _parse_json_payload(raw: str | None) -> dict[str, Any]:
    data = json.loads(raw or "{}")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return {}
    return data


def track_usage(user_id: str, operation: str, response: Any) -> None:
    if not getattr(response, "usage", None):
        return
    from .token_tracker import record as track

    track(
        user_id,
        operation,
        getattr(response.usage, "prompt_tokens", 0) or 0,
        getattr(response.usage, "completion_tokens", 0) or 0,
    )


def run_quick_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any, logger: logging.Logger) -> QuickTranslateResponse:
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": quick_translate_prompt(req)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    if not response.choices:
        logger.error("translate/quick: Gemini returned empty choices. Full response: %s", response)
        raise HTTPException(500, "Gemini returned empty response")

    track_usage(user["id"], "translate_quick", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return QuickTranslateResponse(
        t=data.get("t", ""),
        p=data.get("p"),
        r=data.get("r"),
    )


def run_phrase_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any) -> dict[str, str]:
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": phrase_translate_prompt(req)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    track_usage(user["id"], "translate_phrase", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return {"t": data.get("t", "")}


def run_explain_translate(req: TranslateRequest, user: dict[str, Any], *, client: Any) -> ExplainResponse:
    response = client.chat.completions.create(
        model="gemini-2.5-flash-lite",
        messages=[{"role": "user", "content": explain_translate_prompt(req)}],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    track_usage(user["id"], "translate_explain", response)
    data = _parse_json_payload(response.choices[0].message.content)
    return ExplainResponse(e=data.get("e", ""))
