import json
import numpy as np
from pathlib import Path
from kg.graph import GraphStore
from kg.embeddings import EmbeddingStore
import os
from openai import OpenAI
from dotenv import load_dotenv

def main():
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    
    user_dir = Path("data/users/chen")
    cards = json.loads((user_dir / "cards.json").read_text())
    
    # Sort cards by created_at descending to get the 25 newest
    cards.sort(key=lambda c: c.get("created_at", ""), reverse=True)
    new_cards = cards[:25]
    
    graph = GraphStore(user_dir / "graph.json", user_dir / "candidates.json")
    embeddings = EmbeddingStore(user_dir / "embeddings.npy", user_dir / "card_ids.json", client)
    
    count = 0
    print("Regenerating candidates for 25 newest cards...")
    for c in new_cards:
        sims = embeddings.find_similar(c["id"], k=3)
        for other_id, score in sims:
            if score > 0.655:
                # Add candidate handles deduplication
                graph.add_candidate(c["id"], other_id, score)
                count += 1
                
    print(f"Done! Requeued {count} candidates total.")
    
if __name__ == "__main__":
    main()
