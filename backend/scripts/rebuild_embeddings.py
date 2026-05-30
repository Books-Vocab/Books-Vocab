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

# Cap a single embedding API request size. Each chunk = one API call + one full
# embeddings.npy save, so chunking keeps us at O(N/chunk) round-trips and saves
# instead of the old O(N) per-card hammering.
_EMBED_CHUNK_SIZE = 100


def rebuild_user_embeddings(emb, cards, chunk_size: int = _EMBED_CHUNK_SIZE) -> int:
    """Embed every card via batched `add_batch` calls (chunk_size per call).

    Replaces the old per-card `emb.add(...)` loop, which issued one API call and
    one full-matrix disk save *per card* (N round-trips, O(N^2) bytes written).
    Returns the number of cards processed.
    """
    items = [(c.id, c.embed_text()) for c in cards]
    for start in range(0, len(items), chunk_size):
        emb.add_batch(items[start:start + chunk_size])
    return len(items)


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

        rebuild_user_embeddings(emb, all_cards)

        total_cards += len(all_cards)

    print(f"\nDone! Rebuilt embeddings for {total_cards} cards across {len(user_dirs)} users.")


if __name__ == "__main__":
    main()
