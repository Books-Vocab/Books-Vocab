# Manual Graph Links Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to manually create and delete graph links between vocabulary cards.

**Architecture:** Backend adds `rejected` status to GraphLink, a `find_link_between()` method, a dedicated manual-link Judge prompt, and two new API endpoints (POST/DELETE). iOS adds a search-based AddLinkSheet triggered from WordDetailPresenter, and swipe-to-delete on existing link rows.

**Tech Stack:** Python/FastAPI, Pydantic, Gemini LLM (via OpenAI client), SwiftUI, SwiftData

---

## File Map

### Backend — New
| File | Responsibility |
|------|---------------|
| `backend/tests/test_manual_link.py` | Tests for manual link creation/deletion |

### Backend — Modify
| File | Changes |
|------|---------|
| `backend/src/kg/graph.py:29-39` | Add `rejected` to `GraphLink.status` Literal |
| `backend/src/kg/graph.py:145-156` | `has_link()` — treat `rejected` as existing |
| `backend/src/kg/graph.py` (new method) | Add `find_link_between(id_a, id_b)` → `GraphLink \| None` |
| `backend/src/kg/graph.py` (new method) | Add `reject_link(link_id)` |
| `backend/src/kg/judge.py` | Add `ManualLinkJudge` class with dedicated prompt |
| `backend/src/kg/api_models.py` | Add `ManualLinkRequest` model |
| `backend/src/kg/vocab_service.py` | Add `create_manual_link()` and `reject_link()` functions |
| `backend/src/kg/vocab_handlers.py` | Add handler functions for new endpoints |
| `backend/src/kg/routers/vocab.py` | Add `POST /api/graph/links` and `DELETE /api/graph/links/{link_id}` routes |
| `backend/src/kg/deps.py` | Add `_gemini_client` import for manual link judge |

### iOS — New
| File | Responsibility |
|------|---------------|
| `ios/BooksBrowser/Views/Vocabulary/Scenes/AddLinkSheet.swift` | Search + select target word sheet |

### iOS — Modify
| File | Changes |
|------|---------|
| `ios/BooksBrowser/Services/KGService+Graph.swift` | Add `createManualLink()` and `deleteLink()` methods |
| `ios/BooksBrowser/Services/KGServing.swift` | Add protocol methods |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift:105-126` | Add "+" button in linksSection header, add swipe-to-delete on link rows |
| `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift` | Add state for AddLinkSheet, pass callbacks |

---

## Task 1: `rejected` status + `find_link_between` + `reject_link` in GraphStore

**Files:**
- Modify: `backend/src/kg/graph.py:39` (status Literal)
- Modify: `backend/src/kg/graph.py:145-156` (has_link)
- Add methods: `find_link_between`, `reject_link`
- Test: `backend/tests/test_manual_link.py`

- [ ] **Step 1: Write failing tests for `rejected` status behavior**

```python
# backend/tests/test_manual_link.py
from __future__ import annotations

import pytest

from kg.graph import GraphStore, LinkKind


@pytest.fixture()
def store(tmp_path):
    return GraphStore(
        links_path=tmp_path / "links.json",
        candidates_path=tmp_path / "candidates.json",
    )


