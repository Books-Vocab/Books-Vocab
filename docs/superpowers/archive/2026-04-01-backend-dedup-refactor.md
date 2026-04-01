# Backend Architecture Refactor: graph.py dedup + vocab_service.py 拆分

> **執行方式:** 使用 execute skill，所有 agent 皆 opus。

**Goal:** 消除 graph.py 三套複製貼上，拆分 vocab_service.py 680 行 god file 為 5 個職責單一模組。
**Architecture:** 純重構 — 零業務邏輯變更。graph.py 抽共用 atomic write。vocab_service.py 拆為 vocab_shared/crud/review/graph_ops/intake，刪除原檔，更新所有 caller import。
**Tech Stack:** Python, FastAPI, pytest

---

## Task 1: graph.py — 抽出 `_atomic_json_write`

**Files:**
- Modify: `backend/src/kg/graph.py:116-146`
- Test: `backend/tests/test_graph_index.py` (existing, validates save/reload round-trip)

- [ ] **Step 1: 寫 failing test**
```python
# backend/tests/test_graph_atomic_write.py
import json
from pathlib import Path
from kg.graph import GraphStore

def test_atomic_json_write_creates_backup(tmp_path):
    """Verify _atomic_json_write creates .bak file on overwrite."""
    path = tmp_path / "test.json"
    GraphStore._atomic_json_write(path, [{"a": 1}])
    assert json.loads(path.read_text()) == [{"a": 1}]
    # Second write should create .bak
    GraphStore._atomic_json_write(path, [{"a": 2}])
    assert json.loads(path.read_text()) == [{"a": 2}]
    bak = path.with_suffix(".json.bak")
    assert bak.exists()
    assert json.loads(bak.read_text()) == [{"a": 1}]

def test_atomic_json_write_no_indent(tmp_path):
    """Verify indent=None produces compact JSON."""
    path = tmp_path / "compact.json"
    GraphStore._atomic_json_write(path, [[1, 2]], indent=None)
    raw = path.read_text()
    assert "\n" not in raw
```

- [ ] **Step 2: 跑 test 確認失敗**
Run: `pytest backend/tests/test_graph_atomic_write.py -v`
Expected: FAIL (AttributeError: type object 'GraphStore' has no attribute '_atomic_json_write')

- [ ] **Step 3: 實作 `_atomic_json_write` 並重構三個 save 方法**

Replace `graph.py:116-146` with:

```python
@staticmethod
def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
    """Atomic JSON write: tmp → bak → replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False))
    if path.exists():
        path.replace(path.with_suffix(".json.bak"))
    tmp.replace(path)

def _save_links(self) -> None:
    data = [lk.model_dump(mode="json") for lk in self._links.values()]
    self._atomic_json_write(self.links_path, data)

def _save_candidates(self) -> None:
    data = [c.model_dump(mode="json") for c in self._candidates]
    self._atomic_json_write(self.candidates_path, data)

def _save_blocked(self) -> None:
    if self.blocked_path is None:
        return
    data = [list(pair) for pair in self._blocked_pairs]
    self._atomic_json_write(self.blocked_path, data, indent=None)
```

