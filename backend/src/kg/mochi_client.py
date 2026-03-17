"""Mochi REST API client."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import httpx

from .retry import sync_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://app.mochi.cards/api"


class MochiClient:
    """Mochi REST API client with automatic retry."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.retry_callback = None
        self._client = httpx.Client(
            base_url=BASE_URL,
            auth=(api_key, ""),
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    def _request(self, method: str, path: str, **kwargs) -> dict:
        from httpx import HTTPStatusError, RequestError

        def _do_request() -> dict:
            resp = self._client.request(method, path, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

        def _delay_fn(attempt: int, exc: BaseException) -> float | None:
            if isinstance(exc, HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503, 504):
                wait = int(exc.response.headers.get("Retry-After", 2 ** (attempt + 1)))
                if self.retry_callback:
                    self.retry_callback(f"Mochi status {exc.response.status_code}, retrying in {wait}s...")
                return float(wait)
            if isinstance(exc, RequestError):
                wait = 2 ** (attempt + 1)
                if self.retry_callback:
                    self.retry_callback(f"Mochi network error, retrying in {wait}s...")
                return float(wait)
            return None

        return sync_retry(
            _do_request,
            max_attempts=4,
            retryable_exceptions=(HTTPStatusError, RequestError),
            delay_fn=_delay_fn,
            step_name="Mochi API",
        )

    # --- Decks ---

    def list_decks(self) -> list[dict]:
        """List all decks."""
        result = self._request("GET", "/decks")
        return result.get("docs", [])

    def create_deck(self, name: str) -> dict:
        """Create a new deck."""
        return self._request("POST", "/decks", json={"name": name})

    def get_deck(self, deck_id: str) -> dict:
        """Get deck by ID."""
        return self._request("GET", f"/decks/{deck_id}")

    # --- Cards ---

    def get_card(self, card_id: str) -> dict:
        """Get card by ID."""
        return self._request("GET", f"/cards/{card_id}")

    def list_cards(self, deck_id: str) -> Iterator[dict]:
        """List all cards in a deck (handles pagination)."""
        bookmark = None
        while True:
            params = {"deck-id": deck_id}
            if bookmark:
                params["bookmark"] = bookmark
            result = self._request("GET", "/cards", params=params)
            yield from result.get("docs", [])
            bookmark = result.get("bookmark")
            if not bookmark or not result.get("docs"):
                break

    def create_card(self, deck_id: str, content: str) -> dict:
        """Create a new card in a deck."""
        return self._request("POST", "/cards", json={"deck-id": deck_id, "content": content})

    def update_card(self, card_id: str, content: str, tags: list[str] | None = None,
                    fields: dict | None = None, template_id: str | None = None) -> dict:
        """Update card content and optionally tags/fields."""
        payload: dict = {"content": content}
        if tags is not None:
            payload["manual-tags"] = tags
        if fields:
            payload["fields"] = fields
        if template_id:
            payload["template-id"] = template_id
        return self._request("POST", f"/cards/{card_id}", json=payload)

    def delete_card(self, card_id: str) -> None:
        """Delete a card."""
        self._request("DELETE", f"/cards/{card_id}")
