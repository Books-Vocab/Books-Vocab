import json
import logging
import shutil
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Add src to path so we can import kg
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root / "src"))

from sqlmodel import Session

from kg.cards import Card, CardStore


def migrate_user(user_dir: Path):
    """Migrates a single user's cards.json to cards.db"""
    json_path = user_dir / "cards.json"
    db_path = user_dir / "cards.db"
    backup_path = user_dir / "cards.json.bak"

    if not json_path.exists():
        logger.info("Skipping %s - no cards.json found.", user_dir.name)
        return

    if db_path.exists():
        logger.warning("Skipping %s - cards.db already exists.", user_dir.name)
        return

    logger.info("Migrating user: %s", user_dir.name)

    # 1. Load old JSON
    try:
        data = json.loads(json_path.read_text())
    except Exception as e:
        logger.error("Failed to read JSON for %s: %s", user_dir.name, e)
        return

    # 2. Init SQLite Store
    store = CardStore(db_path)

    # 3. Insert all records
    migrated_count = 0
    with Session(store.engine) as session:
        for cdict in data:
            try:
                # Safely instantiate via model_validate which handles DB model conversion
                card = Card.model_validate(cdict)
                session.add(card)
                migrated_count += 1
            except Exception as e:
                logger.error("Failed to parse card %s for %s: %s", cdict.get('id', 'unknown'), user_dir.name, e)

        session.commit()

    logger.info("✅ Successfully migrated %s cards for user %s.", migrated_count, user_dir.name)

    # 4. Backup old JSON
    shutil.move(json_path, backup_path)
    logger.info("Backed up %s to %s", json_path.name, backup_path.name)

def main():
    data_dir = project_root / "data" / "users"
    if not data_dir.exists():
        logger.error("Data directory not found: %s", data_dir)
        sys.exit(1)

    logger.info("Starting cards.json to SQLite migration...")

    # Iterate through user directories
    for user_dir in data_dir.iterdir():
        if user_dir.is_dir():
            migrate_user(user_dir)

    logger.info("Migration complete.")

if __name__ == "__main__":
    main()
