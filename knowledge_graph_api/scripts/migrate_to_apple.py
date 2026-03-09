#!/usr/bin/env python3
"""Migrate existing single-user data to Apple Sign In multi-user structure."""

import json
import os
import shutil
from pathlib import Path

def main():
    print("==================================================")
    print(" Knowledge Graph: Multi-User Migration Script")
    print("==================================================")
    print("This script will move your existing data into a per-user directory")
    print("based on your Apple User ID (sub).")
    print()
    
    apple_id = input("Enter your Apple User ID (sub): ").strip()
    if not apple_id:
        print("Error: Apple User ID cannot be empty.")
        return
        
    mochi_key = input("Enter your Mochi API Key (or press Enter to read from .env): ").strip()
    
    # Resolve Paths
    data_dir = Path(__file__).resolve().parent.parent / "data"
    users_dir = data_dir / "users"
    target_dir = users_dir / apple_id
    users_file = data_dir / "users.json"
    
    # 1. Create structure
    print(f"\n=> Creating target directory: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Find eligible data files in root 'data/'
    # Exclude directories and metadata files like users.json
    files_to_move = []
    for f in data_dir.iterdir():
        if f.is_file() and f.name not in ["users.json", ".gitkeep"]:
            files_to_move.append(f)
            
    if not files_to_move:
        print("=> No data files found in root data/ directory to migrate.")
    else:
        print(f"=> Moving {len(files_to_move)} files...")
        for src in files_to_move:
            dst = target_dir / src.name
            print(f"   Moving: {src.name}")
            shutil.move(str(src), str(dst))
            
    # 3. Handle users.json config
    if not mochi_key:
        from dotenv import load_dotenv
        load_dotenv()
        mochi_key = os.getenv("MOCHI_API_KEY", "")
        
    print(f"\n=> Updating {users_file.name}...")
    users = {}
    if users_file.exists():
        with open(users_file, "r") as f:
            users = json.load(f)
            
    # Always set or update
    if apple_id not in users:
        users[apple_id] = {}

    if not isinstance(users[apple_id].get("config"), dict):
        users[apple_id]["config"] = {}

    if mochi_key:
        users[apple_id]["config"]["mochi_api_key"] = mochi_key
        users[apple_id]["config"]["integrations"] = {
            "mochi": {
                "api_key": mochi_key
            }
        }
        print("   Mochi API Key linked to your Apple ID.")
        
    with open(users_file, "w") as f:
        json.dump(users, f, indent=2)
        
    print("\n✅ Migration complete!")
    print(f"Your data is now safely isolated at: data/users/{apple_id}/")
    print(f"Consider updating DEFAULT_USER_ID={apple_id} in your .env for CLI usage.")

if __name__ == "__main__":
    main()
