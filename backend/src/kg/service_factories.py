from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

from .cards import CardStore
from .daily_stats import DailyReviewStatsStore
from .embeddings import EmbeddingStore
from .graph import GraphStore


def create_card_store(user_dir: Path) -> CardStore:
    return CardStore(user_dir / "cards.db")


def create_daily_stats_store(user_dir: Path) -> DailyReviewStatsStore:
    return DailyReviewStatsStore(user_dir / "daily_review_stats.db")


def create_graph_store(user_dir: Path) -> GraphStore:
    return GraphStore(user_dir / "graph.json", user_dir / "candidates.json")


def create_gemini_client():
    from openai import OpenAI

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def create_embedding_store(
    user_dir: Path,
    *,
    gemini_client_factory,
    user_id: str | None = None,
) -> EmbeddingStore:
    return EmbeddingStore(
        user_dir / "embeddings.npy",
        user_dir / "card_ids.json",
        gemini_client_factory(),
        user_id=user_id,
    )
