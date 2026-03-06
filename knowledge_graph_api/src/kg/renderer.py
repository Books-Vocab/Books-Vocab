"""Card renderer - converts Card to Mochi markdown based on intent and mode."""

from __future__ import annotations

import re
from enum import Enum

from .cards import Card, CardStore
from .difficulty import TIERS
from .graph import GraphStore, LinkKind, LINK_LABELS


def _difficulty_div(zipf: float | None) -> str:
    """Get a <div> tag for difficulty tier, styled via Mochi CSS Snippet."""
    if zipf is None:
        return ""
    for threshold, tier in TIERS:
        if zipf >= threshold:
            return f'<div class="{tier.css_class}">{tier.tag}</div>'
    last = TIERS[-1][1]
    return f'<div class="{last.css_class}">{last.tag}</div>'


class RenderIntent(str, Enum):
    """Rendering intent controls which fields to display."""

    STANDARD = "standard"    # word + example + meaning + note
    FULL = "full"            # standard + all graph links



# KG Vocab v3 Template IDs
TEMPLATE_ID = "fiAjorZ6"
FIELDS = {
    "word": "name",
    "pos": "pos_field",
    "difficulty": "diff_field",
    "example": "example_field",
    "meaning": "meaning_field",
    "note": "note_field",
    "links": "qzEWEGLk",
}