class TestRejectedStatus:
    def test_has_link_returns_true_for_rejected(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        assert store.has_link("a", "b") is True

    def test_get_links_for_excludes_rejected(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        assert store.get_links_for("a") == []

    def test_add_candidate_skips_rejected_pair(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        store.add_candidate("a", "b", 0.85)
        assert store.candidate_count() == 0

    def test_reject_nonexistent_link_raises(self, store):
        with pytest.raises(KeyError):
            store.reject_link("nonexistent")


class TestFindLinkBetween:
    def test_finds_active_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.id == lk.id

    def test_finds_link_reverse_direction(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        found = store.find_link_between("b", "a")
        assert found is not None
        assert found.id == lk.id

    def test_finds_rejected_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.reject_link(lk.id)
        found = store.find_link_between("a", "b")
        assert found is not None
        assert found.status == "rejected"

    def test_returns_none_when_no_link(self, store):
        assert store.find_link_between("a", "b") is None

    def test_skips_deprecated_link(self, store):
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        store.deprecate_links_for("a")
        found = store.find_link_between("a", "b")
        assert found is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_manual_link.py -v`
Expected: FAIL — `reject_link` and `find_link_between` not defined

- [ ] **Step 3: Implement changes in graph.py**

Modify `backend/src/kg/graph.py`:

1. Line 39 — expand status Literal:
```python
status: Literal["candidate", "active", "deprecated", "rejected"] = "active"
```

2. Lines 148-151 — update `has_link()` to include rejected:
```python
if lk.status not in ("active", "rejected"):
    continue
```

3. Add `find_link_between` method after `has_link`:
```python
def find_link_between(self, id_a: str, id_b: str) -> GraphLink | None:
    """Find an active or rejected link between two cards. Returns None if only deprecated or absent."""
    candidates = self._from_index.get(id_a, set()) | self._to_index.get(id_a, set())
    for lid in candidates:
        lk = self._links[lid]
        if lk.status not in ("active", "rejected"):
            continue
        if (lk.from_id == id_a and lk.to_id == id_b) or (
            lk.from_id == id_b and lk.to_id == id_a
        ):
            return lk
    return None
```

4. Add `reject_link` method after `find_link_between`:
```python
def reject_link(self, link_id: str) -> None:
    """Mark a link as rejected by user."""
    lk = self._links.get(link_id)
    if lk is None:
        raise KeyError(f"Link {link_id!r} not found")
    lk.status = "rejected"
    self._save_links()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_manual_link.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing graph tests to verify no regression**

Run: `cd backend && python -m pytest tests/test_graph_index.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/graph.py backend/tests/test_manual_link.py
git commit -m "api: add rejected status, find_link_between, reject_link to GraphStore"
```

---

## Task 2: ManualLinkJudge in judge.py

**Files:**
- Modify: `backend/src/kg/judge.py`
- Test: `backend/tests/test_manual_link.py` (append)

- [ ] **Step 1: Write failing test for ManualLinkJudge**

Append to `backend/tests/test_manual_link.py`:

```python
from unittest.mock import MagicMock
from kg.judge import ManualLinkJudge


class TestManualLinkJudge:
    def _make_client(self, response_json: str):
        client = MagicMock()
        choice = MagicMock()
        choice.message.content = response_json
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage = None
        client.chat.completions.create.return_value = resp
        return client

    def test_returns_judgement_with_kind_and_reason(self):
        client = self._make_client('{"link": "contrasts_with", "confidence": 0.9, "reason": "測試原因"}')
        judge = ManualLinkJudge(client)
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.link in ("contrasts_with", "shares_usage")
        assert result.reason == "測試原因"

    def test_never_returns_none(self):
        """ManualLinkJudge should not return None even for low confidence."""
        client = self._make_client('{"link": "shares_usage", "confidence": 0.3, "reason": "弱關聯"}')
        judge = ManualLinkJudge(client)
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None

    def test_not_applicable_falls_back_to_shares_usage(self):
        """If LLM returns not_applicable despite prompt, fallback to shares_usage."""
        client = self._make_client('{"link": "not_applicable", "confidence": 0.5, "reason": "無明顯關聯"}')
        judge = ManualLinkJudge(client)
        result = judge.evaluate("word_a", "meaning_a", "word_b", "meaning_b")
        assert result is not None
        assert result.link == "shares_usage"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_manual_link.py::TestManualLinkJudge -v`
Expected: FAIL — `ManualLinkJudge` not defined

- [ ] **Step 3: Implement ManualLinkJudge**

Add to end of `backend/src/kg/judge.py`:

```python
MANUAL_LINK_SYSTEM_PROMPT = """The user believes these two vocabulary words are related. Your job is to classify the relationship and explain it.

Choose ONE type:
- contrasts_with: The words have similar or overlapping meanings but differ in nuance, tone, formality, or usage scope
- shares_usage: The words appear in similar contexts, share thematic domains, or complement each other in usage

Do NOT return "not_applicable" — the user has decided these words are related. Find and articulate the connection.

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""


class ManualLinkJudge:
    """LLM judge for user-initiated links. Never returns None."""

    def __init__(self, client: OpenAI, model: str = "gemini-2.5-flash-lite") -> None:
        self.client = client
        self.model = model

    def evaluate(
        self,
        word_a: str,
        meaning_a: str,
        word_b: str,
        meaning_b: str,
        user_id: str | None = None,
    ) -> Judgement:
        user_msg = USER_TEMPLATE.format(
            word_a=word_a, meaning_a=meaning_a,
            word_b=word_b, meaning_b=meaning_b,
        )

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": MANUAL_LINK_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        if user_id and resp.usage:
            from .token_tracker import record
            record(user_id, "manual_link_judge",
                   getattr(resp.usage, "prompt_tokens", 0) or 0,
                   getattr(resp.usage, "completion_tokens", 0) or 0)

        content = resp.choices[0].message.content or ""

        import json
        import re

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if m:
                data = json.loads(m.group())
            else:
                return Judgement(link="shares_usage", confidence=1.0, reason="使用者認為這兩個詞相關。")

        link_val = data.get("link", "shares_usage")
        reason_val = data.get("reason", "")

        # Fallback: if LLM returned not_applicable despite prompt
        if link_val == "not_applicable" or link_val not in ("contrasts_with", "shares_usage"):
            link_val = "shares_usage"

        confidence = 1.0  # Manual links always have full confidence

        return Judgement(link=link_val, confidence=confidence, reason=reason_val)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_manual_link.py::TestManualLinkJudge -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/kg/judge.py backend/tests/test_manual_link.py
git commit -m "api: add ManualLinkJudge with dedicated prompt for user-initiated links"
```

---

## Task 3: API request model + service functions

**Files:**
- Modify: `backend/src/kg/api_models.py`
- Modify: `backend/src/kg/vocab_service.py`
- Test: `backend/tests/test_manual_link.py` (append)

- [ ] **Step 1: Add ManualLinkRequest to api_models.py**

Add after `GraphLinkResponse` (line ~136):

```python
class ManualLinkRequest(BaseModel):
    from_id: str
    to_id: str
```

- [ ] **Step 2: Write failing tests for service functions**

Append to `backend/tests/test_manual_link.py`:

```python
from kg.vocab_service import create_manual_link, reject_graph_link


class FakeCard:
    def __init__(self, id, content="word", meaning="meaning", is_deleted=False, is_archived=False):
        self.id = id
        self.content = content
        self.meaning = meaning
        self.is_deleted = is_deleted
        self.is_archived = is_archived


class FakeCardsStore:
    def __init__(self, cards):
        self._cards = {c.id: c for c in cards}

    def get(self, card_id):
        return self._cards.get(card_id)

    def touch(self, card_id):
        pass


class TestCreateManualLink:
    def test_creates_link_successfully(self, store):
        cards = FakeCardsStore([
            FakeCard("a", content="apple", meaning="蘋果"),
            FakeCard("b", content="banana", meaning="香蕉"),
        ])
        judge_client = TestManualLinkJudge._make_client(
            None, '{"link": "shares_usage", "confidence": 0.9, "reason": "都是水果"}')
        from kg.judge import ManualLinkJudge
        judge = ManualLinkJudge(judge_client)

        result = create_manual_link(
            from_id="a", to_id="b",
            cards_store=cards, graph=store, judge=judge,
        )
        assert result.kind == LinkKind.SHARES_USAGE
        assert result.confidence == 1.0

    def test_rejects_missing_card(self, store):
        cards = FakeCardsStore([FakeCard("a")])
        from kg.judge import ManualLinkJudge
        judge = ManualLinkJudge(MagicMock())

        with pytest.raises(Exception):  # HTTPException 404
            create_manual_link(from_id="a", to_id="missing", cards_store=cards, graph=store, judge=judge)

    def test_rejects_duplicate_active_link(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "existing")
        from kg.judge import ManualLinkJudge
        judge = ManualLinkJudge(MagicMock())

        with pytest.raises(Exception):  # HTTPException 409
            create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)

    def test_revives_rejected_link(self, store):
        cards = FakeCardsStore([
            FakeCard("a", content="apple", meaning="蘋果"),
            FakeCard("b", content="banana", meaning="香蕉"),
        ])
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "old reason")
        store.reject_link(lk.id)

        judge_client = TestManualLinkJudge._make_client(
            None, '{"link": "shares_usage", "confidence": 0.9, "reason": "新原因"}')
        from kg.judge import ManualLinkJudge
        judge = ManualLinkJudge(judge_client)

        result = create_manual_link(from_id="a", to_id="b", cards_store=cards, graph=store, judge=judge)
        assert result.status == "active"
        assert result.reason == "新原因"


class TestRejectGraphLink:
    def test_rejects_link(self, store):
        cards = FakeCardsStore([FakeCard("a"), FakeCard("b")])
        lk = store.add_link("a", "b", LinkKind.CONTRASTS_WITH, 0.9, "r")
        reject_graph_link(link_id=lk.id, graph=store, cards_store=cards)
        assert store.find_link_between("a", "b").status == "rejected"

    def test_rejects_nonexistent_link(self, store):
        cards = FakeCardsStore([])
        with pytest.raises(Exception):  # HTTPException 404
            reject_graph_link(link_id="nonexistent", graph=store, cards_store=cards)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_manual_link.py::TestCreateManualLink tests/test_manual_link.py::TestRejectGraphLink -v`
Expected: FAIL — functions not defined

- [ ] **Step 4: Implement service functions in vocab_service.py**

Add to end of `backend/src/kg/vocab_service.py`:

```python
def create_manual_link(
    *,
    from_id: str,
    to_id: str,
    cards_store: Any,
    graph: Any,
    judge: Any,
) -> Any:
    """Create a manual link between two cards. Calls LLM for kind + reason."""
    from .graph import GraphLink, LinkKind

    card_a = cards_store.get(from_id)
    card_b = cards_store.get(to_id)
    if not card_a or card_a.is_deleted or card_a.is_archived:
        raise HTTPException(404, f"Card '{from_id}' not found or unavailable")
    if not card_b or card_b.is_deleted or card_b.is_archived:
        raise HTTPException(404, f"Card '{to_id}' not found or unavailable")

    existing = graph.find_link_between(from_id, to_id)
    if existing and existing.status == "active":
        raise HTTPException(409, "Link already exists between these cards")

    # Call LLM to determine kind + reason
    judgement = judge.evaluate(
        card_a.content, card_a.meaning,
        card_b.content, card_b.meaning,
    )

    if existing and existing.status == "rejected":
        # Revive the rejected link with new judgement
        existing.status = "active"
        existing.kind = LinkKind(judgement.link)
        existing.confidence = 1.0
        existing.reason = judgement.reason
        graph._save_links()
        link = existing
    else:
        link = graph.add_link(
            from_id, to_id,
            LinkKind(judgement.link),
            confidence=1.0,
            reason=judgement.reason,
        )

    cards_store.touch(from_id)
    cards_store.touch(to_id)
    return link


def reject_graph_link(
    *,
    link_id: str,
    graph: Any,
    cards_store: Any,
) -> None:
    """Reject a link (user-initiated deletion)."""
    try:
        graph.reject_link(link_id)
    except KeyError:
        raise HTTPException(404, f"Link '{link_id}' not found")

    # Touch both cards to trigger incremental sync
    lk = graph._links[link_id]
    cards_store.touch(lk.from_id)
    cards_store.touch(lk.to_id)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_manual_link.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/kg/api_models.py backend/src/kg/vocab_service.py backend/tests/test_manual_link.py
git commit -m "api: add create_manual_link and reject_graph_link service functions"
```

---

## Task 4: API routes (POST + DELETE)

**Files:**
- Modify: `backend/src/kg/vocab_handlers.py`
- Modify: `backend/src/kg/routers/vocab.py`
- Modify: `backend/src/kg/deps.py`

- [ ] **Step 1: Add handler functions in vocab_handlers.py**

Add imports at top:
```python
from .api_models import ManualLinkRequest
from .vocab_service import create_manual_link, reject_graph_link
```

Add at end of file:
```python
def create_manual_link_response(
    req: ManualLinkRequest,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    gemini_client_factory: Callable[[], Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> GraphLinkResponse:
    require_pro_access(user, "knowledge_graph")
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)

    from .judge import ManualLinkJudge
    judge = ManualLinkJudge(gemini_client_factory())

    link = create_manual_link(
        from_id=req.from_id, to_id=req.to_id,
        cards_store=cards, graph=graph, judge=judge,
    )
    return GraphLinkResponse(
        id=link.id,
        fromId=link.from_id,
        toId=link.to_id,
        kind=link.kind.value if hasattr(link.kind, 'value') else link.kind,
        confidence=link.confidence,
        reason=link.reason,
    )


def delete_graph_link_response(
    link_id: str,
    user: dict[str, Any],
    *,
    require_pro_access: Callable[[dict[str, Any], str], None],
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any],
    notebook_store_factory: Callable[[Path], Any] | None = None,
    notebook_id: str = "default",
) -> None:
    require_pro_access(user, "knowledge_graph")
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id)
    reject_graph_link(link_id=link_id, graph=graph, cards_store=cards)
```

- [ ] **Step 2: Add routes in routers/vocab.py**

Add imports for new handler and model:
```python
from ..api_models import ManualLinkRequest
from ..vocab_handlers import create_manual_link_response, delete_graph_link_response
```

Add routes after the existing `get_graph_links` route (line ~159):

```python
@router.post("/api/graph/links", response_model=GraphLinkResponse)
def create_graph_link(
    req: ManualLinkRequest,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    return create_manual_link_response(
        req, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        gemini_client_factory=_gemini_client, notebook_store_factory=_notebook_store,
        notebook_id=notebook_id,
    )


@router.delete("/api/graph/links/{link_id}", status_code=204)
def delete_graph_link(
    link_id: str,
    notebook_id: str = Query("default"),
    user: dict = Depends(get_current_user),
):
    delete_graph_link_response(
        link_id, user, require_pro_access=_require_pro_access,
        card_store_factory=_card_store, graph_store_factory=_graph_store,
        notebook_store_factory=_notebook_store, notebook_id=notebook_id,
    )
```

Add `_gemini_client` import in `routers/vocab.py`:
```python
from ..deps import (
    ...
    _gemini_client,
    ...
)
```

- [ ] **Step 3: Run all backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add backend/src/kg/vocab_handlers.py backend/src/kg/routers/vocab.py backend/src/kg/deps.py
git commit -m "api: add POST/DELETE /api/graph/links endpoints for manual link management"
```

---

## Task 5: iOS — KGService methods for create + delete link

**Files:**
- Modify: `ios/BooksBrowser/Services/KGService+Graph.swift`
- Modify: `ios/BooksBrowser/Services/KGServing.swift`

- [ ] **Step 1: Add request/response models and methods to KGService+Graph.swift**

```swift
// Add after KGGraphLink struct

struct KGManualLinkRequest: Codable {
    let fromId: String
    let toId: String

    enum CodingKeys: String, CodingKey {
        case fromId = "from_id"
        case toId = "to_id"
    }
}

// Add to KGService extension

extension KGService {
    func pullGraphLinks() async throws -> [KGGraphLink] {
        try await authenticatedDecode([KGGraphLink].self, path: "api/graph/links")
    }

    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink {
        let body = try JSONEncoder().encode(KGManualLinkRequest(fromId: fromId, toId: toId))
        return try await authenticatedDecode(
            KGGraphLink.self,
            path: "api/graph/links",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: body
        )
    }

    func deleteLink(linkId: String, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/graph/links/\(linkId)",
            method: "DELETE",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }
}
```

- [ ] **Step 2: Add protocol methods to KGServing.swift**

Add after `func pullGraphLinks()`:
```swift
func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink
func deleteLink(linkId: String, notebookId: String) async throws
```

- [ ] **Step 3: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 4: Commit**

```bash
git add ios/BooksBrowser/Services/KGService+Graph.swift ios/BooksBrowser/Services/KGServing.swift
git commit -m "ios: add createManualLink and deleteLink service methods"
```

---

## Task 6: iOS — AddLinkSheet view

**Files:**
- Create: `ios/BooksBrowser/Views/Vocabulary/Scenes/AddLinkSheet.swift`

- [ ] **Step 1: Create AddLinkSheet**

```swift
import SwiftUI

struct AddLinkSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.vocabSkin) private var vocabSkin

    let sourceEntry: VocabularyEntry
    let allEntries: [VocabularyEntry]
    let onSelect: (VocabularyEntry) -> Void

    @State private var searchText = ""

    private var existingLinkedCardIds: Set<String> {
        Set(sourceEntry.graphLinksByKind.values.flatMap { $0 }.map(\.cardId))
    }

    private var filteredEntries: [VocabularyEntry] {
        let candidates = allEntries.filter { entry in
            entry.id != sourceEntry.id
            && entry.kgCardId != nil
            && !entry.isArchived
            && !(entry.kgCardId.map { existingLinkedCardIds.contains($0) } ?? false)
        }
        guard !searchText.isEmpty else { return [] }
        let query = searchText.lowercased()
        return candidates
            .filter { $0.word.lowercased().contains(query) }
            .prefix(20)
            .map { $0 }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                searchField
                    .padding(vocabSkin.metrics.cardBlockPadding)

                if searchText.isEmpty {
                    ContentUnavailableView(
                        "搜尋單字".localized,
                        systemImage: "magnifyingglass",
                        description: Text("輸入單字名稱來建立連結".localized)
                    )
                    .frame(maxHeight: .infinity)
                } else if filteredEntries.isEmpty {
                    ContentUnavailableView(
                        "沒有結果".localized,
                        systemImage: "magnifyingglass",
                        description: Text("找不到符合的單字".localized)
                    )
                    .frame(maxHeight: .infinity)
                } else {
                    List(filteredEntries) { entry in
                        Button {
                            onSelect(entry)
                            dismiss()
                        } label: {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(entry.word)
                                    .font(vocabSkin.typography.rowWord)
                                    .foregroundStyle(vocabSkin.palette.primaryText)
                                Text(entry.translation)
                                    .font(vocabSkin.typography.caption)
                                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                            }
                        }
                        .listRowBackground(Color.clear)
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                }
            }
            .vocabCanvasBackground()
            .navigationTitle("新增連結".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { dismiss() }
                }
            }
        }
    }

    private var searchField: some View {
        HStack(spacing: vocabSkin.metrics.cardBlockInnerGap) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(vocabSkin.palette.tertiaryText)
            TextField("搜尋單字…".localized, text: $searchText)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
        }
        .padding(vocabSkin.metrics.cardBlockInnerGap * 1.5)
        .background(vocabSkin.palette.cardBackground, in: RoundedRectangle(cornerRadius: 10))
    }
}
```

- [ ] **Step 2: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/AddLinkSheet.swift
git commit -m "ios: add AddLinkSheet for manual link target selection"
```

