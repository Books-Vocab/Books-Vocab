
"""Parser for Mochi markdown content."""

from __future__ import annotations

import re
from typing import Any

from .cards import CardMode
from .renderer import FIELDS


class MochiParser:
    """Parses Mochi markdown back to Card fields."""

    def parse(self, content: str, mode: CardMode) -> dict[str, Any]:
        """Parse markdown content into a dictionary of fields."""
        if mode == "production":
            return self._parse_production(content)
        else:
            return self._parse_recognition(content)

    def parse_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Parse Mochi fields dictionary into Card attributes."""
        # FIELDS mapping:
        # "word": "name"
        # "pos": "pos_field"
        # "difficulty": "diff_field"
        # "example": "example_field"
        # "meaning": "meaning_field"
        # "note": "note_field"

        data: dict[str, Any] = {}

        def get_val(key_alias: str) -> str | None:
            field_id = FIELDS.get(key_alias)
            if not field_id:
                return None
            field_obj = fields.get(field_id)
            if not field_obj:
                return None
            return field_obj.get("value")

        # Word
        word = get_val("word")
        if word:
            data["content"] = word

        # Meaning
        meaning = get_val("meaning")
        if meaning:
            data["meaning"] = meaning

        # POS
        pos = get_val("pos")
        if pos:
            data["pos"] = pos

        # Note
        note = get_val("note")
        if note:
            data["note"] = note

        # Example
        example = get_val("example")
        if example:
            # Convert `==text==` (Mochi highlight) back to `**text**` (Card bold/cloze)
            fixed_example = re.sub(r"==(.+?)==", r"**\1**", example)

            # Strip outer wrapper if present (legacy artifacts)
            if fixed_example.startswith("_") and fixed_example.endswith("_"):
                fixed_example = fixed_example[1:-1]

            data["examples"] = [fixed_example]

        return data

    def _parse_recognition(self, content: str) -> dict[str, Any]:
        """Parse recognition card (Front: Word, Back: Meaning)."""
        data: dict[str, Any] = {}

        parts = content.split("\n---\n", 1)
        if len(parts) != 2:
            return {}

        front, back = parts

        # === FRONT ===
        front_lines = front.strip().split("\n")
        if not front_lines:
            return {}

        # Line 1: **word** [pos]
        # Regex: **word** or **word** [pos]
        m = re.match(r"\*\*(?P<content>.+?)\*\*(?: (?P<pos>\[.+?\]))?", front_lines[0])
        if m:
            data["content"] = m.group("content").strip()
            if m.group("pos"):
                data["pos"] = m.group("pos").strip("[]")

        # Example (lines starting with >)
        # We only take the first one as primary example
        for line in front_lines[1:]:
            if line.startswith("> "):
                data["examples"] = [line[2:].strip()]
                break

        # === BACK ===
        back_lines = back.strip().split("\n")
        if back_lines:
            # Meaning is the first line
            data["meaning"] = back_lines[0].strip()

            # Collocations (look for lines containing `...`)
            # But exclude lines that are links (contain [[...]])?
            # Actually our format for collocations is usually: `col1` `col2`
            # or **搭配** `col1` `col2`
            colls = []
            for line in back_lines:
                # heuristic: if line has backticks and not [[ (links)
                if "`" in line and "[[" not in line:
                    matches = re.findall(r"`(.+?)`", line)
                    colls.extend(matches)

            if colls:
                data["collocations"] = colls

        return data

    def _parse_production(self, content: str) -> dict[str, Any]:
        """Parse production card (Front: Meaning, Back: Word)."""
        data: dict[str, Any] = {}

        parts = content.split("\n---\n", 1)
        if len(parts) != 2:
            return {}

        front, back = parts

        # === FRONT ===
        # *Meaning*
        front_lines = front.strip().split("\n")
        if front_lines:
            # We wrapped meaning in *...*
            m = re.match(r"\*(?P<meaning>.+?)\*", front_lines[0])
            if m:
                data["meaning"] = m.group("meaning").strip()
            else:
                # fallback if user removed italics
                data["meaning"] = front_lines[0].strip()

        # === BACK ===
        # **Word** [pos]
        back_lines = back.strip().split("\n")
        if back_lines:
            m = re.match(r"\*\*(?P<content>.+?)\*\*(?: (?P<pos>\[.+?\]))?", back_lines[0])
            if m:
                data["content"] = m.group("content").strip()
                if m.group("pos"):
                    data["pos"] = m.group("pos").strip("[]")

            colls = []
            for line in back_lines:
                if "`" in line and "[[" not in line:
                    matches = re.findall(r"`(.+?)`", line)
                    colls.extend(matches)

            if colls:
                data["collocations"] = colls

        # Note: We do NOT parse examples from production cards because they are clozes.
        # We cannot recover the original text easily.

        return data
