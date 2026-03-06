import os
import shutil
from pathlib import Path
from dotenv import load_dotenv
from src.kg.mochi import MochiClient

load_dotenv()
DATA_DIR = Path(os.getenv("KG_DATA_DIR", "./data"))

def main():
    print("WARNING: This will delete ALL local data (cards, embeddings, links) and the Mochi 'Knowledge' deck.")
    print("Files preserved: *.csv")
    
    # We won't use input() here to avoid hanging if run via automation, 
    # but the user explicitly requested this via the agent.
    # However, for safety, I'll assume the agent is running it intentionally.
    
    # 1. Delete Local Files
    print("Deleting local files...")
    extensions = [".json", ".npy", ".bak"]
    deleted_count = 0
    
    if DATA_DIR.exists():
        for f in DATA_DIR.iterdir():
            if f.is_file() and any(f.suffix == ext for ext in extensions):
                # Preserve specific config files if any? No, reset all.
                # Just keep CSVs.
                try:
                    f.unlink()
                    print(f"Deleted: {f.name}")
                    deleted_count += 1
                except Exception as e:
                    print(f"Failed to delete {f.name}: {e}")
                    
    print(f"Deleted {deleted_count} local files.")
    
    # 2. Delete Mochi Deck
    print("Deleting Mochi deck 'Knowledge'...")
    api_key = os.getenv("MOCHI_API_KEY")
    if not api_key:
        print("No MOCHI_API_KEY found, skipping deck deletion.")
        return
        
    client = MochiClient(api_key)
    decks = client.list_decks()
    
    target_deck = None
    for d in decks:
        if d["name"] == "Knowledge":
            target_deck = d
            break
            
    if target_deck:
        try:
            # Client doesn't have public delete_deck, use internal
            client._request("DELETE", f"/decks/{target_deck['id']}")
            print(f"Deleted Mochi deck: {target_deck['name']} ({target_deck['id']})")
        except Exception as e:
            print(f"Failed to delete deck: {e}")
    else:
        print("Deck 'Knowledge' not found.")
        
    print("\nReset Complete.")
    print("You can now run 'kg ui' -> [Import] to restore from CSV.")

if __name__ == "__main__":
    main()
