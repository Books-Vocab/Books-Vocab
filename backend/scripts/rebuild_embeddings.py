"""Rebuild embeddings for all users using the current EMBEDDING_MODEL."""
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from kg.cards import CardStore
from kg.embeddings import EMBEDDING_MODEL, EmbeddingStore
from kg.service_factories import create_gemini_client


def main():
    data_dir = Path(os.getenv("KG_DATA_DIR", Path(__file__).parent.parent / "data"))
    users_dir = data_dir / "users"

    if not users_dir.exists():
        print(f"Users directory not found: {users_dir}")
        return

    client = create_gemini_client()

    user_dirs = [d for d in users_dir.iterdir() if d.is_dir()]
    print(f"Found {len(user_dirs)} user(s). Model: {EMBEDDING_MODEL}")

    total_cards = 0
    for user_dir in sorted(user_dirs):
        db_path = user_dir / "cards.db"
        if not db_path.exists():
            continue

        cards = CardStore(db_path)
        all_cards = list(cards.all())
        if not all_cards:
            continue

        print(f"\n  {user_dir.name}: {len(all_cards)} cards")
        emb = EmbeddingStore(
            user_dir / "embeddings.npy",
            user_dir / "card_ids.json",
            client,
        )

        for card in all_cards:
            emb.add(card.id, card.embed_text())

        total_cards += len(all_cards)

    print(f"\nDone! Rebuilt embeddings for {total_cards} cards across {len(user_dirs)} users.")


if __name__ == "__main__":
    main()