---

## Task 7: iOS — Wire up WordDetailPresenter + WordDetailSheet

**Files:**
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift:105-126`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift`
- Modify: `ios/BooksBrowser/Views/Vocabulary/Components/WordDetailComponents.swift`

- [ ] **Step 1: Add callbacks to WordDetailPresenter**

In `WordDetailPresenter.swift`, add new callback properties after existing ones:
```swift
let onAddLink: (() -> Void)?
let onDeleteLink: ((KGCardLinkSummary) -> Void)?
```

- [ ] **Step 2: Add "+" button to linksSection header**

Replace `linksSection` (lines 105-126) with:

```swift
private var linksSection: some View {
    VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockContentGap) {
        HStack {
            CardSectionLabel(title: "知識連結".localized, systemImage: "link")
            Spacer()
            if let onAddLink {
                Button(action: onAddLink) {
                    Image(systemName: "plus")
                        .font(vocabSkin.typography.iconSmall)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }
                .buttonStyle(.plain)
            }
        }

        ForEach(state.card.linkGroups) { group in
            VStack(alignment: .leading, spacing: vocabSkin.metrics.cardBlockInnerGap) {
                Text(group.label.localized)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)

                ForEach(group.items) { link in
                    WordDetailGraphLinkRow(
                        link: link,
                        onTap: state.navigableLinkCardIDs.contains(link.cardId) ? {
                            onLinkTapped(link)
                        } : nil,
                        onDelete: onDeleteLink != nil ? { onDeleteLink?(link) } : nil
                    )
                }
            }
        }
    }
}
```