- [ ] **Step 4: 跑全部 graph 相關 test 確認通過**
Run: `pytest backend/tests/test_graph_atomic_write.py backend/tests/test_graph_index.py backend/tests/test_graph_concurrency.py backend/tests/test_graph_orphan.py backend/tests/test_hide_link.py backend/tests/test_notebook_delete_cleanup.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**
`api: refactor graph.py — extract _atomic_json_write, eliminate 3x save duplication`

---

## Task 2: 建立 `vocab_shared.py`

**Files:**
- Create: `backend/src/kg/vocab_shared.py`
- Test: existing tests (no new test needed — pure extraction)

- [ ] **Step 1: 建立 `vocab_shared.py`**

從 `vocab_service.py` 搬出以下內容：

```python
# backend/src/kg/vocab_shared.py
"""Shared helpers and response builders for vocabulary modules."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from .api_models import (
    CardLinkSummaryResponse,
    CardResponse,
    VocabSource,
)
from .exceptions import BadRequestError
from .text_utils import normalize_nfc_lower
from .user_store import parse_datetime

logger = logging.getLogger(__name__)

MAX_BATCH_SIZE = 500
MAX_WORD_LENGTH = 200


def _normalize_word(word: str) -> str:
    return normalize_nfc_lower(word)


def _clean_content(word: str) -> str:
    """Clean up word content for storage: strip trailing punctuation, lowercase first char."""
    word = word.strip().rstrip(".,;:!?")
    if word and word[0].isupper() and not word.isupper() and " " not in word:
        word = word[0].lower() + word[1:]
    return word


_POS_CANONICAL = {"n": "n.", "v": "v.", "adj": "adj.", "adv": "adv.", "phr": "phr.", "conj": "conj.", "prep": "prep."}


def _normalize_pos(pos: str | None) -> str | None:
    if not pos:
        return pos
    p = pos.strip()
    return _POS_CANONICAL.get(p, p)


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    s = dt.isoformat()
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    return s


def _build_content_lookup(cards_store: Any, notebook_id: str | None = None) -> dict[str, Any]:
    """Build a normalized-content → card dict from all active cards."""
    lookup: dict[str, Any] = {}
    for card in cards_store.all(include_deleted=False, notebook_id=notebook_id):
        key = _normalize_word(card.content)
        if key not in lookup:
            lookup[key] = card
    return lookup


def build_links_by_kind(card_id: str, *, graph: Any, cards_by_id: dict[str, Any], link_kinds: list[Any], link_labels: dict[Any, str]) -> dict[str, list[CardLinkSummaryResponse]]:
    grouped: dict[str, list[CardLinkSummaryResponse]] = {}

    for link in graph.get_links_for(card_id):
        other_id = link.to_id if link.from_id == card_id else link.from_id
        other_card = cards_by_id.get(other_id)
        if not other_card or other_card.is_deleted or other_card.is_archived:
            continue

        kind_key = link.kind.value
        grouped.setdefault(kind_key, []).append(
            CardLinkSummaryResponse(
                id=link.id,
                cardId=other_card.id,
                word=other_card.content,
                kind=kind_key,
                label=link_labels.get(link.kind, link.kind.value),
                confidence=link.confidence,
                reason=link.reason,
                hidden=(link.status == "hidden"),
            )
        )

    ordered: dict[str, list[CardLinkSummaryResponse]] = {}
    for kind in link_kinds:
        items = grouped.get(kind.value)
        if items:
            ordered[kind.value] = sorted(items, key=lambda item: _normalize_word(item.word))

    return ordered


def card_response(card: Any, *, graph: Any, cards_by_id: dict[str, Any], tier_getter: Callable[[str], Any], link_kinds: list[Any], link_labels: dict[Any, str]) -> CardResponse:
    tier = tier_getter(card.content)
    links_by_kind = {}
    if not card.is_deleted:
        links_by_kind = build_links_by_kind(
            card.id,
            graph=graph,
            cards_by_id=cards_by_id,
            link_kinds=link_kinds,
            link_labels=link_labels,
        )

    return CardResponse(
        id=card.id,
        content=card.content,
        meaning=card.meaning,
        pos=card.pos,
        difficulty=card.difficulty,
        difficultyTier=tier.tag,
        note=card.note,
        collocations=card.collocations or [],
        examples=card.examples,
        mode=card.mode,
        isDeleted=card.is_deleted,
        isArchived=card.is_archived,
        inflections=card.inflections or [],
        linksByKind=links_by_kind,
        notebookId=getattr(card, "notebook_id", "default"),
        source=VocabSource(**json.loads(card.source)) if getattr(card, "source", None) else None,
        updatedAt=_dt_to_iso(card.updated_at),
        reviewIntervalHours=card.review_interval_hours,
        nextReviewAt=_dt_to_iso(card.next_review_at),
        lastReviewedAt=_dt_to_iso(card.last_reviewed_at),
        reviewCount=card.review_count,
        lapseCount=card.lapse_count,
        reviewStreak=card.review_streak,
        lastReviewFeedback=card.last_review_feedback,
    )
```

- [ ] **Step 2: 驗證 import 正確**
Run: `python -c "from kg.vocab_shared import card_response, build_links_by_kind, _normalize_word, _normalize_pos, _dt_to_iso, MAX_BATCH_SIZE"`
Expected: no error

- [ ] **Step 3: Commit**
`api: extract vocab_shared.py — shared helpers and response builders`

---

## Task 3: 建立 `vocab_crud.py`

**Files:**
- Create: `backend/src/kg/vocab_crud.py`

- [ ] **Step 1: 建立 `vocab_crud.py`**

搬出 `list_vocab_cards`, `lookup_vocab_word`, `archive_vocab_word`, `delete_vocab_word`, `batch_delete_vocab_words`, `batch_archive_vocab_words`, `move_vocab_words`。

Import from `vocab_shared`: `_normalize_word`, `_build_content_lookup`, `MAX_BATCH_SIZE`, `MAX_WORD_LENGTH`。
Import from `exceptions`: `BadRequestError`, `NotFoundError`, `ValidationError`。

- [ ] **Step 2: 驗證 import 正確**
Run: `python -c "from kg.vocab_crud import list_vocab_cards, lookup_vocab_word, delete_vocab_word"`
Expected: no error

- [ ] **Step 3: Commit**
`api: extract vocab_crud.py — vocabulary CRUD operations`

---

## Task 4: 建立 `vocab_review.py`

**Files:**
- Create: `backend/src/kg/vocab_review.py`

- [ ] **Step 1: 建立 `vocab_review.py`**

搬出 `push_review_states`, `push_daily_review_stats`, `pull_daily_review_stats`。

Import from `vocab_shared`: `_normalize_word`。
Import from `api_models`: `DailyReviewStatEntry`, `ReviewStateEntry`。
Import from `user_store`: `parse_datetime`。

- [ ] **Step 2: 驗證 import 正確**
Run: `python -c "from kg.vocab_review import push_review_states, push_daily_review_stats, pull_daily_review_stats"`
Expected: no error

- [ ] **Step 3: Commit**
`api: extract vocab_review.py — review state sync operations`

---

## Task 5: 建立 `vocab_graph_ops.py`

**Files:**
- Create: `backend/src/kg/vocab_graph_ops.py`

- [ ] **Step 1: 建立 `vocab_graph_ops.py`**

搬出 `create_manual_link`, `hide_graph_link`, `unhide_graph_link`, `delete_graph_link`。

Import from `exceptions`: `NotFoundError`, `ConflictError`。
Import from `graph`: `LinkKind`（在 `create_manual_link` 內）。

- [ ] **Step 2: 驗證 import 正確**
Run: `python -c "from kg.vocab_graph_ops import create_manual_link, hide_graph_link"`
Expected: no error

- [ ] **Step 3: Commit**
`api: extract vocab_graph_ops.py — graph link operations`

---

## Task 6: 建立 `vocab_intake.py`

**Files:**
- Create: `backend/src/kg/vocab_intake.py`

- [ ] **Step 1: 建立 `vocab_intake.py`**

搬出 `add_vocab_entries`, `_derive_inflections`, `_build_example`。

Import: `import json`, `import logging`, `import re`。
Import from `vocab_shared`: `_normalize_word`, `_clean_content`, `MAX_BATCH_SIZE`。
Import from `api_models`: `VocabAddResponse`, `VocabEntry`, `VocabSource`。
Import from `vocab_graph`: `embed_and_link_new_cards`。
Import from `exceptions`: `ValidationError`。

- [ ] **Step 2: 驗證 import 正確**
Run: `python -c "from kg.vocab_intake import add_vocab_entries"`
Expected: no error

- [ ] **Step 3: Commit**
`api: extract vocab_intake.py — vocabulary intake and inflection derivation`

---

## Task 7: 刪除 `vocab_service.py`，更新所有 src + test import（原子操作）

**Files:**
- Delete: `backend/src/kg/vocab_service.py`
- Modify: `backend/src/kg/vocab_handlers.py:25-42`
- Modify: `backend/src/kg/deps.py:44`
- Modify: `backend/src/kg/translate_service.py:12`
- Modify: `backend/src/kg/pipeline_service.py:67`
- Modify: `backend/src/kg/routers/notebook.py:10`
- Modify: all test files (see below)

- [ ] **Step 1: 更新 `vocab_handlers.py` imports**
```python
from .vocab_crud import (
    archive_vocab_word,
    batch_archive_vocab_words,
    batch_delete_vocab_words,
    delete_vocab_word,
    list_vocab_cards,
    lookup_vocab_word,
    move_vocab_words,
)
from .vocab_graph_ops import (
    create_manual_link,
    delete_graph_link,
    hide_graph_link,
    unhide_graph_link,
)
from .vocab_intake import add_vocab_entries
from .vocab_review import (
    pull_daily_review_stats,
    push_daily_review_stats,
    push_review_states,
)
from .vocab_graph import graph_links_payload
```

- [ ] **Step 2: 更新 `deps.py:44`**
```python
from .vocab_shared import build_links_by_kind, card_response
```

- [ ] **Step 3: 更新 `translate_service.py:12`**
```python
from .vocab_shared import _normalize_pos
```

- [ ] **Step 4: 更新 `pipeline_service.py:67`**
```python
from .vocab_shared import _normalize_pos
```

- [ ] **Step 5: 更新 `routers/notebook.py:10`**
```python
from ..vocab_shared import _dt_to_iso
```

- [ ] **Step 6: 更新所有 test 的 import**

按 spec 中的 test import 映射表逐一更新。注意 inline imports：
- `test_vocab_service.py:322` → `from kg.vocab_crud import delete_vocab_word`
- `test_vocab_service.py:511` → `from kg.vocab_crud import list_vocab_cards`
- `test_sync_merge.py:318` → `from kg.api_models import CardResponse`

- [ ] **Step 7: 刪除 `vocab_service.py`**

- [ ] **Step 8: 全量跑 test**
Run: `pytest backend/tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 9: 驗證無殘留 import**
Run: `rg "from.*vocab_service" backend/`
Expected: zero results

- [ ] **Step 10: Commit**
`api: delete vocab_service.py, rewire all imports to new modules`
