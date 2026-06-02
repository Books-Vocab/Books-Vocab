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
