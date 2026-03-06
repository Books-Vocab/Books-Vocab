import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from kg.cli import get_card_store, get_embedding_store
from tqdm import tqdm

def main():
    cards = get_card_store()
    all_cards = list(cards.all())
    if not all_cards:
        print("No cards found.")
        return
        
    print(f"Rebuilding embeddings for {len(all_cards)} cards using Gemini text-embedding-004...")
    embeddings = get_embedding_store()
    
    for card in tqdm(all_cards):
        embeddings.add(card.id, card.embed_text())
        
    print("Done!")

if __name__ == "__main__":
    main()
