"""spec_world.py — kg.seed_spec.v1 → UI World v2 四 domain 的確定式投影（純函式）。

行銷帳號系統 Phase 2/6：`ops_cli world-export` 導出的 seed spec（Phase 1，
backend/src/kg/ops_world_export.py）→ iOS UI World v2 fixture 的
vocabulary / notebook / reviewDeck / todayReview 四個 domain。Phase 4 的
「改帳號資料 → 分鐘級重生 fixture → 截圖」視覺迭代迴圈的投影核心。

契約（違反 = fail-loud，不靜默降級）：
* 輸入必須是 `kg.seed_spec.v1`（schema / notebooks / cards / links 結構驗證，
  link 端點必須是同 notebook 的卡）。
* **確定式**：同一 spec 重跑 byte 相等。零 wall-clock（無 Date.now / now()）、
  零隨機值；所有排序 / 子集選取 / id 都是 spec 內容的純函式。
* **explicit-everything**：每個 row state 明示（syncStatus / actionType /
  isArchived / isExcludedFromReader / review scheduling counters /
  graphLinksByKind / reviewHistory refs），對齊 `ops/ui_world_manifest.py` 與
  Swift FixtureDatasetStore 的 fail-fast decode 契約。
* fixture id 只用 app-known id（FIXTURE_DOMAIN_IDS）；本模組**只回傳
  spec-derived 的 fixture id**，UI-chrome / gallery 語意的 id（如
  notebook.coverGallery、todayReview.longContent）由 emit_ios 沿用 baseline。

映射語意（deterministic selection rules）：
* primary notebook = active 卡最多者（tie-break: is_default、再 spec 順序）——
  真實帳號的預設單字本常是空殼，行銷資料住在別本。
* 卡片依 spec 順序；同 notebook 內同 content 去重（keep-first；fixture 要求
  seed 內 word 唯一）。
* due 排序 = 有 next_review_at 者依 (next_review_at, word) 升冪在前（越過期
  越前），未排程者依 spec 順序在後 —— 不引用「現在」也能穩定表達 due 優先序。
* review 計數器 → reviewHistory 合成對齊 backend `demo_review_synth` 語意：
  末 review_streak 筆 good、打斷 streak 的 lapse 緊鄰 good 尾、其餘 lapse 均勻
  散佈；時間自 last_reviewed_at 往過去回推，間隔以 1.7 成長、單段上限 30 天、
  每卡上限 _HISTORY_PER_CARD_MAX 筆（防 1.7^n 溢位；計數器本身保留 spec 真值，
  合成事件僅供 heatmap / stats 顯示）。
* datetime 一律正規化為 `YYYY-MM-DDTHH:MM:SSZ`（截去微秒）：iOS
  `AppDateFormatters.parseISO8601`（ISO8601DateFormatter）對 6 位小數秒不保證
  可解析，秒級 Z 格式是雙端最穩交集。
* spec 無書籍來源欄位（kg.seed_spec.v1 不含 source）→ bookTitle 用 notebook 名
  （validator 要求非空字串）、context 缺 example 時 fallback 為 word 本身、
  chapterTitle 一律 null（明示、非省略）。
* todayReview 卡片 dateAdded：Swift TodayReviewCardSeed.dateAdded 是非 optional
  Date → 必須確定式導出非空值（規則見 `_card_date_added` docstring；缺料逐級
  fallback 到 `_DATE_ADDED_FALLBACK_ANCHOR` 固定錨點，禁 Date.now / 隨機）。
* content-pinned fixtures 不投影：catalog scenario / UITest seam 釘死特定 word /
  query 命中數 / exact count / archived 量 / probeword deck 的 fixture（清單與
  SoT 註解 = `emit_ios.SPEC_BASELINE_KEPT_FIXTURES`，涵蓋 vocabulary 8 個 +
  reviewDeck probe/notebookReviewDeck）由 emit_ios 保留 baseline，本模組不得
  回傳這些 id——任意合法 spec（可 0 archived、0 命中）無法保證其斷言。
* seed 自足（link 域）：vocabulary / reviewDeck seed 的 graphLinksByKind target
  必須 resolve 到同 seed entries（Swift KG 圖面以 Set(entries.kgCardId) 驗證）
  → 子集投影時 prune 指向子集外的 link；todayReview 卡不 prune（baseline 語意
  即容許 cross-seed 顯示 chips）。
* 仍投影的 populated/dense fixtures 帶 catalog 端最低量斷言（vocabListPopulated
  ≥4、vocabListLong ≥40、statsPopulated ≥8 卡/≥12 事件、reviewCalendarDense
  ≥70 事件、knowledgeGraphPopulated ≥3 卡/≥2 link、reviewDeck.phaseMulti ==3）：
  這是行銷 spec 的資料量責任，投影器不擋薄 spec（測試/沙盒 spec 合法），量不足
  時對應 catalog surface 會 fail-loud。
* statsPopulated = primary 全 active 卡 + 全量合成事件（cap
  _HISTORY_STATS_MAX）：它是 Stats / ReviewCalendar 的敘事底稿（streak / 學習
  日曆 / totalCards）；只投影小樣本時 streak 與 heatmap 必崩。shellNavigation
  維持 _STATS_ENTRIES_MAX 小樣本（chrome smoke，非敘事面）。複習歷史敘事的
  上游 owner = ops/demo/marketing_account/shape_history.py（塑形 spec 的
  review 日期欄位），本模組只忠實合成，不造敘事。

測試：ops/tests/test_demo_ios_spec_emitter.py。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SEED_SPEC_SCHEMA = "kg.seed_spec.v1"

_VALID_LINK_KINDS = {"contrasts_with", "shares_usage"}
_VALID_MODES = {"recognition", "production"}
_LINK_LABELS = {"shares_usage": "相關", "contrasts_with": "對比"}

# ---- bounded deterministic selection constants ------------------------------
_TODAY_SESSION_MAX = 12      # todayReview 一場 session 的卡數上限
_DECK_MULTI_MAX = 3          # reviewDeck.phaseMulti
_LIST_LONG_MAX = 40          # vocabListLong（長列表捲動語意）
_KG_GRAPH_MAX = 24           # knowledgeGraphPopulated（圖面可渲染上限）
_STATS_ENTRIES_MAX = 8       # statsPopulated / shellNavigation entries
_SYNCING_MAX = 5             # vocabListSyncing
_PENDING_MIXED_MAX = 4       # syncPendingMixed
_HISTORY_PER_CARD_MAX = 40   # 每卡合成事件上限（防指數回推溢位）
_HISTORY_DENSE_MAX = 3000    # reviewCalendarDense 全域事件上限（fixture 體積）
_HISTORY_STATS_MAX = 3000    # statsPopulated（敘事底稿：全 active 卡事件，勿截舊日）
_HISTORY_SHELL_MAX = 200     # shellNavigation
_INTERVAL_GROWTH = 1.7       # 對齊 demo_review_synth 的往過去回推成長係數
_MIN_RECENT_GAP_HOURS = 8.0
_MAX_GAP_HOURS = 24.0 * 30   # 單段間隔上限（30 天）
_DATE_ADDED_LEAD_HOURS = 24.0  # dateAdded 至少早於最早 review 錨點 24h（卡先加入才被複習）
_DATE_ADDED_FALLBACK_ANCHOR = "2026-01-01T00:00:00Z"  # spec 全無日期素材時的固定錨點


class SpecWorldError(ValueError):
    """seed spec 缺欄 / 型別錯 / 引用斷裂 / 無法投影時 fail-loud。"""


# --------------------------------------------------------------------------- #
# loading / normalization
# --------------------------------------------------------------------------- #
def _norm_ts(raw: Any, *, owner: str) -> str | None:
    """spec datetime（isoformat，含微秒 / Z / offset）→ 'YYYY-MM-DDTHH:MM:SSZ'。"""
    if raw in (None, ""):
        return None
    s = str(raw).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as exc:
        raise SpecWorldError(f"{owner}: 無法解析 datetime {raw!r}") from exc
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return _fmt_ts(dt)


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_norm_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def _str_list(raw: Any, *, owner: str) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
        raise SpecWorldError(f"{owner}: 必須是 string list，got {raw!r}")
    return raw


def _difficulty_tier(raw: Any) -> str | None:
    """difficulty float → iOS difficultyTier 字串桶（core/intermediate/advanced）。"""
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 4.0:
        return "core"
    if value < 5.0:
        return "intermediate"
    return "advanced"


def load_seed_spec(path: Path) -> dict[str, Any]:
    """讀取 + 結構驗證 kg.seed_spec.v1。回傳原始（已驗證）dict。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecWorldError(f"seed spec 不是可讀 JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecWorldError(f"seed spec top-level 必須是 object: {path}")
    if data.get("schema") != SEED_SPEC_SCHEMA:
        raise SpecWorldError(
            f"seed spec schema 必須是 {SEED_SPEC_SCHEMA!r}，got {data.get('schema')!r}: {path}"
        )

    notebooks = data.get("notebooks")
    cards = data.get("cards")
    links = data.get("links", [])
    if not isinstance(notebooks, list) or not notebooks:
        raise SpecWorldError("seed spec notebooks 必須是非空 list")
    if not isinstance(cards, list) or not cards:
        raise SpecWorldError("seed spec cards 必須是非空 list")
    if not isinstance(links, list):
        raise SpecWorldError("seed spec links 必須是 list")

    nb_names: set[str] = set()
    for i, nb in enumerate(notebooks):
        if not isinstance(nb, dict):
            raise SpecWorldError(f"notebooks[{i}] 必須是 object")
        name = str(nb.get("name") or "").strip()
        if not name:
            raise SpecWorldError(f"notebooks[{i}] name 空白")
        if name in nb_names:
            raise SpecWorldError(f"notebooks[{i}] name 重複: {name!r}")
        nb_names.add(name)

    contents_by_nb: dict[str, set[str]] = {}
    for i, card in enumerate(cards):
        if not isinstance(card, dict):
            raise SpecWorldError(f"cards[{i}] 必須是 object")
        content = str(card.get("content") or "").strip()
        if not content:
            raise SpecWorldError(f"cards[{i}] content 空白")
        if not str(card.get("meaning") or "").strip():
            raise SpecWorldError(f"cards[{i}] ({content!r}) meaning 空白")
        nb = card.get("notebook")
        if nb not in nb_names:
            raise SpecWorldError(f"cards[{i}] ({content!r}) notebook {nb!r} 未宣告")
        mode = card.get("mode") or "recognition"
        if mode not in _VALID_MODES:
            raise SpecWorldError(f"cards[{i}] ({content!r}) mode {mode!r} 不在 {_VALID_MODES}")
        contents_by_nb.setdefault(nb, set()).add(content)

    for i, link in enumerate(links):
        if not isinstance(link, dict):
            raise SpecWorldError(f"links[{i}] 必須是 object")
        kind = link.get("kind")
        if kind not in _VALID_LINK_KINDS:
            raise SpecWorldError(f"links[{i}] kind {kind!r} 不在 {_VALID_LINK_KINDS}")
        nb = link.get("notebook")
        if nb not in nb_names:
            raise SpecWorldError(f"links[{i}] notebook {nb!r} 未宣告")
        members = contents_by_nb.get(nb, set())
        for end in ("from", "to"):
            if link.get(end) not in members:
                raise SpecWorldError(
                    f"links[{i}] {end} {link.get(end)!r} 不是 notebook {nb!r} 內的卡"
                )
        try:
            conf = float(link.get("confidence"))
        except (TypeError, ValueError) as exc:
            raise SpecWorldError(f"links[{i}] confidence 非數值") from exc
        if not 0.0 <= conf <= 1.0:
            raise SpecWorldError(f"links[{i}] confidence {conf} 超出 [0,1]")

    return data


# --------------------------------------------------------------------------- #
# normalized world model
# --------------------------------------------------------------------------- #
def _normalize(spec: dict[str, Any]) -> dict[str, Any]:
    """spec → 去重 / 編 id / 正規化 datetime 的內部 world 模型。"""
    notebooks: list[dict[str, Any]] = []
    for i, nb in enumerate(spec["notebooks"]):
        notebooks.append({
            "index": i,
            "remote_id": f"spec-nb-{i + 1}",
            "name": str(nb["name"]),
            "color": nb.get("color"),
            "cover_pattern": nb.get("cover_pattern"),
            "sort_order": int(nb.get("sort_order") or 0),
            "is_default": bool(nb.get("is_default")),
        })

    nb_by_name = {nb["name"]: nb for nb in notebooks}
    cards_by_nb: dict[str, list[dict[str, Any]]] = {nb["name"]: [] for nb in notebooks}
    seen: dict[str, set[str]] = {nb["name"]: set() for nb in notebooks}
    for card in spec["cards"]:
        nb_name = card["notebook"]
        content = str(card["content"]).strip()
        if content in seen[nb_name]:
            continue  # 同 notebook 同 content 去重（keep-first；fixture word 唯一）
        seen[nb_name].add(content)
        review = card.get("review") or {}
        owner = f"card {content!r}"
        feedback = review.get("last_review_feedback")
        cards_by_nb[nb_name].append({
            "word": content,
            "translation": str(card["meaning"]),
            "pos": card.get("pos"),
            "note": card.get("note"),
            "examples": _str_list(card.get("examples"), owner=f"{owner}.examples"),
            "collocations": _str_list(card.get("collocations"), owner=f"{owner}.collocations"),
            "root_form": card.get("root_form"),
            "inflections": _str_list(card.get("inflections"), owner=f"{owner}.inflections"),
            "mode": card.get("mode") or "recognition",
            "is_archived": bool(card.get("is_archived")),
            "difficulty_tier": _difficulty_tier(card.get("difficulty")),
            "kg_card_id": f"spec-nb{nb_by_name[nb_name]['index'] + 1}-card{len(cards_by_nb[nb_name]) + 1}",
            "review_count": int(review.get("review_count") or 0),
            "review_streak": int(review.get("review_streak") or 0),
            "lapse_count": int(review.get("lapse_count") or 0),
            "review_interval_hours": float(review.get("review_interval_hours") or 12.0),
            "next_review_at": _norm_ts(review.get("next_review_at"), owner=f"{owner}.next_review_at"),
            "last_reviewed_at": _norm_ts(review.get("last_reviewed_at"), owner=f"{owner}.last_reviewed_at"),
            "last_review_feedback": int(feedback) if feedback is not None else -1,
            "links": [],  # from-side links，下面回填
        })

    card_index: dict[tuple[str, str], dict[str, Any]] = {
        (nb_name, c["word"]): c
        for nb_name, cards in cards_by_nb.items()
        for c in cards
    }
    link_seq: dict[str, int] = {nb["name"]: 0 for nb in notebooks}
    for link in spec.get("links", []):
        nb_name = link["notebook"]
        source = card_index[(nb_name, link["from"])]
        target = card_index[(nb_name, link["to"])]
        link_seq[nb_name] += 1
        source["links"].append({
            "id": f"spec-link-nb{nb_by_name[nb_name]['index'] + 1}-{link_seq[nb_name]}",
            "cardId": target["kg_card_id"],
            "word": target["word"],
            "kind": link["kind"],
            "label": _LINK_LABELS[link["kind"]],
            "confidence": float(link["confidence"]),
            # export 面明確容許 reason=""（DB link 無 reason），但 todayReview link
            # validator 要求非空字串——確定式 fallback 到 kind label，避免合法 spec
            # 在「該卡剛好落在 session current/next」時才位置依賴地炸。
            "reason": str(link.get("reason") or "").strip() or _LINK_LABELS[link["kind"]],
            "hidden": False,
        })

    # primary = active 卡最多的 notebook（tie-break: is_default、再 spec 順序）。
    # 不能只看 is_default:真實帳號的預設單字本（user-create 建的「我的單字本」）
    # 常是空的，行銷資料住在另一本。
    def _active_count(nb: dict[str, Any]) -> int:
        return sum(1 for c in cards_by_nb[nb["name"]] if not c["is_archived"])

    primary = max(
        notebooks,
        key=lambda nb: (_active_count(nb), nb["is_default"], -nb["index"]),
    )
    for cards in cards_by_nb.values():
        for card in cards:
            card["date_added"] = _card_date_added(card)
    return {"notebooks": notebooks, "cards_by_nb": cards_by_nb, "primary": primary}


def _due_order(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """已排程者依 (next_review_at, word) 升冪在前，未排程者維持 spec 順序在後。"""
    scheduled = [c for c in cards if c["next_review_at"]]
    unscheduled = [c for c in cards if not c["next_review_at"]]
    scheduled.sort(key=lambda c: (c["next_review_at"], c["word"]))
    return scheduled + unscheduled


# --------------------------------------------------------------------------- #
# review history synthesis（對齊 backend demo_review_synth 語意的精簡版）
# --------------------------------------------------------------------------- #
def _even_positions(span: int, count: int) -> list[int]:
    if count <= 0 or span <= 0:
        return []
    count = min(count, span)
    return sorted({(2 * i + 1) * span // (2 * count) for i in range(count)})


def _feedback_sequence(n: int, lapses: int, streak: int, last_feedback: int) -> list[int]:
    """長度 n 的 0/1 序列（index 0 最舊）；語意同 demo_review_synth._feedback_sequence。"""
    streak = max(0, min(streak, n))
    pre_len = n - streak
    lapses = max(0, min(lapses, pre_len))
    fb = [1] * n
    if streak > 0:
        if lapses >= 1:
            breaker = pre_len - 1
            fb[breaker] = 0
            for pos in _even_positions(breaker, lapses - 1):
                fb[pos] = 0
        return fb
    positions = set(_even_positions(pre_len, lapses))
    last_idx = n - 1
    if last_feedback == 0 and last_idx not in positions:
        if positions:
            positions.discard(max(positions))
        positions.add(last_idx)
    elif last_feedback == 1 and last_idx in positions:
        positions.discard(last_idx)
        for pos in _even_positions(last_idx, 1):
            positions.add(pos)
    for pos in positions:
        fb[pos] = 0
    return fb


def _card_history(card: dict[str, Any]) -> list[dict[str, Any]]:
    """單卡聚合 → [{word, feedback, reviewedAt}]（最舊在前）。

    每卡最多 _HISTORY_PER_CARD_MAX 筆（取最近的）；往過去回推的單段間隔以
    _INTERVAL_GROWTH 成長並 clamp 在 _MAX_GAP_HOURS，避免大 review_count 指數溢位。
    """
    n = min(card["review_count"], _HISTORY_PER_CARD_MAX)
    anchor_raw = card["last_reviewed_at"]
    if n <= 0 or not anchor_raw:
        return []
    anchor = _parse_norm_ts(anchor_raw)
    fb = _feedback_sequence(
        n, card["lapse_count"], card["review_streak"], card["last_review_feedback"]
    )
    base_gap = max(card["review_interval_hours"] / _INTERVAL_GROWTH, _MIN_RECENT_GAP_HOURS)
    cum = [0.0]
    for k in range(1, n):
        gap = min(base_gap * (_INTERVAL_GROWTH ** (k - 1)), _MAX_GAP_HOURS)
        cum.append(cum[-1] + gap)
    # cum[k] = 從末筆往過去第 k 段的累積小時；index 0 最舊 -> offset cum[n-1-i]
    return [
        {
            "word": card["word"],
            "feedback": fb[i],
            "reviewedAt": _fmt_ts(anchor - timedelta(hours=cum[n - 1 - i])),
        }
        for i in range(n)
    ]


def _card_date_added(card: dict[str, Any]) -> str:
    """確定式導出非空 dateAdded（Swift TodayReviewCardSeed.dateAdded 非 optional）。

    規則（缺料逐級 fallback；全部是 spec 內容的純函式，零 wall-clock、零隨機）：
    1. 有合成 review 事件（review_count>0 且 last_reviewed_at 非空）→ 取最早
       合成事件再往前 _DATE_ADDED_LEAD_HOURS：卡必先加入才有首次 review。
    2. 否則有 last_reviewed_at 或 next_review_at → 該錨點往前
       _DATE_ADDED_LEAD_HOURS。
    3. 全無日期素材 → _DATE_ADDED_FALLBACK_ANCHOR 固定錨點。
    """
    history = _card_history(card)
    if history:
        anchor = _parse_norm_ts(history[0]["reviewedAt"])  # index 0 = 最舊事件
    else:
        raw = card["last_reviewed_at"] or card["next_review_at"]
        if not raw:
            return _DATE_ADDED_FALLBACK_ANCHOR
        anchor = _parse_norm_ts(raw)
    return _fmt_ts(anchor - timedelta(hours=_DATE_ADDED_LEAD_HOURS))


def _history_for(cards: list[dict[str, Any]], *, cap: int) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for card in cards:
        events.extend(_card_history(card))
    events.sort(key=lambda r: (r["reviewedAt"], r["word"]), reverse=True)
    return events[:cap]


# --------------------------------------------------------------------------- #
# entry / seed builders
# --------------------------------------------------------------------------- #
def _entry(card: dict[str, Any], *, nb_name: str, sync_status: int = 1,
           action_type: str = "add", reviewed_mode: str | None = None,
           allowed_words: set[str] | None = None) -> dict[str, Any]:
    """卡 → UI_WORLD_ENTRY_KEYS 全鍵明示的 vocabulary/reviewDeck entry。

    `allowed_words`：seed 子集的 word 集合。vocabulary/reviewDeck seed 是自足
    宇宙——graphLinksByKind 的 target 必須 resolve 到同 seed entries
    （KnowledgeGraphViewScenarios.swift:199 以 Set(entries.kgCardId) 驗證，
    dangling 即 preconditionFailure）→ 子集投影時把指向子集外的 link prune 掉。
    """
    return {
        "word": card["word"],
        "translation": card["translation"],
        "context": card["examples"][0] if card["examples"] else card["word"],
        "explanation": card["note"],
        "partOfSpeech": card["pos"],
        "bookTitle": nb_name,  # spec 無書籍來源欄位；validator 要求非空 → 用 notebook 名
        "chapterTitle": None,
        "kgCardId": card["kg_card_id"],
        "difficultyTier": card["difficulty_tier"],
        "reviewMode": reviewed_mode or card["mode"],
        "reviewExamples": card["examples"],
        "collocations": card["collocations"] or None,
        "rootForm": card["root_form"],
        "inflections": card["inflections"] or None,
        "syncStatus": sync_status,
        "actionType": action_type,
        "isArchived": card["is_archived"],
        "isExcludedFromReader": False,
        "reviewIntervalHours": card["review_interval_hours"],
        "nextReviewAt": card["next_review_at"],
        "lastReviewedAt": card["last_reviewed_at"],
        "reviewCount": card["review_count"],
        "reviewStreak": card["review_streak"],
        "lastReviewFeedbackRaw": card["last_review_feedback"],
        "graphLinksByKind": _links_by_kind(card, allowed_words=allowed_words),
    }


def _links_by_kind(
    card: dict[str, Any], *, allowed_words: set[str] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """card links → kind buckets。`allowed_words` 非 None 時只保留 target 在
    集合內的 link（seed 自足契約）；None = 不過濾（todayReview 卡對齊 baseline
    語意：links 是顯示 chips，容許指向 session 外的字）。"""
    buckets: dict[str, list[dict[str, Any]]] = {}
    for link in card["links"]:
        if allowed_words is not None and link["word"] not in allowed_words:
            continue
        buckets.setdefault(link["kind"], []).append(dict(link))
    return {kind: buckets[kind] for kind in sorted(buckets)}


def _vocab_seed(primary: dict[str, Any], entries: list[dict[str, Any]],
                history: list[dict[str, Any]] | None = None,
                *, notebook_sync: int = 1) -> dict[str, Any]:
    return {
        "notebookRemoteId": primary["remote_id"],
        "notebookName": primary["name"],
        "notebookSyncStatus": notebook_sync,
        "bookTitle": primary["name"],  # spec 無書籍來源；validator 要求非空 → 用 notebook 名
        "entries": entries,
        "reviewHistory": history or [],
    }


def _deck_seed(primary: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "notebookRemoteId": primary["remote_id"],
        "notebookName": primary["name"],
        "notebookSyncStatus": 1,
        "entries": entries,
    }


def _notebook_entry(card: dict[str, Any], *, nb_name: str) -> dict[str, Any]:
    return {
        "word": card["word"],
        "translation": card["translation"],
        "context": card["examples"][0] if card["examples"] else card["word"],
        "explanation": card["note"],
        "partOfSpeech": card["pos"],
        "bookTitle": nb_name,
        "chapterTitle": None,
        "syncStatus": 1,
        "actionType": "add",
        "isArchived": card["is_archived"],
        "isExcludedFromReader": False,
        # review scheduling：NotebookStatsCalculator 的 due/unlearned/reviewed
        # 徽章與進度條靠這四欄；缺了列表徽章=總卡數、進度條全空。
        "reviewIntervalHours": card["review_interval_hours"],
        "nextReviewAt": card["next_review_at"],
        "lastReviewedAt": card["last_reviewed_at"],
        "reviewCount": card["review_count"],
    }


def _notebook_row(nb: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, Any]:
    active = [c for c in cards if not c["is_archived"]]
    return {
        "remoteId": nb["remote_id"],
        "name": nb["name"],
        "color": nb["color"],
        "coverPattern": nb["cover_pattern"],
        "coverImageAssetRef": None,
        "cardState": None,
        "syncStatus": 1,
        "isDefault": nb["is_default"],
        "sortOrder": nb["sort_order"],
        "entries": [_notebook_entry(c, nb_name=nb["name"]) for c in active],
    }


def _today_card(card: dict[str, Any], *, nb_name: str,
                reviewed_mode: str | None = None) -> dict[str, Any]:
    return {
        "word": card["word"],
        "translation": card["translation"],
        "context": card["examples"][0] if card["examples"] else card["word"],
        "explanation": card["note"],
        "partOfSpeech": card["pos"],
        "bookTitle": nb_name,
        "chapterTitle": None,
        "dateAdded": card["date_added"],  # 非空確定式導出（_card_date_added）
        "difficultyTier": card["difficulty_tier"],
        "reviewMode": reviewed_mode or card["mode"],
        "reviewExamples": card["examples"],
        "rootForm": card["root_form"],
        "inflections": card["inflections"],
        "graphLinksByKind": _links_by_kind(card),
    }


def _today_session(queue: list[dict[str, Any]], *, nb_name: str, stage: str,
                   completed: bool = False, autoplaying: bool = False,
                   paused: bool = False, force_mode: str | None = None) -> dict[str, Any]:
    total = len(queue)
    if completed:
        done, current, nxt = total, None, None
    else:
        done = total // 4
        current = _today_card(queue[done], nb_name=nb_name, reviewed_mode=force_mode)
        nxt = (
            _today_card(queue[done + 1], nb_name=nb_name, reviewed_mode=force_mode)
            if done + 1 < total else None
        )
    forgot = done // 3
    return {
        "progressText": f"{done} / {total}",
        "currentCard": current,
        "nextCard": nxt,
        "revealStage": stage,
        "canShuffle": total > 1 and not completed,
        "canGoPrevious": done > 0 and not completed,
        "canGoNext": (done + 1 < total) and not completed,
        "remainingCount": total - done,
        "forgotCount": forgot,
        "rememberedCount": done - forgot,
        "rememberedFeedbackTrigger": 0,
        "forgotFeedbackTrigger": 0,
        "isAutoPlaying": autoplaying,
        "isAutoPlayPaused": paused,
        "autoplayProgress": 1.0 if completed else (0.5 if autoplaying else 0.0),
        "autoplaySpeed": "normal",
        "autoplaySoundEnabled": True,
        "showFirstRunHint": False,
    }


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def derive_domains(spec: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """seed spec → (四 domain 的 spec-derived fixture seeds, 統計)。

    回傳的 domain dict 只含 spec-derived fixture id；emit_ios 以
    baseline domain 為底 merge（未覆蓋的 UI-chrome fixture id 沿用 baseline）。
    """
    world = _normalize(spec)
    notebooks = world["notebooks"]
    cards_by_nb = world["cards_by_nb"]
    primary = world["primary"]

    p_cards = cards_by_nb[primary["name"]]
    active = [c for c in p_cards if not c["is_archived"]]
    archived = [c for c in p_cards if c["is_archived"]]
    if not active:
        raise SpecWorldError(
            f"primary notebook {primary['name']!r} 沒有 active 卡，無法投影 review/session fixtures"
        )
    due = _due_order(active)
    linked = [c for c in active if c["links"] or any(
        lk["word"] == c["word"] for other in active for lk in other["links"])]
    if not linked:
        linked = active[:4]

    production_due = [c for c in due if c["mode"] == "production"]
    session = due[:_TODAY_SESSION_MAX]
    if production_due:
        production_session = production_due[:_TODAY_SESSION_MAX]
        force_mode = None
    else:
        # spec 無 production 卡：production fixture 的語意（展示 production 介面）
        # 優先，卡片 reviewMode 確定式覆寫為 production。
        production_session = session
        force_mode = "production"

    def entries(cards: list[dict[str, Any]], **kw: Any) -> list[dict[str, Any]]:
        allowed = {c["word"] for c in cards}
        return [_entry(c, nb_name=primary["name"], allowed_words=allowed, **kw)
                for c in cards]

    syncing = active[:_SYNCING_MAX]
    syncing_split = (len(syncing) * 3) // 5
    syncing_words = {c["word"] for c in syncing}
    syncing_entries = [
        _entry(c, nb_name=primary["name"], sync_status=1 if i < syncing_split else 0,
               allowed_words=syncing_words)
        for i, c in enumerate(syncing)
    ]
    # SyncViewScenarios mixed 釘「pending>1 且同時含 add+delete」→ delete 排第二，
    # 讓 ≥2 張 active 卡的 spec 就能滿足，不依賴恰有 4 張。
    mixed_actions = ("add", "delete", "add", "edit")
    mixed_cards = active[:_PENDING_MIXED_MAX]
    mixed_words = {c["word"] for c in mixed_cards}
    mixed_entries = [
        _entry(c, nb_name=primary["name"], sync_status=0,
               action_type=mixed_actions[i % len(mixed_actions)],
               allowed_words=mixed_words)
        for i, c in enumerate(mixed_cards)
    ]

    dense_history = _history_for(active, cap=_HISTORY_DENSE_MAX)
    # statsPopulated 承載 streak / heatmap 敘事 → 必須全 active 卡 + 全量事件
    # （只取前 8 張時，8 條幾何回推序列的聯集永遠湊不出連續日 streak）。
    # shellNavigation 是 chrome smoke，維持 8 卡小樣本。
    stats_cards = active[:_STATS_ENTRIES_MAX]
    stats_history = _history_for(active, cap=_HISTORY_STATS_MAX)
    shell_history = _history_for(stats_cards, cap=_HISTORY_SHELL_MAX)

    # content-pinned fixtures（wordDetail / wordEdit / searchVocabNotebook /
    # kgVocabRow / vocabLinkedCards / archivedPopulated / archivedSingle /
    # archivedLong）刻意不投影：catalog scenario 釘死特定內容/形狀，由 emit_ios
    # 保留 baseline（SoT 註解見 emit_ios.SPEC_BASELINE_KEPT_FIXTURES）。
    vocabulary = {
        "vocabListPopulated": _vocab_seed(primary, entries(active)),
        "vocabListSingle": _vocab_seed(primary, entries(active[:1])),
        "vocabListLong": _vocab_seed(primary, entries(active[:_LIST_LONG_MAX])),
        "vocabListEmpty": _vocab_seed(primary, []),
        "vocabListSyncing": _vocab_seed(primary, syncing_entries),
        "syncPendingSingle": _vocab_seed(
            primary, entries(active[:1], sync_status=0), notebook_sync=0),
        "syncPendingMixed": _vocab_seed(primary, mixed_entries, notebook_sync=0),
        "syncEmpty": _vocab_seed(primary, []),
        "archivedEmpty": _vocab_seed(primary, []),
        "knowledgeGraphPopulated": _vocab_seed(primary, entries(linked[:_KG_GRAPH_MAX])),
        "knowledgeGraphEmpty": _vocab_seed(primary, []),
        "shellNavigation": _vocab_seed(primary, entries(stats_cards), shell_history),
        "statsPopulated": _vocab_seed(primary, entries(active), stats_history),
        "reviewCalendarDense": _vocab_seed(primary, entries(active), dense_history),
        "statsEmpty": _vocab_seed(primary, []),
    }

    notebook = {
        "empty": {"notebooks": [], "editStates": []},
        "single": {
            "notebooks": [_notebook_row(primary, p_cards)],
            "editStates": [],
        },
        "populated": {
            "notebooks": [_notebook_row(nb, cards_by_nb[nb["name"]]) for nb in notebooks],
            "editStates": [],
        },
    }

    # probe / notebookReviewDeck 刻意不投影：UITest 量測 deck
    # （NotebookReviewFlowUITests 釘 probeword 前綴 + 譯文配對），由 emit_ios
    # 保留 baseline（SoT 註解見 emit_ios.SPEC_BASELINE_KEPT_FIXTURES）。
    review_deck = {
        "phaseSingle": _deck_seed(primary, entries(due[:1])),
        "phaseMulti": _deck_seed(primary, entries(due[:_DECK_MULTI_MAX])),
        "phaseLongContent": _deck_seed(
            primary,
            entries([max(active, key=lambda c: (len(c["translation"]) + len(
                c["examples"][0] if c["examples"] else ""), c["word"]))]),
        ),
    }

    nb_name = primary["name"]
    today_review = {
        "front": _today_session(session, nb_name=nb_name, stage="front"),
        "back": _today_session(session, nb_name=nb_name, stage="back"),
        "completed": _today_session(session, nb_name=nb_name, stage="front", completed=True),
        "autoplay": _today_session(session, nb_name=nb_name, stage="back", autoplaying=True),
        "autoplayPaused": _today_session(
            session, nb_name=nb_name, stage="back", autoplaying=True, paused=True),
        "productionFront": _today_session(
            production_session, nb_name=nb_name, stage="front", force_mode=force_mode),
        "productionBack": _today_session(
            production_session, nb_name=nb_name, stage="back", force_mode=force_mode),
    }

    stats = {
        "notebooks": len(notebooks),
        "cards": sum(len(v) for v in cards_by_nb.values()),
        "primaryNotebook": primary["name"],
        "primaryActiveCards": len(active),
        "primaryArchivedCards": len(archived),
        "links": sum(len(c["links"]) for v in cards_by_nb.values() for c in v),
        "reviewHistoryEvents": len(dense_history),
        "todaySessionCards": len(session),
    }
    domains = {
        "vocabulary": vocabulary,
        "notebook": notebook,
        "reviewDeck": review_deck,
        "todayReview": today_review,
    }
    return domains, stats
