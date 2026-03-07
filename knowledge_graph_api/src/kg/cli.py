"""CLI interface for Knowledge Graph."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from openai import OpenAI
from tqdm import tqdm

from .api import load_users
from .cards import CardStore
from .embeddings import EmbeddingStore
from .graph import GraphStore, LinkKind
from .judge import Judge
from .mochi import MochiClient, MochiSync
from .renderer import RenderIntent, CardRenderer

load_dotenv()

app = typer.Typer(help="Knowledge Graph for Vocabulary Recall")

# Default data directory
DATA_DIR = Path(os.getenv("KG_DATA_DIR", "./data"))


@app.callback()
def main(
    ctx: typer.Context,
    user: str = typer.Option(
        None,
        "--user",
        "-u",
        help="Apple User ID to operate on. Defaults to DEFAULT_USER_ID from env."
    ),
):
    """Knowledge Graph Multi-User API and Tools"""
    user_id = user or os.getenv("DEFAULT_USER_ID")
    if not user_id:
        raise typer.Exit("No user specified. Use --user or define DEFAULT_USER_ID in .env")
        
    user_dir = DATA_DIR / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    
    ctx.obj = {
        "user_id": user_id,
        "user_dir": user_dir
    }


def get_card_store(user_dir: Path) -> CardStore:
    return CardStore(user_dir / "cards.json")


def get_graph_store(user_dir: Path) -> GraphStore:
    return GraphStore(user_dir / "graph.json", user_dir / "candidates.json")


def get_embedding_store(user_dir: Path) -> EmbeddingStore:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise typer.Exit("GEMINI_API_KEY not set")
    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    return EmbeddingStore(user_dir / "embeddings.npy", user_dir / "card_ids.json", client)


@app.command()
def add(
    ctx: typer.Context,
    content: str = typer.Argument(..., help="Word or phrase"),
    meaning: str = typer.Argument(..., help="Definition"),
    pos: str = typer.Option(None, "--pos", "-p", help="Part of speech [v.] [n.] [adj.]"),
    examples: list[str] = typer.Option([], "--example", "-e", help="Usage examples"),
    collocations: list[str] = typer.Option([], "--collocation", "-c", help="Common collocations"),
) -> None:
    """Add a new card."""
    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    graph = get_graph_store(user_dir)
    embeddings = get_embedding_store(user_dir)

    # Create card
    card = cards.add(content, meaning, pos=pos, examples=examples, collocations=collocations)
    typer.echo(f"Created card: {card.id} ({card.content})")

    # Add embedding
    embeddings.add(card.id, card.embed_text())
    typer.echo("Embedding stored")

    # Find candidates
    similar = embeddings.find_similar(card.id, k=3)
    if similar:
        typer.echo(f"Found {len(similar)} similar cards:")
        for other_id, score in similar:
            other = cards.get(other_id)
            if other and score > 0.655:  # threshold
                graph.add_candidate(card.id, other_id, score)
                typer.echo(f"  - {other.content} (similarity: {score:.2f}) -> queued")

    pending = graph.candidate_count()
    if pending:
        typer.echo(f"\nRun 'kg link' to process {pending} pending candidates")


@app.command()
def link(ctx: typer.Context) -> None:
    """Process pending candidates via LLM."""
    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    graph = get_graph_store(user_dir)

    candidates = graph.pop_candidates()
    if not candidates:
        typer.echo("No pending candidates")
        return

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise typer.Exit("GEMINI_API_KEY not set")

    judge = Judge(OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    ))
    created = 0

    try:
        i = 0
        for i, candidate in enumerate(tqdm(candidates, desc="Processing")):
            card_a = cards.get(candidate.from_id)
            card_b = cards.get(candidate.to_id)
            if not card_a or not card_b:
                continue

            result = judge.evaluate(
                card_a.content,
                card_a.meaning,
                card_b.content,
                card_b.meaning,
            )

            if result:
                graph.add_link(
                    candidate.from_id,
                    candidate.to_id,
                    LinkKind(result.link),
                    result.confidence,
                    result.reason,
                )
                tqdm.write(
                    f"  {card_a.content} <-> {card_b.content}: "
                    f"{result.link.upper()} ({result.confidence:.2f})"
                )
                created += 1
    except Exception as e:
        graph.requeue_candidates(candidates[i:])
        raise e

    typer.echo(f"\nCreated {created} links")


@app.command()
def difficulty(ctx: typer.Context) -> None:
    """Score all cards by word frequency (Zipf) using absolute thresholds."""
    from .difficulty import get_zipf, get_tier, TIERS

    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    all_cards = list(cards.all())

    tier_counts: dict[str, int] = {}
    scored = 0

    for card in tqdm(all_cards, desc="Scoring"):
        z = get_zipf(card.content)
        card.difficulty = round(z, 2)
        tier = get_tier(card.content)
        tier_counts[tier.tag] = tier_counts.get(tier.tag, 0) + 1
        scored += 1

    cards.save()

    typer.echo(f"\nScored {scored} cards using static thresholds:")
    for _, tier in TIERS:
        count = tier_counts.get(tier.tag, 0)
        typer.echo(f"  {tier.label} ({tier.tag}): {count}")


@app.command()
def enrich(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without writing"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-enrich all cards, not just empty ones"),
    workers: int = typer.Option(5, "--workers", "-w", help="Max concurrent API calls"),
) -> None:
    """Enrich cards via LLM (POS + teacher note). Runs concurrently."""
    from .enrich import enrich_cards_concurrent

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise typer.Exit("GEMINI_API_KEY not set")

    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    all_cards = list(cards.all())

    if force:
        targets = all_cards
    else:
        targets = [c for c in all_cards if not c.pos or not c.note]

    if not targets:
        typer.echo("All cards already enriched")
        return

    typer.echo(f"Enriching {len(targets)}/{len(all_cards)} cards ({workers} workers)...")

    client = OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    results, errors = enrich_cards_concurrent(client, targets, batch_size=20, max_workers=workers)

    for err in errors:
        typer.echo(f"  ⚠ {err}", err=True)

    result_map = {r["word"].lower(): r for r in results}
    updated = 0

    for card in targets:
        enrichment = result_map.get(card.content.lower())
        if not enrichment:
            continue

        changed = False

        if enrichment.get("pos") and (not card.pos or force):
            if not dry_run:
                card.pos = enrichment["pos"]
            changed = True

        if enrichment.get("note") and (not card.note or force):
            if not dry_run:
                card.note = enrichment["note"]
            changed = True

        if changed:
            updated += 1
            if dry_run:
                tqdm.write(f"  {card.content} ({enrichment.get('pos')}): {enrichment.get('note')}")

    if not dry_run and updated:
        cards.save()

    typer.echo(f"\n{'Would update' if dry_run else 'Updated'} {updated} cards")


@app.command("list")
def list_cards(ctx: typer.Context) -> None:
    """List all cards."""
    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)

    for card in cards.all():
        pos_str = f" [{card.pos}]" if card.pos else ""
        typer.echo(f"{card.id}  {card.content}{pos_str}: {card.meaning}")

    typer.echo(f"\nTotal: {cards.count()} cards")


@app.command()
def graph(ctx: typer.Context) -> None:
    """Show graph statistics."""
    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    graph_store = get_graph_store(user_dir)

    typer.echo(f"Cards: {cards.count()}")
    typer.echo(f"Links: {graph_store.link_count()}")
    typer.echo(f"Pending candidates: {graph_store.candidate_count()}")

    # Show links by kind
    from collections import Counter

    kinds = Counter(lk.kind for lk in graph_store.all_links() if lk.status == "active")
    if kinds:
        typer.echo("\nLinks by type:")
        for kind, count in kinds.items():
            typer.echo(f"  {kind.value}: {count}")


@app.command()
def preview(
    ctx: typer.Context,
    intent: str = typer.Argument(..., help="Render intent: standard, full"),
) -> None:
    """Preview rendered cards for an intent."""
    try:
        render_intent = RenderIntent(intent)
    except ValueError:
        typer.echo(f"Invalid intent. Choose from: {[i.value for i in RenderIntent]}")
        raise typer.Exit(1)

    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    graph_store = get_graph_store(user_dir)

    # Use empty mochi_map for preview (no links will resolve)
    renderer = CardRenderer(cards, graph_store, {})

    for card in cards.all():
        typer.echo(f"\n{'='*40}")
        typer.echo(f"Card: {card.id}")
        typer.echo(renderer.render(card, render_intent))

    typer.echo(f"\n{'='*40}")
    typer.echo(f"Total: {cards.count()} cards")


@app.command()
def sync(
    ctx: typer.Context,
    intent: str = typer.Argument(..., help="Render intent: standard, full"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview sync actions"),
    pull: bool = typer.Option(False, "--pull", "-p", help="Pull changes from Mochi to local"),
) -> None:
    """Sync cards with Mochi (default: push to Mochi)."""
    try:
        render_intent = RenderIntent(intent)
    except ValueError:
        typer.echo(f"Invalid intent. Choose from: {[i.value for i in RenderIntent]}")
        raise typer.Exit(1)

    user_id = ctx.obj["user_id"]
    user_dir = ctx.obj["user_dir"]
    users = load_users()
    mochi_key = users.get(user_id, {}).get("config", {}).get("mochi_api_key")
    
    if not mochi_key:
        raise typer.Exit(f"MOCHI_API_KEY not configured for user {user_id}. Set it in users.json")

    cards = get_card_store(user_dir)
    graph_store = get_graph_store(user_dir)

    if cards.count() == 0:
        typer.echo("No cards to sync")
        return

    client = MochiClient(mochi_key)
    syncer = MochiSync(
        client,
        cards,
        graph_store,
        map_path=user_dir / "mochi_map.json",
    )

    if pull:
        typer.echo(f"Pulling updates from Mochi...{' [DRY RUN]' if dry_run else ''}")
        stats = syncer.pull_updates(dry_run=dry_run)
        typer.echo(
            f"Done: {stats['updated']} updated, "
            f"{stats['skipped']} skipped"
        )
    else:
        typer.echo(f"Syncing {cards.count()} cards to Mochi ({intent} intent)...{' [DRY RUN]' if dry_run else ''}")
        stats = syncer.sync(render_intent, dry_run=dry_run)

        typer.echo(
            f"Done: {stats['created']} created, "
            f"{stats['updated']} updated, "
            f"{stats['skipped']} skipped"
        )


@app.command("import")
def import_csv(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="CSV file to import"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without writing"),
) -> None:
    """Import cards from CSV file."""
    if not file.exists():
        typer.echo(f"File not found: {file}")
        raise typer.Exit(1)

    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    existing_contents = {c.content.lower() for c in cards.all()}

    # Parse CSV
    rows: list[dict] = []
    with open(file, encoding="utf-8-sig") as f:  # utf-8-sig handles BOM
        reader = csv.DictReader(f)
        for row in reader:
            content = row.get("content", "").strip()
            meaning = row.get("meaning", "").strip()
            if not content or not meaning:
                continue
            rows.append(row)

    # Check duplicates
    to_import = []
    skipped = 0
    for row in rows:
        if row["content"].strip().lower() in existing_contents:
            skipped += 1
        else:
            to_import.append(row)

    typer.echo(f"Found {len(rows)} rows, {len(to_import)} new, {skipped} duplicates")

    if dry_run:
        typer.echo("\n[Dry run] Would import:")
        for row in to_import[:10]:
            typer.echo(f"  - {row['content'].strip()}: {row['meaning'].strip()[:30]}...")
        if len(to_import) > 10:
            typer.echo(f"  ... and {len(to_import) - 10} more")
        return

    if not to_import:
        typer.echo("Nothing to import")
        return

    # Import cards
    embeddings = get_embedding_store(user_dir)
    graph = get_graph_store(user_dir)
    created_cards = []

    for row in tqdm(to_import, desc="Importing"):
        content = row["content"].strip()
        meaning = row["meaning"].strip()
        pos = row.get("pos", "").strip() or None
        examples = [e.strip() for e in row.get("examples", "").split("|") if e.strip()]
        collocations = [c.strip() for c in row.get("collocations", "").split("|") if c.strip()]
        mode = row.get("mode", "").strip() or "recognition"

        card = cards.add(content, meaning, pos=pos, examples=examples, collocations=collocations, mode=mode)
        created_cards.append(card)

    typer.echo(f"\nCreated {len(created_cards)} cards")

    # Batch embeddings
    typer.echo("Generating embeddings...")
    for card in tqdm(created_cards, desc="Embedding"):
        embeddings.add(card.id, card.embed_text())

    # Find candidates
    typer.echo("Finding candidates...")
    candidate_count = 0
    for card in tqdm(created_cards, desc="Finding candidates"):
        similar = embeddings.find_similar(card.id, k=3)
        for other_id, score in similar:
            if score > 0.655:
                graph.add_candidate(card.id, other_id, score)
                candidate_count += 1

    typer.echo(f"Queued {candidate_count} candidates")
    pending = graph.candidate_count()
    if pending:
        typer.echo(f"\nRun 'kg link' to process {pending} pending candidates")


@app.command("import-readlang")
def import_readlang(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="Readlang exported TSV/TXT file"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Preview without writing"),
) -> None:
    """Import cards from a Readlang export file (TSV)."""
    from .readlang import parse_readlang_tsv

    if not file.exists():
        typer.echo(f"File not found: {file}")
        raise typer.Exit(1)

    rows = parse_readlang_tsv(file)
    if not rows:
        typer.echo("No valid rows found in file")
        return

    user_dir = ctx.obj["user_dir"]
    cards = get_card_store(user_dir)
    existing_contents = {c.content.lower() for c in cards.all()}

    to_import = [r for r in rows if r["content"].strip().lower() not in existing_contents]
    skipped = len(rows) - len(to_import)

    typer.echo(f"Found {len(rows)} words, {len(to_import)} new, {skipped} duplicates")

    if dry_run:
        typer.echo("\n[Dry run] Would import:")
        for row in to_import[:10]:
            meaning_preview = row['meaning'][:30] + '...' if len(row['meaning']) > 30 else row['meaning']
            typer.echo(f"  - {row['content']}: {meaning_preview}")
            if row.get("examples"):
                typer.echo(f"    ex: {row['examples'][0][:60]}...")
        if len(to_import) > 10:
            typer.echo(f"  ... and {len(to_import) - 10} more")
        return

    if not to_import:
        typer.echo("Nothing to import")
        return

    embeddings = get_embedding_store(user_dir)
    graph = get_graph_store(user_dir)
    created_cards = []

    for row in tqdm(to_import, desc="Importing"):
        card = cards.add(
            content=row["content"],
            meaning=row["meaning"],
            pos=row.get("pos"),
            examples=row.get("examples", []),
            collocations=row.get("collocations", []),
            mode=row.get("mode", "recognition"),
        )
        created_cards.append(card)

    typer.echo(f"\nCreated {len(created_cards)} cards")

    typer.echo("Generating embeddings...")
    for card in tqdm(created_cards, desc="Embedding"):
        embeddings.add(card.id, card.embed_text())

    typer.echo("Finding candidates...")
    candidate_count = 0
    for card in tqdm(created_cards, desc="Finding candidates"):
        similar = embeddings.find_similar(card.id, k=3)
        for other_id, score in similar:
            if score > 0.655:
                graph.add_candidate(card.id, other_id, score)
                candidate_count += 1

    typer.echo(f"Queued {candidate_count} candidates")
    pending = graph.candidate_count()
    if pending:
        typer.echo(f"\nRun 'kg link' to process {pending} pending candidates")


@app.command("auto")
def auto_pipeline(
    ctx: typer.Context,
    file: Path = typer.Argument(..., help="Readlang exported TSV/TXT file to process"),
) -> None:
    """Run the complete automated pipeline: import -> enrich -> link -> difficulty -> sync."""
    user = ctx.obj["user_id"]
    typer.secho(f"🚀 Starting automated pipeline for {file} (User: {user})", fg=typer.colors.GREEN, bold=True)
    
    user_args = ["--user", user]
    
    typer.secho("\n--- [1/5] Import ---", fg=typer.colors.CYAN, bold=True)
    import_readlang(ctx, file, dry_run=False)
    
    typer.secho("\n--- [2/5] Enrich (LLM) ---", fg=typer.colors.CYAN, bold=True)
    enrich(ctx, dry_run=False, force=False, workers=5)
    
    typer.secho("\n--- [3/5] Link (LLM) ---", fg=typer.colors.CYAN, bold=True)
    link(ctx)
    
    typer.secho("\n--- [4/5] Difficulty (Zipf) ---", fg=typer.colors.CYAN, bold=True)
    difficulty(ctx)
    
    typer.secho("\n--- [5/5] Sync (Mochi) ---", fg=typer.colors.CYAN, bold=True)
    sync(ctx, "full", dry_run=False, pull=False)
    
    typer.secho("\n✅ Pipeline completed successfully!", fg=typer.colors.GREEN, bold=True)


if __name__ == "__main__":
    app()
