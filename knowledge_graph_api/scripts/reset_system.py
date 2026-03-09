import os
import shutil
import json
from pathlib import Path
from dotenv import load_dotenv
from src.kg.mochi import MochiClient
from src.kg.user_store import resolve_mochi_api_key_from_config

load_dotenv()
DATA_DIR = Path(os.getenv("KG_DATA_DIR", "./data"))
USERS_FILE = DATA_DIR / "users.json"


def resolve_mochi_api_key() -> tuple[str | None, str]:
    preferred_user_id = os.getenv("KG_RESET_USER_ID") or os.getenv("DEFAULT_USER_ID")

    users = {}
    if USERS_FILE.exists():
        try:
            users = json.loads(USERS_FILE.read_text())
        except json.JSONDecodeError:
            users = {}

    def key_for(record: dict) -> str:
        config = record.get("config", {})
        if isinstance(config, dict):
            nested = resolve_mochi_api_key_from_config(config)
            if nested:
                return nested
        return ""

    if preferred_user_id:
        record = users.get(preferred_user_id, {})
        if isinstance(record, dict):
            preferred_key = key_for(record)
            if preferred_key:
                return preferred_key, f"user:{preferred_user_id}"

    configured_users = [
        (user_id, key_for(record))
        for user_id, record in users.items()
        if isinstance(record, dict) and not user_id.startswith("_")
    ]
    configured_users = [(user_id, key) for user_id, key in configured_users if key]

    if len(configured_users) == 1:
        user_id, key = configured_users[0]
        return key, f"user:{user_id}"

    legacy_env_key = os.getenv("MOCHI_API_KEY", "").strip()
    if legacy_env_key:
        return legacy_env_key, "legacy-env:MOCHI_API_KEY"

    if len(configured_users) > 1:
        return None, "multiple-users"

    return None, "not-found"

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
    api_key, source = resolve_mochi_api_key()
    if not api_key:
        if source == "multiple-users":
            print("Multiple user-scoped Mochi keys found. Set KG_RESET_USER_ID or DEFAULT_USER_ID to choose one.")
        else:
            print("No user-scoped Mochi key found, skipping deck deletion.")
        return

    if source.startswith("legacy-env:"):
        print("Using legacy system env MOCHI_API_KEY fallback.")
    else:
        print(f"Resolved Mochi key from {source}.")

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
