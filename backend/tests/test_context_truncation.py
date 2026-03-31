def test_context_around_word_centers_on_word():
    from kg.translate_service import _context_around_word
    ctx = "A" * 200 + " hello " + "B" * 200
    result = _context_around_word(ctx, "hello", max_len=100)
    assert "hello" in result
    assert len(result) <= 100

def test_context_around_word_short_passthrough():
    from kg.translate_service import _context_around_word
    assert _context_around_word("short context", "short") == "short context"

def test_context_around_word_missing_word():
    from kg.translate_service import _context_around_word
    result = _context_around_word("A" * 500, "missing", max_len=100)
    assert len(result) <= 100
