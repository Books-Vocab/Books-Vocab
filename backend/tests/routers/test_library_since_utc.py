from __future__ import annotations

import pytest

from kg.api_models.library import BookMetadataResponse
from kg.exceptions import BadRequestError
from kg.routers import library as library_router


class _FakeLibraryStore:
    def __init__(self, books: list[BookMetadataResponse]) -> None:
        self.books = books

    def all(self, *, include_deleted: bool) -> list[BookMetadataResponse]:
        assert include_deleted is True
        return self.books


def test_since_filter_compares_utc_instants_for_mixed_offsets(monkeypatch):
    books = [
        BookMetadataResponse(
            id="before",
            title="Before",
            updated_at="2026-08-21T11:00:00+02:00",  # 09:00 UTC
        ),
        BookMetadataResponse(
            id="equal",
            title="Equal",
            updated_at="2026-08-21T12:00:00+02:00",  # 10:00 UTC
        ),
        BookMetadataResponse(
            id="after",
            title="After",
            updated_at="2026-08-21T09:30:00-02:00",  # 11:30 UTC
        ),
    ]
    monkeypatch.setattr(
        library_router,
        "_library_store",
        lambda _user_dir: _FakeLibraryStore(books),
    )

    result = library_router.list_books(
        {"dir": "ignored"},
        since="2026-08-21T10:00:00Z",
    )

    assert [book.id for book in result] == ["after"]


def test_empty_since_is_rejected_instead_of_disabling_filter(monkeypatch):
    monkeypatch.setattr(
        library_router,
        "_library_store",
        lambda _user_dir: _FakeLibraryStore([]),
    )

    with pytest.raises(BadRequestError, match="Invalid since timestamp"):
        library_router.list_books({"dir": "ignored"}, since="")
