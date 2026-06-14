"""One-time migration: regenerate graph link reasons in 繁體中文.

Usage:
    python -m kg.migrations.migrate_graph_reasons [data_dir]

Default data_dir: ./data

Reads each user's graph_*.json, finds active links, looks up the two
cards' content+meaning from cards.db, calls Gemini to produce a Chinese
reason, and overwrites the link in-place. A .bak is kept automatically
by GraphStore._save_links().
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _has_cjk(text: str) -> bool:
    return any('\u4e00' <= ch <= '\u9fff' for ch in text)


def migrate_user_graph(user_dir: Path, client, model: str) -> int:
    """Migrate all notebook graphs for one user. Returns count of updated links."""
    from kg.cards import CardStore
    from kg.graph import GraphStore

    # Inline prompts (originally from judge.py, inlined for migration stability)
    _MIGRATE_SYSTEM_PROMPT = """Judge vocabulary relationship. Choose ONE type:
- contrasts_with: Genuinely opposite or contrasting meanings
- shares_usage: Used in similar contexts or fill similar grammatical roles
- not_applicable: No meaningful learning relationship

Write "reason" in 繁體中文 (1-2 sentences). Explain the relationship AND highlight the nuance/difference between the two words to help learners distinguish them.

Respond JSON: {"link": "<type>", "confidence": <0.0-1.0>, "reason": "<繁體中文>"}"""

    _MIGRATE_USER_TEMPLATE = "Word A: {word_a}\nMeaning A: {meaning_a}\n\nWord B: {word_b}\nMeaning B: {meaning_b}\n\nDetermine the relationship type and your confidence (0.0-1.0)."

    import json
    import re

    graph_files = sorted(user_dir.glob("graph_*.json"))
    if not graph_files:
        return 0

    total_updated = 0

    for graph_path in graph_files:
        notebook_id = graph_path.stem.replace("graph_", "")
        candidates_path = user_dir / f"candidates_{notebook_id}.json"
        cards_db_path = user_dir / "cards.db"

        if not cards_db_path.exists():
            logger.warning("  No cards.db in %s, skipping", user_dir.name)
            continue

        cards = CardStore(cards_db_path)
        graph = GraphStore(graph_path, candidates_path)

        active_links = [lk for lk in graph.all_links() if lk.status == "active"]
        if not active_links:
            continue

        logger.info("  [%s] %d active links to migrate", notebook_id, len(active_links))

        for link in active_links:
            if _has_cjk(link.reason):
                continue  # already migrated
            card_a = cards.get(link.from_id)
            card_b = cards.get(link.to_id)
            if not card_a or not card_b:
                logger.warning("    Skipping link %s: missing card(s)", link.id)
                continue

            user_msg = _MIGRATE_USER_TEMPLATE.format(
                word_a=card_a.content,
                meaning_a=card_a.meaning,
                word_b=card_b.content,
                meaning_b=card_b.meaning,
            )

            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": _MIGRATE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                content = resp.choices[0].message.content or ""
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, ValueError):
                logger.warning("LLM returned malformed JSON for %s; trying regex fallback", link.id)
                m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
                data = json.loads(m.group()) if m else {}

                if data.get("link") == "not_applicable":
                    logger.warning("    Link %s: LLM says not_applicable, keeping old", link.id)
                    continue
                new_reason = data.get("reason", "")
                if not new_reason:
                    logger.warning("    Link %s: empty reason from LLM, keeping old", link.id)
                    continue

                old_reason = link.reason
                # source=ops:此為一次性運維遷移,圖譜事件帳本不應記成 pipeline(auto)變動。
                graph.update_link(link.id, reason=new_reason, source="ops")
                total_updated += 1
                logger.info("    %s <-> %s: %s -> %s",
                            card_a.content, card_b.content,
                            old_reason[:40], new_reason[:40])

            except Exception as exc:
                logger.error("    Link %s failed: %s", link.id, exc, exc_info=True)
                continue

        # Touch all cards involved in active links so incremental sync picks them up
        touched_ids = set()
        for link in active_links:
            touched_ids.add(link.from_id)
            touched_ids.add(link.to_id)
        touch_count = sum(1 for cid in touched_ids if cards.touch(cid))
        logger.info("  [%s] saved, touched %d cards for sync", notebook_id, touch_count)

    return total_updated


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    if not data_dir.exists():
        logger.error("Data directory %s does not exist", data_dir)
        sys.exit(1)

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY env var is required")
        sys.exit(1)

    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )

    # User dirs live under data_dir/users/ (production layout)
    users_root = data_dir / "users" if (data_dir / "users").is_dir() else data_dir
    user_dirs = sorted([
        d for d in users_root.iterdir()
        if d.is_dir() and (d / "cards.db").exists()
    ])
    logger.info("Found %d user directories", len(user_dirs))

    grand_total = 0
    for user_dir in user_dirs:
        logger.info("Migrating %s ...", user_dir.name)
        try:
            count = migrate_user_graph(user_dir, client, model)
            grand_total += count
            if count:
                logger.info("  Updated %d links", count)
        except Exception as exc:
            logger.error("  FAILED: %s", exc, exc_info=True)

    logger.info("Migration complete. Total links updated: %d", grand_total)


if __name__ == "__main__":
    main()
