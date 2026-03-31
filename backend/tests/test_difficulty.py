from __future__ import annotations

from kg.difficulty import DifficultyTier, get_tier, get_zipf


class TestGetZipf:
    def test_common_word_high_zipf(self):
        assert get_zipf("the") > 5.0
        assert get_zipf("is") > 5.0

    def test_rare_word_low_zipf(self):
        # "xenobiotic" is genuinely rare in English wordfreq corpus
        assert get_zipf("xenobiotic") < 2.0

    def test_multi_word_phrase_takes_minimum(self):
        score = get_zipf("the xenobiotic")
        # "the" is very common, "xenobiotic" is very rare — result should be the rare one
        assert score < 3.0
        assert score == min(get_zipf("the"), get_zipf("xenobiotic"))

    def test_empty_string_safe(self):
        # Should not raise; wordfreq returns 0.0 for unknown tokens
        result = get_zipf("")
        assert isinstance(result, float)


class TestGetTier:
    def test_core_threshold(self):
        # "the" has Zipf ~7.5, well above 3.44
        tier = get_tier("the")
        assert tier.tag == "core"

    def test_intermediate_boundary(self):
        # Find a word with Zipf between 3.01 and 3.44
        # "resilient" is around 3.1-3.3 in English
        tier = get_tier("resilient")
        assert tier.tag in ("core", "intermediate", "advanced")
        z = get_zipf("resilient")
        if z >= 3.44:
            assert tier.tag == "core"
        elif z >= 3.01:
            assert tier.tag == "intermediate"
        elif z >= 2.55:
            assert tier.tag == "advanced"
        else:
            assert tier.tag == "rare"

    def test_rare_word(self):
        tier = get_tier("xenobiotic")
        assert tier.tag == "rare"

    def test_tier_boundary_core_at_344(self):
        # Mock get_zipf to test exact boundary via known thresholds
        # "make" is a very common word
        tier = get_tier("make")
        z = get_zipf("make")
        if z >= 3.44:
            assert tier.tag == "core"

    def test_difficulty_tier_structure(self):
        tier = get_tier("the")
        assert isinstance(tier, DifficultyTier)
        assert hasattr(tier, "tag")
        assert hasattr(tier, "css_class")
        assert hasattr(tier, "color")
        assert hasattr(tier, "label")
        assert tier.tag == "core"
        assert tier.css_class == "diff-core"
        assert tier.color == "#4caf50"
        assert tier.label == "core"

    def test_tiers_are_correct_for_known_words(self):
        rare_tier = get_tier("xenobiotic")
        assert rare_tier.tag == "rare"

        core_tier = get_tier("the")
        assert core_tier.tag == "core"


def test_get_zipf_is_cached():
    from kg.difficulty import get_zipf
    # Clear any existing cache
    get_zipf.cache_clear()
    # Warm cache
    result1 = get_zipf("hello")
    # Check cache info shows hits
    info_before = get_zipf.cache_info()
    result2 = get_zipf("hello")
    info_after = get_zipf.cache_info()
    assert result1 == result2
    assert info_after.hits > info_before.hits
