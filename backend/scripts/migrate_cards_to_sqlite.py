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

from kg.cards import Card, CardStore
from sqlmodel import Session

def migrate_user(user_dir: Path):
    """Migrates a single user's cards.json to cards.db"""
    json_path = user_dir / "cards.json"
    db_path = user_dir / "cards.db"
    backup_path = user_dir / "cards.json.bak"

    if not json_path.exists():
        logger.info(f"Skipping {user_dir.name} - no cards.json found.")
        return

    if db_path.exists():
        logger.warning(f"Skipping {user_dir.name} - cards.db already exists.")
        return

    logger.info(f"Migrating user: {user_dir.name}")
    
    # 1. Load old JSON
    try:
        data = json.loads(json_path.read_text())
    except Exception as e:
        logger.error(f"Failed to read JSON for {user_dir.name}: {e}")
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
                logger.error(f"Failed to parse card {cdict.get('id', 'unknown')} for {user_dir.name}: {e}")
        
        session.commit()

    logger.info(f"✅ Successfully migrated {migrated_count} cards for user {user_dir.name}.")

    # 4. Backup old JSON
    shutil.move(json_path, backup_path)
    logger.info(f"Backed up {json_path.name} to {backup_path.name}")

def main():
    data_dir = project_root / "data" / "users"
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    logger.info("Starting cards.json to SQLite migration...")
    
    # Iterate through user directories
    for user_dir in data_dir.iterdir():
        if user_dir.is_dir():
            migrate_user(user_dir)
            
    logger.info("Migration complete.")

if __name__ == "__main__":
    main()