class CardRenderer:
    """Renders Card to Mochi markdown based on intent and card.mode."""

    def __init__(
        self,
        cards: CardStore,
        graph: GraphStore,
        mochi_map: dict[str, str],
    ) -> None:
        self.cards = cards
        self.graph = graph
        self.mochi_map = mochi_map  # card_id -> mochi_card_id

    def _make_cloze(self, text: str) -> str:
        """Replace **marked** word with blank in text."""
        return re.sub(r"\*\*(.+?)\*\*", "______", text)

    def _truncate_example(self, text: str, radius: int = 5) -> str:
        """Truncate example to keep only radius words around the target word."""
        match = re.search(r"(\*\*.+?\*\*)", text)
        if not match:
            return text

        target = match.group(1)
        start, end = match.span()
        
        before_text = text[:start]
        after_text = text[end:]
        
        # Regex for tokens (non-whitespace)
        # We use this to find offsets but we want to filter what counts as a 'word'
        def get_tokens(s):
            return list(re.finditer(r"\S+", s))
            
        before_tokens = get_tokens(before_text)
        after_tokens = get_tokens(after_text)
        
        prefix = ""
        new_before = before_text
        
        # Filter tokens that should count towards radius (at least one alphanumeric char)
        def is_word(match):
            return any(c.isalnum() for c in match.group())

        # Process BEFORE
        # We need the last 'radius' valid words
        valid_indices_before = [i for i, m in enumerate(before_tokens) if is_word(m)]
        if len(valid_indices_before) > radius:
            # We cut off content.
            # The cut point should be the start of the token at index [-(radius)]
            full_token_index = valid_indices_before[-radius]
            cut_start = before_tokens[full_token_index].start()
            new_before = before_text[cut_start:]
            prefix = "..."
        
        suffix = ""
        new_after = after_text
        
        # Process AFTER
        # We need the first 'radius' valid words
        valid_indices_after = [i for i, m in enumerate(after_tokens) if is_word(m)]
        if len(valid_indices_after) > radius:
            # The cut point should be the end of the token at index [radius-1]
            full_token_index = valid_indices_after[radius-1]
            cut_end = after_tokens[full_token_index].end()
            new_after = after_text[:cut_end]
            suffix = "..."
            
        return f"{prefix}{new_before}{target}{new_after}{suffix}"

    def _format_example(self, text: str, wrap_italics: bool = True) -> str:
        """Format example: truncate -> italic + ==highlight== for marked words."""
        # 1. Truncate first (on raw text with **word**)
        truncated = self._truncate_example(text)
        
        # 2. Highlight
        highlighted = re.sub(r"\*\*(.+?)\*\*", r"==\1==", truncated)
        return f"_{highlighted}_" if wrap_italics else highlighted

    # CSS class per link kind
    _LINK_CSS: dict[LinkKind, str] = {
        LinkKind.CONFUSABLE: "link-confusable",
        LinkKind.CONTRASTS_WITH: "link-contrast",
        LinkKind.SHARES_USAGE: "link-related",
    }

    def _get_links_by_kind(self, card: Card) -> dict[LinkKind, list[tuple[str, str]]]:
        """Get links grouped by kind. Each entry is (word_name, mochi_id)."""
        links = self.graph.get_links_for(card.id)
        result: dict[LinkKind, list[tuple[str, str]]] = {}

        for link in links:
            other_id = link.to_id if link.from_id == card.id else link.from_id
            mochi_id = self.mochi_map.get(other_id, "")

            # Look up the word name
            other_card = self.cards.get(other_id)
            if not other_card:
                continue

            word_name = other_card.content

            if link.kind not in result:
                result[link.kind] = []
            result[link.kind].append((word_name, mochi_id))

        return result

    def _render_links_section(self, links_by_kind: dict[LinkKind, list[tuple[str, str]]]) -> list[str]:
        """Render links as plain markdown (no HTML, template-safe)."""
        parts: list[str] = []
        for kind, entries in links_by_kind.items():
            label = LINK_LABELS.get(kind, kind.value)
            
            link_strs: list[str] = []
            for word_name, mochi_id in entries:
                if mochi_id:
                    link_strs.append(f"[[{mochi_id}]]")
                else:
                    link_strs.append(f"*{word_name}*")
            
            if link_strs:
                parts.append(f"{label}：{'、'.join(link_strs)}")

        if parts:
            # Use ｜ to separate different kinds of links
            return [f"📎 {'｜'.join(parts)}"]
        return []

    def render(self, card: Card, intent: RenderIntent) -> str:
        """Render a card to Mochi markdown based on intent and card.mode."""
        if card.mode == "production":
            return self._render_production(card, intent)
        else:
            return self._render_recognition(card, intent)

    def _render_recognition(self, card: Card, intent: RenderIntent) -> str:
        """Render recognition card (word -> meaning)."""
        front_lines: list[str] = []
        back_lines: list[str] = []

        # === FRONT ===
        # Difficulty float-right div (must come before word for CSS float)
        diff_div = _difficulty_div(card.difficulty)
        if diff_div:
            front_lines.append(diff_div)
            front_lines.append("")  # blank line for markdown parsing

        pos_str = f" {card.pos}" if card.pos else ""
        front_lines.append(f'<div class="word">{card.content}{pos_str}</div>')

        if card.examples:
            front_lines.append("")
            front_lines.append(f'<div class="example">{self._format_example(card.examples[0])}</div>')

        # === BACK ===
        back_lines.append(f'<div class="meaning">{card.meaning}</div>')

        if card.note:
            back_lines.append("")
            back_lines.append('<div class="note">')
            back_lines.append("")
            back_lines.append(card.note)
            back_lines.append("")
            back_lines.append("</div>")

        # Links as separate div (full only)
        if intent == RenderIntent.FULL:
            links_by_kind = self._get_links_by_kind(card)
            if links_by_kind:
                link_text = self._render_links_section(links_by_kind)
                back_lines.append("")
                back_lines.append('<div class="links">')
                back_lines.append("")
                back_lines.extend(link_text)
                back_lines.append("")
                back_lines.append("</div>")

        front = "\n".join(front_lines)
        back = "\n".join(back_lines)
        return f"{front}\n---\n{back}"

    def _render_production(self, card: Card, intent: RenderIntent) -> str:
        """Render production card (meaning -> word, cloze example)."""
        front_lines: list[str] = []
        back_lines: list[str] = []

        # === FRONT ===
        front_lines.append(f'<div class="meaning">{card.meaning}</div>')

        if card.examples:
            # For production cloze, we also might want truncation?
            # User request didn't specify, but usually cloze also benefits from context focus.
            # But cloze replaces the word with blanks. 
            # Let's stick to recognition/standard view for now as per "example" field request.
            # If I change _format_example, it affects front of recognition card.
            # But _make_cloze is manual.
            
            # Let's apply truncation to cloze too for consistency?
            # The user request showed "Siri had heard...", which is a recognition example.
            
            # Use raw example for cloze generation to ensure we find **word**
            # transform to cloze then truncate? No, truncate uses **word**.
            
            truncated = self._truncate_example(card.examples[0])
            cloze = self._make_cloze(truncated)
            front_lines.append("")
            front_lines.append(f'<div class="example">_{cloze}_</div>')

        # === BACK ===
        diff_div = _difficulty_div(card.difficulty)
        if diff_div:
            back_lines.append(diff_div)
            back_lines.append("")

        pos_str = f" {card.pos}" if card.pos else ""
        back_lines.append(f'<div class="word">{card.content}{pos_str}</div>')

        if card.note:
            back_lines.append("")
            back_lines.append('<div class="note">')
            back_lines.append("")
            back_lines.append(card.note)
            back_lines.append("")
            back_lines.append("</div>")

        # Links as separate div (full only)
        if intent == RenderIntent.FULL:
            links_by_kind = self._get_links_by_kind(card)
            if links_by_kind:
                link_text = self._render_links_section(links_by_kind)
                back_lines.append("")
                back_lines.append('<div class="links">')
                back_lines.append("")
                back_lines.extend(link_text)
                back_lines.append("")
                back_lines.append("</div>")

        front = "\n".join(front_lines)
        back = "\n".join(back_lines)
        return f"{front}\n---\n{back}"
        return f"{front}\n---\n{back}"

    def render_fields(self, card: Card, intent: RenderIntent, thresholds: list[float] | None = None) -> dict:
        """Render card fields for KG Vocab v3 template."""
        from .difficulty import get_tier

        # content for legacy/search
        content = self.render(card, intent)

        fields = {
            FIELDS["word"]: {"id": FIELDS["word"], "value": card.content},
            FIELDS["meaning"]: {"id": FIELDS["meaning"], "value": card.meaning},
        }

        if card.pos:
            fields[FIELDS["pos"]] = {"id": FIELDS["pos"], "value": card.pos}
        
        if card.difficulty is not None:
             tier = get_tier(card.content)
             fields[FIELDS["difficulty"]] = {"id": FIELDS["difficulty"], "value": tier.tag}

        if card.examples:
            # Example with highlighting (not cloze)
            # Template already adds italics (_..._), so we don't wrap here to avoid bold (__...__)
            example = self._format_example(card.examples[0], wrap_italics=False)
            fields[FIELDS["example"]] = {"id": FIELDS["example"], "value": example}
        
        if card.note:
            fields[FIELDS["note"]] = {"id": FIELDS["note"], "value": card.note}
            
        if intent == RenderIntent.FULL:
            links_by_kind = self._get_links_by_kind(card)
            if links_by_kind:
                link_text = self._render_links_section(links_by_kind)
                if link_text:
                    fields[FIELDS["links"]] = {"id": FIELDS["links"], "value": link_text[0]}

        return fields
