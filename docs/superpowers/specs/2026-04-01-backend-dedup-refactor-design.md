# Backend Architecture Refactor: graph.py dedup + vocab_service.py 拆分

## 問題

1. **graph.py 三套複製貼上** — `_save_links`、`_save_candidates`、`_save_blocked` 邏輯完全相同（mkdir → dump → write tmp → rename bak → rename），僅資料來源和路徑不同
2. **vocab_service.py 680 行 god file** — 4 個 bounded context 混合：CRUD、review sync、graph link ops、intake + inflection

## 設計

### Part 1: graph.py — 抽出 `_atomic_json_write`

**Before:**
```python
def _save_links(self):
    self.links_path.parent.mkdir(parents=True, exist_ok=True)
    data = [lk.model_dump(mode="json") for lk in self._links.values()]
    tmp_path = self.links_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    if self.links_path.exists():
        bak_path = self.links_path.with_suffix(".json.bak")
        self.links_path.replace(bak_path)
    tmp_path.replace(self.links_path)

# _save_candidates — 同上邏輯
# _save_blocked — 同上邏輯
```

**After:**
```python
@staticmethod
def _atomic_json_write(path: Path, data: Any, *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=indent, ensure_ascii=False))
    if path.exists():
        path.replace(path.with_suffix(".json.bak"))
    tmp.replace(path)

def _save_links(self):
    data = [lk.model_dump(mode="json") for lk in self._links.values()]
    self._atomic_json_write(self.links_path, data)

def _save_candidates(self):
    data = [c.model_dump(mode="json") for c in self._candidates]
    self._atomic_json_write(self.candidates_path, data)

def _save_blocked(self):
    if self.blocked_path is None:
        return
    data = [list(pair) for pair in self._blocked_pairs]
    self._atomic_json_write(self.blocked_path, data, indent=None)
```

**行為變更：零。** 純重構，所有 caller 不受影響。

### Part 2: vocab_service.py 拆分

刪除 `vocab_service.py`，拆成 5 個模組，更新所有 caller 的 import。

#### 新模組結構

| 模組 | 職責 | 包含函式 |
|------|------|---------|
| `vocab_shared.py` | 共用 helper + response builder | `_normalize_word`, `_clean_content`, `_normalize_pos`, `_dt_to_iso`, `_build_content_lookup`, `card_response`, `build_links_by_kind`, `MAX_BATCH_SIZE`, `MAX_WORD_LENGTH` |
| `vocab_crud.py` | 卡片 CRUD | `list_vocab_cards`, `lookup_vocab_word`, `archive_vocab_word`, `delete_vocab_word`, `batch_delete_vocab_words`, `batch_archive_vocab_words`, `move_vocab_words` |
| `vocab_review.py` | 複習狀態同步 | `push_review_states`, `push_daily_review_stats`, `pull_daily_review_stats` |
| `vocab_graph_ops.py` | 圖譜 link 操作 | `create_manual_link`, `hide_graph_link`, `unhide_graph_link`, `delete_graph_link` |
| `vocab_intake.py` | 新增詞彙 + 形態衍生 | `add_vocab_entries`, `_derive_inflections`, `_build_example` |

#### 內部依賴圖

```
vocab_shared  ← vocab_crud, vocab_review, vocab_intake, vocab_graph_ops
vocab_graph (existing) ← vocab_graph_ops, vocab_intake (via vocab_graph.embed_and_link_new_cards)
```

無循環依賴。

#### Caller import 變更

| Caller | 舊 import | 新 import |
|--------|-----------|-----------|
| `vocab_handlers.py` | `from .vocab_service import (17 symbols)` | `from .vocab_crud import ...` + `from .vocab_review import ...` + `from .vocab_graph_ops import ...` + `from .vocab_intake import ...` + `from .vocab_graph import graph_links_payload` |
| `deps.py:44` | `from .vocab_service import build_links_by_kind, card_response` | `from .vocab_shared import build_links_by_kind, card_response` |
| `translate_service.py:12` | `from .vocab_service import _normalize_pos` | `from .vocab_shared import _normalize_pos` |
| `pipeline_service.py:67` | `from .vocab_service import _normalize_pos` | `from .vocab_shared import _normalize_pos` |
| `routers/notebook.py:10` | `from ..vocab_service import _dt_to_iso` | `from ..vocab_shared import _dt_to_iso` |

#### Test import 變更

| Test file | 舊 import | 新 import |
|-----------|-----------|-----------|
| `test_vocab_service.py` | `from kg.vocab_service import MAX_BATCH_SIZE, MAX_WORD_LENGTH, _normalize_word, add_vocab_entries, archive_vocab_word, batch_archive_vocab_words, batch_delete_vocab_words, delete_vocab_word, graph_links_payload, list_vocab_cards, lookup_vocab_word, move_vocab_words` | `from kg.vocab_shared import MAX_BATCH_SIZE, MAX_WORD_LENGTH, _normalize_word` + `from kg.vocab_crud import list_vocab_cards, lookup_vocab_word, archive_vocab_word, delete_vocab_word, batch_delete_vocab_words, batch_archive_vocab_words, move_vocab_words` + `from kg.vocab_intake import add_vocab_entries` + `from kg.vocab_graph import graph_links_payload` |
| `test_vocab_service.py:541` | `from kg.vocab_service import list_vocab_cards, card_response` | `from kg.vocab_crud import list_vocab_cards` + `from kg.vocab_shared import card_response` |
| `test_graph_orphan.py` | `from kg.vocab_service import delete_vocab_word` | `from kg.vocab_crud import delete_vocab_word` |
| `test_vocab_limit.py` | `from kg.vocab_service import list_vocab_cards` | `from kg.vocab_crud import list_vocab_cards` |
| `test_manual_link.py` | `from kg.vocab_service import create_manual_link` | `from kg.vocab_graph_ops import create_manual_link` |
| `test_daily_stats.py` | `from kg.vocab_service import pull/push_daily_review_stats` | `from kg.vocab_review import pull_daily_review_stats, push_daily_review_stats` |
| `test_sync_merge.py:18` | `from kg.vocab_service import list_vocab_cards, push_review_states` | `from kg.vocab_crud import list_vocab_cards` + `from kg.vocab_review import push_review_states` |
| `test_sync_merge.py:318` | `from kg.vocab_service import CardResponse` | `from kg.api_models import CardResponse` |
| `test_move_cards.py` | `from kg.vocab_service import move_vocab_words` | `from kg.vocab_crud import move_vocab_words` |
| `test_hide_link.py` | `from kg.vocab_service import hide_graph_link, unhide_graph_link, delete_graph_link, create_manual_link, build_links_by_kind` | `from kg.vocab_graph_ops import hide_graph_link, unhide_graph_link, delete_graph_link, create_manual_link` + `from kg.vocab_shared import build_links_by_kind` |

#### 隨 `_normalize_pos` 一起搬移的私有常數

`_POS_CANONICAL` dict → `vocab_shared.py`（被 `_normalize_pos` 使用）

## 不做的事

- **不做 dirty flag / coalesced flush** — 資料量小、immediate write 更安全
- **不保留 facade re-export** — 內部 codebase，直接改 import 更清晰
- **不改任何業務邏輯** — 純檔案搬移 + import 重寫

## 驗證方式

- `pytest backend/tests/ -x` 全部通過
- `rg "from.*vocab_service" backend/` 回傳零結果
