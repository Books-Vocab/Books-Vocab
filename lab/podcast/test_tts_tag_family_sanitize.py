# /// script
# requires-python = ">=3.12"
# ///
"""TDD for cross-family audio-tag sanitization (tts_tags.sanitize_tags_for_family).

The scriptwriter palette is authored for Gemini 3.1 (noun-form emotion tags,
energy/pause tags). On a non-3.1 synthesis family (e.g. 2.5-flash) an unsupported
inline tag is NOT silently dropped by the model — it is spoken aloud as literal
text. This guard rewrites 3.1-only tags into 2.5-safe forms (or strips them)
BEFORE the text reaches the TTS API, while leaving non-palette content brackets
(e.g. habit-stacking placeholders like [NEW HABIT]) untouched.
"""

from tts_tags import sanitize_tags_for_family


def test_3_1_family_is_passthrough():
    # On the native family the full palette is valid — nothing is touched.
    src = "I felt [determination] and then [high energy] [long pause] done."
    out, changes = sanitize_tags_for_family(src, "3.1")
    assert out == src
    assert changes == {}


def test_noun_emotion_downgraded_to_25_adjective():
    # [excitement] is a 3.1 noun form; 2.5 wants the adjective [excited].
    out, _ = sanitize_tags_for_family("This is [excitement] real.", "2.5")
    assert "[excited]" in out
    assert "[excitement]" not in out


def test_nonverbal_downgraded_to_25_form():
    # [whispers]/[laughs] -> the 2.5-era gerund forms the pipeline shipped.
    out, _ = sanitize_tags_for_family("[whispers] hi [laughs] ha", "2.5")
    assert "[whispering]" in out and "[chuckling]" not in out
    assert "[laughing]" in out
    assert "[whispers]" not in out and "[laughs]" not in out


def test_energy_tags_stripped():
    # Energy tags are 3.1-only with no 2.5 equivalent -> remove entirely.
    out, _ = sanitize_tags_for_family("Now [high energy] go [low energy] slow.", "2.5")
    assert "[high energy]" not in out and "[low energy]" not in out
    assert "energy" not in out  # must NOT be voiced as the word "energy"
    # surrounding text stays readable (no doubled spaces)
    assert "  " not in out


def test_pause_tags_stripped():
    out, _ = sanitize_tags_for_family("Wait [long pause] for it.", "2.5")
    assert "pause" not in out
    assert "Wait for it." == out


def test_abstract_noun_without_adjective_stripped():
    # [awe]/[yearning] have no 2.5 adjective form -> strip rather than voice them.
    out, _ = sanitize_tags_for_family("Pure [awe] and [yearning] here.", "2.5")
    assert "awe" not in out and "yearning" not in out


def test_unknown_content_bracket_preserved():
    # Habit-stacking placeholder is CONTENT meant to be spoken, not an audio tag.
    src = "After [CURRENT HABIT], I will [NEW HABIT]."
    out, changes = sanitize_tags_for_family(src, "2.5")
    assert out == src
    assert changes == {}


def test_already_25_adjective_preserved():
    # [excited] is already the 2.5-native form -> leave it alone.
    out, changes = sanitize_tags_for_family("So [excited] today.", "2.5")
    assert out == "So [excited] today."
    assert changes == {}


def test_changes_are_reported():
    _, changes = sanitize_tags_for_family(
        "[excitement] [high energy] [long pause]", "2.5"
    )
    # one rewrite + two strips recorded (exact keys are an impl detail; counts matter)
    assert sum(changes.values()) == 3


# ─── concept×family registry (Phase 1) ───

def test_registry_reproduces_legacy_3_1_palette():
    # The 3.1 palette derived from the registry must equal the historical
    # CANONICAL set (46 tags) so nothing silently drops on the migration.
    import tts_tags
    assert tts_tags.palette("3.1") == set(tts_tags.CANONICAL)
    assert len(tts_tags.palette("3.1")) == 46


def test_25_palette_is_the_15_safe_forms():
    import tts_tags
    p = tts_tags.palette("2.5")
    assert p == {
        "excited", "skeptical", "amused", "uncertain", "sad", "surprised",
        "happy", "sarcastic", "empathetic", "whispering", "sighing", "laughing",
        "chuckling", "speaking slowly", "speaking quickly",
    }


def test_form_index_is_collision_free():
    # Every surface form across all families maps to exactly one concept.
    import tts_tags
    seen: dict[str, str] = {}
    for c in tts_tags.TAG_CONCEPTS:
        for fam, form in c.forms.items():
            assert form not in seen or seen[form] == c.id, (
                f"form {form!r} claimed by both {seen.get(form)} and {c.id}"
            )
            seen[form] = c.id


def test_normalization_upgrades_25_form_on_3_1():
    # On 3.1 a 2.5-era form is upgraded to the stronger noun form (not passthrough).
    out, changes = sanitize_tags_for_family("So [excited] today.", "3.1")
    assert out == "So [excitement] today."
    assert sum(changes.values()) == 1


def test_unknown_family_is_passthrough():
    # No registry for the family → cannot know what to strip → leave verbatim
    # (defense-in-depth; prompt injection raises loudly instead, see Phase 2).
    src = "Big [determination] and [high energy] here."
    out, changes = sanitize_tags_for_family(src, "9.9")
    assert out == src and changes == {}


def test_render_palette_md_omits_empty_groups_for_25():
    import tts_tags
    md = tts_tags.render_palette_md("2.5")
    assert "[excited]" in md
    # 2.5 has no energy/pause forms → those groups must not appear with tags
    assert "high energy" not in md and "long pause" not in md
    # 3.1 render includes them
    md31 = tts_tags.render_palette_md("3.1")
    assert "high energy" in md31 and "long pause" in md31


if __name__ == "__main__":
    import sys
    import traceback

    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception:
                failures += 1
                print(f"FAIL {name}")
                traceback.print_exc()
    sys.exit(1 if failures else 0)
