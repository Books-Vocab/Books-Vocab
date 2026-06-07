"""graph_history_synth.py — 把圖譜終態 link 確定式展開成合成生命史事件。

圖譜檔(``graph_{nb}.json``)只存每條 link 的「當前態」(id / from / to / kind /
confidence / reason / created_at / status),不存「怎麼變成這樣」的逐步歷史。一次性遷移
回填 ``graph_event_log`` 時,需要把終態反推成 :class:`GraphEventDraft` 序列,讓帳本有
回溯料(圖譜成長曲線 / link 密度演進 / 隱藏與棄用節奏)。

設計(對齊 ``demo_review_synth`` 的確定式合成哲學):

* **最小誠實**:只還原能從終態推得的東西 —— link 的誕生(``link_added``,錨定真實
  ``created_at``)與 status 生命線(born ``active`` → 終態)。**不**偽造 confidence 演進
  斜坡(我們只知終態 confidence,無中間值依據),故 birth 的 ``confidence_after`` 即終態
  confidence,``confidence_before=None``。
* **status 生命線**:terminal active → 單筆 add;terminal hidden → add + ``link_hidden``;
  terminal deprecated → add + ``link_deprecated``;terminal candidate → 單筆 add(born
  candidate,尚未升為 link)。link 由 pipeline 建立時預設 ``active``,故 hidden/deprecated
  皆視為 active 之後的轉移。
* **event_id** = ``synth-<link_id>-<seq>`` → 穩定;重跑經 store 的 event_id 去重而冪等。
* **source** = ``synth`` + ``is_synthetic=True`` → 研究時可 ``WHERE`` 一刀切開合成過去與
  真實未來。
* **時間**:add 錨定 ``created_at``;後續 transition 因無真實時點,置於 birth 之後 1µs,
  保證 ``occurred_at`` 在 link 內嚴格遞增且事件相異(回放順序正確)。

純函式、無副作用、確定式,刻意不用 RNG。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from .graph.models import GraphLink
from .graph_event_log import GraphEventDraft, GraphEventSource, GraphEventType

# terminal status → 從 active 轉移過去的事件型別。active/candidate 無轉移(見下)。
_TERMINAL_TRANSITION: dict[str, GraphEventType] = {
    "hidden": GraphEventType.LINK_HIDDEN,
    "deprecated": GraphEventType.LINK_DEPRECATED,
}


def _as_utc(dt: datetime) -> datetime:
    """正規化為 tz-aware UTC(圖譜檔可能存 naive created_at)。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def synthesize_graph_history(link: GraphLink, *, notebook_id: str) -> list[GraphEventDraft]:
    """把單條終態 link 展開成生命史事件(最舊在前)。"""
    born = _as_utc(link.created_at)
    status = str(link.status)
    kind = str(link.kind)
    # candidate 直接 born candidate(尚未升為正式 link);其餘一律 born active。
    birth_status = "candidate" if status == "candidate" else "active"
    drafts = [
        GraphEventDraft(
            event_id=f"synth-{link.id}-0",
            event_type=str(GraphEventType.LINK_ADDED),
            link_id=link.id,
            from_id=link.from_id,
            to_id=link.to_id,
            kind=kind,
            confidence_before=None,
            confidence_after=link.confidence,
            reason=link.reason,
            status_before=None,
            status_after=birth_status,
            source=str(GraphEventSource.SYNTH),
            notebook_id=notebook_id,
            occurred_at=born,
            is_synthetic=True,
        )
    ]
    transition = _TERMINAL_TRANSITION.get(status)
    if transition is not None:
        drafts.append(
            GraphEventDraft(
                event_id=f"synth-{link.id}-1",
                event_type=str(transition),
                link_id=link.id,
                from_id=link.from_id,
                to_id=link.to_id,
                kind=kind,
                confidence_before=link.confidence,
                confidence_after=link.confidence,
                # 終態無從得知「為何隱藏/棄用」,留 None 比沿用建立理由誠實 ——
                # 免得研究時把 transition.reason 誤讀為隱藏理由。
                reason=None,
                status_before="active",
                status_after=status,
                source=str(GraphEventSource.SYNTH),
                notebook_id=notebook_id,
                occurred_at=born + timedelta(microseconds=1),
                is_synthetic=True,
            )
        )
    return drafts


def synthesize_graph_history_many(
    links: Iterable[GraphLink], *, notebook_id: str
) -> list[GraphEventDraft]:
    """多條 link 的生命史攤平成單一 draft 序列。"""
    out: list[GraphEventDraft] = []
    for link in links:
        out.extend(synthesize_graph_history(link, notebook_id=notebook_id))
    return out
