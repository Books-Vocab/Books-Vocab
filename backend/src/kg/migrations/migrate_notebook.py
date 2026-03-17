"""One-time migration: introduce notebook concept to existing user data.

Usage:
    python -m kg.migrations.migrate_notebook [data_dir]

Default data_dir: ./data
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def migrate_user(user_dir: Path) -> None:
    """Migrate a single user directory to notebook-aware layout."""

    # 1. Create notebooks.db with default notebook
    from kg.notebook import NotebookStore
    nb_store = NotebookStore(user_dir / "notebooks.db")
    nb_store.ensure_default()
    logger.info("  [notebooks.db] default notebook ensured")

    # 2. cards.db: add notebook_id column (CardStore lazy migration handles this)
    cards_db = user_dir / "cards.db"
    if cards_db.exists():
        from kg.cards import CardStore
        CardStore(cards_db)  # triggers _migrate_review_columns which adds notebook_id
        logger.info("  [cards.db] notebook_id column ensured")

    # 3. Rename graph files
    for old_name, new_name in [
        ("graph.json", "graph_default.json"),
        ("candidates.json", "candidates_default.json"),
        ("embeddings.npy", "embeddings_default.npy"),
        ("card_ids.json", "card_ids_default.json"),
    ]:
        old_path = user_dir / old_name
        new_path = user_dir / new_name
        if old_path.exists() and not new_path.exists():
            old_path.rename(new_path)
            logger.info("  Renamed %s -> %s", old_name, new_name)
            # Also rename .bak files if present
            bak = old_path.with_suffix(old_path.suffix + ".bak")
            if bak.exists():
                bak.rename(new_path.with_suffix(new_path.suffix + ".bak"))


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data")
    if not data_dir.exists():
        logger.error("Data directory %s does not exist", data_dir)
        sys.exit(1)

    user_dirs = [d for d in data_dir.iterdir() if d.is_dir() and (d / "cards.db").exists()]
    logger.info("Found %d user directories to migrate", len(user_dirs))

    for user_dir in user_dirs:
        logger.info("Migrating %s ...", user_dir.name)
        try:
            migrate_user(user_dir)
        except Exception as exc:
            logger.error("  FAILED: %s", exc, exc_info=True)

    logger.info("Migration complete.")


if __name__ == "__main__":
    main()
