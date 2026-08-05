"""Dictionary sidecar and materialization-operation tables in ``cards.db``."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


class DictionaryEntry(SQLModel, table=True):
    __tablename__ = "dictionary_entry"

    card_id: str = SQLField(primary_key=True)
    provider: str
    dictionary_id: str
    provider_entry_key: str
    provider_schema_version: str
    selected_sense_key: str
    selected_example_key: str
    payload_json: str
    source_url: str
    license_name: str
    license_url: str
    attribution_text: str
    fetched_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    materialization_status: str = SQLField(default="staged")


class LexicalOperation(SQLModel, table=True):
    __tablename__ = "lexical_operations"

    idempotency_key: str = SQLField(primary_key=True)
    request_hash: str
    status: str = SQLField(default="started")
    card_id: str | None = None
    link_id: str | None = None
    relation_json: str | None = None
    response_json: str | None = None
    created_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))


class DictionaryPromotionJob(SQLModel, table=True):
    """Durable one-per-card promotion work item.

    The card row remains the client-facing lifecycle source of truth; this row
    carries worker recovery/error state that must survive process restarts.
    """

    __tablename__ = "dictionary_promotion_jobs"

    card_id: str = SQLField(primary_key=True)
    status: str = SQLField(default="queued")
    attempt_count: int = SQLField(default=0)
    error_code: str | None = None
    retryable: bool | None = None
    worker_id: str | None = None
    queued_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    updated_at: datetime = SQLField(default_factory=lambda: datetime.now(UTC))