- [ ] **Step 3: Also show linksSection when empty but onAddLink is available**

In `detailContentScroll`, change the condition at line 71 from:
```swift
if !state.card.linkGroups.isEmpty {
```
to:
```swift
if !state.card.linkGroups.isEmpty || onAddLink != nil {
```

- [ ] **Step 4: Add swipe-to-delete to WordDetailGraphLinkRow**

In `WordDetailComponents.swift`, add `onDelete` parameter to `WordDetailGraphLinkRow`:

```swift
struct WordDetailGraphLinkRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let link: KGCardLinkSummary
    let onTap: (() -> Void)?
    let onDelete: (() -> Void)?

    var body: some View {
        Group {
            if let onTap {
                Button(action: onTap) {
                    linkRowContent(showsAccessory: true)
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
            } else {
                linkRowContent(showsAccessory: false)
            }
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            if let onDelete {
                Button(role: .destructive, action: onDelete) {
                    Label("刪除".localized, systemImage: "trash")
                }
            }
        }
    }
    // ... linkRowContent unchanged
}
```

Note: swipe actions require the row to be inside a `List` or `ForEach` within a `List`. Since the current implementation uses `VStack` + `ForEach`, swipe won't work natively. Instead, use a context menu approach:

```swift
var body: some View {
    Group {
        if let onTap {
            Button(action: onTap) {
                linkRowContent(showsAccessory: true)
            }
            .buttonStyle(.plain)
            .contentShape(Rectangle())
        } else {
            linkRowContent(showsAccessory: false)
        }
    }
    .contextMenu {
        if let onDelete {
            Button(role: .destructive) {
                onDelete()
            } label: {
                Label("刪除連結".localized, systemImage: "trash")
            }
        }
    }
}
```

