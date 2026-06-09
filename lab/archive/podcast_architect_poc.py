#!/usr/bin/env python3
"""Podcast Architect PoC — Book → Production Plan via claude-code-gateway."""

import json
import os
import sys
import time
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub
from openai import OpenAI

# --- Config ---
# NOTE: archived — superseded by lab/podcast/pipeline.py. Kept for history.
# The previously hardcoded gateway token leaked via git history MUST be
# rotated; reading from env now so this file can't re-leak.
PUBLIC_WEB_BASE_URL = "https://wordnexus.lol"
GATEWAY_URL = PUBLIC_WEB_BASE_URL + "/claude/v1"
GATEWAY_TOKEN = os.environ["CCG_API_TOKEN"]
MODEL = "opus"

SYSTEM_PROMPT = """\
You are a Podcast Architect. You receive a complete book and output a Production Plan as markdown.

## Your Job

Read the entire book. Produce a structured Production Plan that a downstream Scriptwriter agent can use to generate episode scripts in parallel.

## Judgment Process

1. **Classify** the book: genre, narrative structure (linear/nonlinear/modular/cumulative), information density (low/medium/high)
2. **Decide compression ratio & episode count** using these guidelines:
   - Fiction epic: 8:1–12:1, 30-45 min/ep, 10-15 eps per 100K chars
   - Fiction mystery: 6:1–8:1, 20-30 min/ep, 8-12 eps
   - Fiction literary/romance: 5:1–8:1, 25-35 min/ep, 8-10 eps
   - Nonfiction self-help: 2:1–4:1, 15-25 min/ep, 5-8 eps
   - Nonfiction business: 3:1–5:1, 15-20 min/ep, 4-6 eps
   - Nonfiction science: 3:1–5:1, 20-30 min/ep, 5-8 eps
   - Biography: 5:1–8:1, 25-35 min/ep, 6-10 eps
   - Technical: 2:1–3:1, 15-20 min/ep, by chapter
   - Speech rate: ~150 words/min English, ~200 chars/min Chinese
   - Sweet spot: 20-30 min/episode (best completion rate)
3. **Choose split points** based on story arcs (fiction) or concept boundaries (nonfiction). Each episode ending must have a hook.
4. **Design inter-episode continuity**: hook chains (closing.hook_to_next → next opening.hook_from_prev), theme arcs, terminology consistency.
5. **Generate scriptwriter instructions** per episode: exact source ranges, exclusion lists, previous episode context, style notes.

## Output Format

Output a well-structured markdown document. Do NOT output JSON. Use the following structure:

# [Series Title]
> [Subtitle]

## Series Info
- Book type: ...
- Language: ...
- Total episodes: ...
- Estimated total duration: ... min
- Tone: ...

### Hosts
- **Host A** ([role]): [personality]. Voice: [voice_id]
- **Host B** ([role]): [personality]. Voice: [voice_id]

## Analysis
- Information density: low/medium/high
- Compression ratio: ... (rationale: ...)
- Narrative structure: ...
- Key themes: ...
- Audience assumption: ...

## Episode 1: [Title]
- Source: [chapters]
- Strategy: full_text / key_passages / summary_plus_quotes
- Duration: ... min
- Core thesis: ...

### Key Points
1. ...

### Must Quote
> "quote" — source

### Opening
- Strategy: cold_open / recap_hook / question / anecdote
- Hook from prev: ...
- Description: ...

### Pacing
| Segment | Treatment | Notes |
|---------|-----------|-------|
| ... | deep_dive/overview/storytelling/debate/rapid_fire | ... |

### Closing
- Hook to next: ...
- Takeaway: ...

### Scriptwriter Instructions
- Read range: ...
- Do not cover: ...
- Style override: ...
- Context from prev: ...

(repeat for each episode)
"""


def extract_book(epub_path: str, max_chapters: int | None = None) -> tuple[dict, str]:
    """Extract metadata + full text with chapter markers from EPUB."""
    book = epub.read_epub(epub_path)

    title = book.get_metadata("DC", "title")[0][0]
    author = book.get_metadata("DC", "creator")[0][0]
    lang = book.get_metadata("DC", "language")[0][0]

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if len(text) > 100:
            chapters.append(text)

    if max_chapters:
        chapters = chapters[:max_chapters]

    full_text = ""
    for i, ch_text in enumerate(chapters):
        full_text += f"\n\n--- Chapter {i + 1} ---\n\n{ch_text}"

    metadata = {
        "title": title,
        "author": author,
        "language": lang,
        "total_chars": len(full_text),
        "chapter_count": len(chapters),
    }
    return metadata, full_text.strip()


def run_architect(metadata: dict, book_text: str) -> dict:
    """Send book to gateway, get Production Plan."""
    client = OpenAI(base_url=GATEWAY_URL, api_key=GATEWAY_TOKEN)

    user_msg = f"""## Book Metadata
{json.dumps(metadata, ensure_ascii=False, indent=2)}

## Full Book Text

{book_text}"""

    print(f"Sending to gateway ({MODEL}), streaming...")
    print(f"  Input size: {len(user_msg):,} chars")
    sys.stdout.flush()
    t0 = time.time()

    stream = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        stream=True,
    )

    raw = ""
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            raw += delta
            sys.stdout.write(delta)
            sys.stdout.flush()

    elapsed = time.time() - t0
    print(f"\n\n  Done in {elapsed:.1f}s, {len(raw):,} chars")
    return raw


def main():
    epub_path = sys.argv[1] if len(sys.argv) > 1 else None
    max_chapters = int(sys.argv[2]) if len(sys.argv) > 2 else None
    if not epub_path:
        print("Usage: python podcast_architect_poc.py <path-to-epub> [max_chapters]")
        sys.exit(1)

    print(f"=== Podcast Architect PoC ===")
    print(f"Book: {epub_path}")

    metadata, book_text = extract_book(epub_path, max_chapters=max_chapters)
    print(f"Title: {metadata['title']}")
    print(f"Author: {metadata['author']}")
    print(f"Language: {metadata['language']}")
    print(f"Chapters: {metadata['chapter_count']}")
    print(f"Total chars: {metadata['total_chars']:,}")
    print()

    raw = run_architect(metadata, book_text)

    # Save as markdown
    stem = Path(epub_path).stem.split("(")[0].strip()
    out_dir = Path(__file__).parent / "podcast_plans"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{stem}_plan.md"
    with open(out_file, "w") as f:
        f.write(raw)
    print(f"\nPlan saved to: {out_file}")


if __name__ == "__main__":
    main()
