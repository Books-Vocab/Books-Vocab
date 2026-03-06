import json
import numpy as np
from pathlib import Path

def main():
    user_dir = Path("data/users/chen")
    cards_path = user_dir / "cards.json"
    embeddings_path = user_dir / "embeddings.npy"
    ids_path = user_dir / "card_ids.json"

    cards = json.loads(cards_path.read_text())
    total_cards = len(cards)
    
    embeddings = np.load(embeddings_path)
    ids = json.loads(ids_path.read_text())

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normalized = embeddings / (norms + 1e-9)
    sim_mat = normalized @ normalized.T
    np.fill_diagonal(sim_mat, -1.0)
    top5 = np.sort(sim_mat, axis=1)[:, -5:][:, ::-1]

    thresholds = [0.65, 0.66, 0.67, 0.68, 0.69, 0.70]
    for t in thresholds:
        count = np.sum(top5 > t)
        print(f"Threshold > {t:.2f}: {count} candidates ({count/total_cards*100:.1f}%)")

if __name__ == "__main__":
    main()
