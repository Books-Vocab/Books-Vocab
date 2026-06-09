"""LLM judge for user-initiated links (separate prompt, never returns None)."""

from __future__ import annotations

import json
import logging
import re

from ..exceptions import QuotaExceededError
from ..retry import llm_retryable_exceptions, sync_retry
from ..tracked_llm import TrackedLLM
from .models import Judgement
from .prompts import MANUAL_LINK_SYSTEM_PROMPT, MANUAL_USER_TEMPLATE

logger = logging.getLogger(__name__)

# Default degraded verdict — used for BOTH unparseable responses and
# transport failures (provider 5xx surviving sync_retry). Honors the
# "never returns None" contract: the user asked to link these two cards,
# so we keep a neutral shares_usage link rather than dropping the request.
_DEGRADED_LINK = "shares_usage"
_DEGRADED_REASON = "使用者認為這兩個詞相關。"


class ManualLinkJudge:
    """LLM judge for user-initiated links. Never returns None."""

    def __init__(self, llm: TrackedLLM, model: str | None = None,
                 *, user_id: str = "", notebook_id: str = "default") -> None:
        self.llm = llm
        self.model = model
        self.user_id = user_id
        self.notebook_id = notebook_id

    def _log(self, *, from_id: str, to_id: str, judgement: Judgement) -> None:
        if not self.user_id:
            return
        try:
            from .. import judge_log
            judge_log.record(
                user_id=self.user_id, notebook_id=self.notebook_id,
                from_id=from_id, to_id=to_id, similarity=None,
                verdict=judgement.link, confidence=judgement.confidence,
                accepted=True, reject_reason=None,
                reason=judgement.reason, source="manual",
            )
        except QuotaExceededError:
            raise
        except Exception:
            logger.warning("Failed to write judge_log (manual)", exc_info=True)

    @staticmethod
    def _parse_judgement(content: str) -> dict | None:
        """Parse the LLM response into a dict, tolerating a JSON object embedded
        in surrounding prose. Returns None when no valid object can be recovered."""
        try:
            return json.loads(content)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if not m:
                return None
            try:
                return json.loads(m.group())
            except (json.JSONDecodeError, ValueError):
                return None

    def _degraded(self, *, from_id: str, to_id: str) -> Judgement:
        """Neutral fallback shared by parse failures and transport failures."""
        j = Judgement(link=_DEGRADED_LINK, confidence=1.0, reason=_DEGRADED_REASON)
        self._log(from_id=from_id, to_id=to_id, judgement=j)
        return j

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
        *,
        from_id: str = "",
        to_id: str = "",
    ) -> Judgement:
        user_msg = MANUAL_USER_TEMPLATE.format(
            word_a=word_a, meaning_a=meaning_a, word_b=word_b, meaning_b=meaning_b,
        )

        try:
            # sync_retry rides out transient provider 5xx / rate limits (aligned
            # with enrich.py). Anything still failing after retries falls through
            # to the same graceful degrade as an unparseable response — the
            # exception must never surface to the route (never returns None).
            resp = sync_retry(
                self.llm.chat,
                # call_type group "JUDGE" — shares LLM_PROVIDER_JUDGE routing with
                # the auto pipeline judge ("judge"). Renamed from "manual_link_judge"
                # so the group split (key.split("_",1)[0]) lands on JUDGE not MANUAL.
                "judge_manual",
                model=self.model,
                messages=[
                    {"role": "system", "content": MANUAL_LINK_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_attempts=3,
                base_delay=2.0,
                retryable_exceptions=llm_retryable_exceptions(),
                step_name="Manual judge LLM",
                uid=self.user_id,
            )
        except QuotaExceededError:
            raise
        except Exception:
            logger.warning(
                "Manual judge LLM transport failure; degrading to %s",
                _DEGRADED_LINK, exc_info=True,
            )
            return self._degraded(from_id=from_id, to_id=to_id)

        content = resp.choices[0].message.content or ""

        data = self._parse_judgement(content)
        if data is None:
            return self._degraded(from_id=from_id, to_id=to_id)

        link_val = data.get("link", _DEGRADED_LINK)
        reason_val = data.get("reason", _DEGRADED_REASON)

        if link_val not in ("contrasts_with", "shares_usage"):
            link_val = _DEGRADED_LINK

        j = Judgement(link=link_val, confidence=1.0, reason=reason_val)
        self._log(from_id=from_id, to_id=to_id, judgement=j)
        return j
