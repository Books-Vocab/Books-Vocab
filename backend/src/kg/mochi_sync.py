"""Mochi sync engine: pushes/pulls Cards to/from Mochi."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import httpx

from .cards import Card, CardStore
from .graph import GraphStore
from .mochi_client import MochiClient
from .renderer import TEMPLATE_ID, CardRenderer, RenderIntent

logger = logging.getLogger(__name__)


class MochiSync:
    """Syncs Cards to Mochi with intent-based rendering."""

    def __init__(
        self,
        client: MochiClient,
        cards: CardStore,
        graph: GraphStore,
        map_path: Path,
        deck_name: str = "Knowledge",
    ) -> None:
        self.client = client
        self.cards = cards
        self.graph = graph
        # Unified sync file: {"map": {...}, "state": {...}}
        # map_path kept for backward-compat path resolution; actual file is mochi_sync.json
        self._sync_path = map_path.parent / "mochi_sync.json"
        self._legacy_map_path = map_path
        self._legacy_state_path = map_path.parent / "sync_state.json"
        self.deck_name = deck_name
        self._deck_id: str | None = None
        self._map: dict[str, str] = {}   # card_id -> mochi_card_id
        self._state: dict[str, str] = {} # card_id -> content_hash
        self._load()

    def _load(self) -> None:
        """Load unified sync file, migrating legacy files if needed."""
        if self._sync_path.exists():
            try:
                data = json.loads(self._sync_path.read_text())
                self._map = data.get("map", {})
                self._state = data.get("state", {})
                return
            except json.JSONDecodeError:
                logger.warning("mochi_sync.json corrupted, attempting legacy migration")

        # Migrate from legacy separate files
        if self._legacy_map_path.exists():
            try:
                self._map = json.loads(self._legacy_map_path.read_text())
            except json.JSONDecodeError:
                self._map = {}
        if self._legacy_state_path.exists():
            try:
                self._state = json.loads(self._legacy_state_path.read_text())
            except json.JSONDecodeError:
                self._state = {}

        if self._map or self._state:
            logger.info("Migrated legacy mochi map+state → mochi_sync.json")
            self._save()

    def _save(self) -> None:
        """Atomically write map + state as a single JSON file."""
        self._sync_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._sync_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps({"map": self._map, "state": self._state}, indent=2))
        tmp_path.replace(self._sync_path)

    # Keep legacy property for renderer compatibility
    @property
    def map_path(self) -> Path:
        return self._sync_path

    def _ensure_deck(self) -> str:
        """Get or create the target deck."""
        if self._deck_id:
            return self._deck_id

        for deck in self.client.list_decks():
            if deck.get("name") == self.deck_name:
                self._deck_id = deck["id"]
                return self._deck_id

        result = self.client.create_deck(self.deck_name)
        self._deck_id = result["id"]
        return self._deck_id

    @property
    def mochi_map(self) -> dict[str, str]:
        """Expose mapping for renderer."""
        return self._map

    def sync(self, intent: RenderIntent, dry_run: bool = False, progress_callback=None) -> dict:
        """Sync all Cards to Mochi with the given intent.

        1. Ensure all cards have mochi_card_id (create empty cards if needed)
        2. Render each card with the intent
        3. Check content hash, update if changed
        4. Update all cards

        Returns stats: {created, updated, skipped}
        """
        if progress_callback:
            def retry_cb(msg):
                progress_callback("retry", 0, 0, msg)
            self.client.retry_callback = retry_cb
        else:
            self.client.retry_callback = None

        if not dry_run:
            deck_id = self._ensure_deck()
        else:
            deck_id = "dry-run-deck-id"

        all_cards = list(self.cards.all())

        stats = {"created": 0, "updated": 0, "skipped": 0, "deleted": 0}

        # Phase 0: Delete orphaned Mochi cards (local card deleted but Mochi card still exists)
        local_ids = {c.id for c in all_cards}
        orphaned = {cid: mid for cid, mid in self._map.items() if cid not in local_ids}
        if orphaned:
            total_orphaned = len(orphaned)
            for i, (card_id, mochi_id) in enumerate(orphaned.items(), 1):
                if progress_callback:
                    progress_callback("running", i, total_orphaned, f"Deleting orphan {i}/{total_orphaned}...")
                if not dry_run:
                    try:
                        self.client.delete_card(mochi_id)
                    except httpx.HTTPError as e:
                        logger.warning("Failed to delete orphaned Mochi card %s (local: %s): %s", mochi_id, card_id, e)
                    del self._map[card_id]
                    self._state.pop(card_id, None)
                stats["deleted"] += 1

        # Phase 1: Ensure all cards have mochi_card_id
        new_cards = [c for c in all_cards if c.id not in self._map]
        if new_cards:
            total_new = len(new_cards)
            for i, card in enumerate(new_cards, 1):
                if progress_callback:
                    progress_callback("running", i, total_new, f"Creating Mochi placeholders {i}/{total_new}...")
                if not dry_run:
                    result = self.client.create_card(deck_id, "")
                    self._map[card.id] = result["id"]
                stats["created"] += 1

        if not dry_run:
            self._save()

        # Phase 2: Render all cards (fields), find which ones changed
        renderer = CardRenderer(self.cards, self.graph, self._map)

        from .difficulty import get_tier

        to_update: list[tuple[Card, str, dict, list[str] | None]] = []  # (card, content, fields, tags)

        for card in all_cards:
            mochi_id = self._map.get(card.id)
            if not mochi_id:
                continue

            # Render fields & content
            fields = renderer.render_fields(card, intent)
            content = renderer.render(card, intent) # Keep fallback content

            # Build tags using calibrated static thresholds
            tags = None
            if card.difficulty is not None:
                tier = get_tier(card.content)
                tags = [tier.tag]

            # Include tags in hash so tier changes trigger sync
            hash_data = json.dumps({"fields": fields, "tags": tags}, sort_keys=True)
            content_hash = hashlib.md5(hash_data.encode("utf-8")).hexdigest()

            if self._state.get(card.id) == content_hash:
                stats["skipped"] += 1
                continue

            to_update.append((card, content, fields, tags))

        # Phase 3: Update only changed cards (with API calls + progress)
        if to_update:
            total_updates = len(to_update)
            for i, (card, content, fields, tags) in enumerate(to_update, 1):
                if progress_callback:
                    progress_callback("running", i, total_updates, f"Syncing card {i}/{total_updates} to Mochi...")
                mochi_id = self._map[card.id]
                if not dry_run:
                    self.client.update_card(mochi_id, content, tags=tags,
                                          fields=fields, template_id=TEMPLATE_ID)

                    hash_data = json.dumps({"fields": json.loads(json.dumps(fields, sort_keys=True)), "tags": tags}, sort_keys=True)
                    content_hash = hashlib.md5(hash_data.encode("utf-8")).hexdigest()
                    self._state[card.id] = content_hash
                stats["updated"] += 1

        if not dry_run:
            self._save()

        return stats

    def pull_updates(self, dry_run: bool = False) -> dict:
        """Pull updates from Mochi and update local cards."""
        from .parser import MochiParser

        if not self._map:
            return {"updated": 0, "skipped": 0}

        parser = MochiParser()
        stats = {"updated": 0, "skipped": 0}

        # Invert map for efficiency if needed, but we check by local ID
        mochi_to_local = {v: k for k, v in self._map.items()}

        # 1. Fetch all cards from Mochi deck (more efficient than N requests)
        deck_id = self._ensure_deck()
        mochi_cards = {}
        for card in self.client.list_cards(deck_id):
            if card["id"] in mochi_to_local:
                # Store full card object to access fields
                mochi_cards[card["id"]] = card

        # 2. Iterate local cards that are mapped
        from tqdm import tqdm
        iterator = tqdm(mochi_to_local.items(), desc="Pulling from Mochi", unit="card")

        for mochi_id, local_id in iterator:
            remote_card = mochi_cards.get(mochi_id)
            if not remote_card:
                continue

            local_card = self.cards.get(local_id)
            if not local_card:
                continue

            # Parse remote content
            # Try fields first (new system), fallback to content (legacy)
            if remote_card.get("fields"):
                updates = parser.parse_fields(remote_card["fields"])
            else:
                updates = parser.parse(remote_card.get("content", ""), local_card.mode)

            if not updates:
                stats["skipped"] += 1
                continue

            # Check for changes
            changed = False

            # Helper to check change
            def has_changed(key: str) -> bool:  # noqa: B023
                if key not in updates:  # noqa: B023
                    return False
                if getattr(local_card, key) != updates[key]:  # noqa: B023
                    return True
                return False

            if has_changed("content"):
                if not dry_run:
                    local_card.content = updates["content"]
                changed = True

            if has_changed("meaning"):
                if not dry_run:
                    local_card.meaning = updates["meaning"]
                changed = True

            if has_changed("pos"):
                if not dry_run:
                    local_card.pos = updates["pos"]
                changed = True

            if "note" in updates and local_card.note != updates["note"]:
                if not dry_run:
                    local_card.note = updates["note"]
                changed = True

            # Sync lists carefully
            if "collocations" in updates:
                if local_card.collocations != updates["collocations"]:
                    if not dry_run:
                        local_card.collocations = updates["collocations"]
                    changed = True

            # Examples: Only update if present in updates (Recognition only usually)
            if "examples" in updates:
                if local_card.examples != updates["examples"]:
                     if not dry_run:
                         local_card.examples = updates["examples"]
                     changed = True

            if changed:
                stats["updated"] += 1
            else:
                stats["skipped"] += 1

        if not dry_run and stats["updated"] > 0:
            self.cards.save()

        return stats