- [ ] **Step 5: Wire up in WordDetailSheet**

In `WordDetailSheet.swift`, add state and service:

```swift
@State private var showAddLink = false
@State private var isCreatingLink = false
@Environment(\.kgService) private var kgService
```

Update the `WordDetailPresenter` call to pass new callbacks:

```swift
WordDetailPresenter(
    state: presenterState,
    wrapInNavigation: wrapInNavigation,
    onClose: wrapInNavigation ? { dismiss() } : nil,
    onEdit: wrapInNavigation ? { isEditing = true } : nil,
    onLinkTapped: handleLinkTap,
    onToggleExcludeFromReader: { entry.isExcludedFromReader.toggle() },
    onAddLink: { showAddLink = true },
    onDeleteLink: handleDeleteLink
)
```

Add the sheet modifier after the existing `.sheet(isPresented: $isEditing)`:

```swift
.sheet(isPresented: $showAddLink) {
    AddLinkSheet(
        sourceEntry: entry,
        allEntries: allEntries,
        onSelect: handleAddLink
    )
}
```

Add handler functions:

```swift
private func handleAddLink(_ target: VocabularyEntry) {
    guard let fromId = entry.kgCardId, let toId = target.kgCardId else { return }
    let notebookId = entry.notebookId ?? "default"
    isCreatingLink = true
    Task {
        defer { isCreatingLink = false }
        do {
            let link = try await kgService.createManualLink(
                fromId: fromId, toId: toId, notebookId: notebookId
            )
            // Update local graphLinksJSON
            var current = entry.graphLinksByKind
            let summary = KGCardLinkSummary(
                id: link.id,
                cardId: toId,
                word: target.word,
                kind: link.kind,
                label: link.kind == "contrasts_with" ? "對比" : "相關",
                confidence: link.confidence,
                reason: link.reason
            )
            current[link.kind, default: []].append(summary)
            entry.graphLinksByKind = current
        } catch {
            // Error handling — silent for now, sync will reconcile
        }
    }
}

private func handleDeleteLink(_ link: KGCardLinkSummary) {
    let notebookId = entry.notebookId ?? "default"
    Task {
        do {
            try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
            // Remove from local cache
            var current = entry.graphLinksByKind
            current[link.kind]?.removeAll { $0.id == link.id }
            if current[link.kind]?.isEmpty == true {
                current.removeValue(forKey: link.kind)
            }
            entry.graphLinksByKind = current
        } catch {
            // Error handling — silent for now, sync will reconcile
        }
    }
}
```

- [ ] **Step 6: Check kgService environment key exists**

Verify that `@Environment(\.kgService)` is available. Search for the environment key definition. If it uses a different pattern (e.g., passed via init), adapt accordingly.

- [ ] **Step 7: Build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 8: Commit**

```bash
git add ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailPresenter.swift \
        ios/BooksBrowser/Views/Vocabulary/Scenes/WordDetailSheet.swift \
        ios/BooksBrowser/Views/Vocabulary/Components/WordDetailComponents.swift
git commit -m "ios: wire up manual link creation and deletion in WordDetailSheet"
```

---

## Task 8: Integration test + final verification

**Files:**
- Test: `backend/tests/test_manual_link.py` (append API-level test if needed)

- [ ] **Step 1: Run full backend test suite**

Run: `cd backend && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run iOS build**

Run: `./ops/ios_build.sh`
Expected: Exit 0

- [ ] **Step 3: Final commit and PR**

```bash
git add -A
git status  # verify no untracked files that shouldn't be committed
```

Create PR with title: `feat: manual graph link creation and deletion (#NNN)`
