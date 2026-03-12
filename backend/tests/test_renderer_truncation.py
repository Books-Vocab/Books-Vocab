
import unittest

from kg.renderer import CardRenderer


class TestCardRendererTruncation(unittest.TestCase):
    def setUp(self):
        # minimal mock for CardRenderer dependencies
        self.renderer = CardRenderer(None, None, {})

    def test_truncate_short_sentence(self):
        text = "This is a **short** sentence."
        # No truncation needed (under 5+1+5 words)
        result = self.renderer._truncate_example(text, radius=5)
        self.assertEqual(result, "This is a **short** sentence.")

    def test_truncate_long_start(self):
        # 7 words before, 2 after
        text = "One two three four five six seven **target** end."
        # Should keep 5 words before: "three four five six seven"
        expected = "...three four five six seven **target** end."
        result = self.renderer._truncate_example(text, radius=5)
        self.assertEqual(result, expected)

    def test_truncate_long_end(self):
        # 2 words before, 7 after
        text = "Start here **target** one two three four five six seven."
        # Should keep 5 words after: "one two three four five"
        expected = "Start here **target** one two three four five..."
        result = self.renderer._truncate_example(text, radius=5)
        self.assertEqual(result, expected)

    def test_truncate_both_sides(self):
        # 7 words before, 7 after
        text = "One two three four five six seven **target** one two three four five six seven."
        expected = "...three four five six seven **target** one two three four five..."
        result = self.renderer._truncate_example(text, radius=5)
        self.assertEqual(result, expected)

    def test_truncate_user_example(self):
        # User provided example
        text = "While Bevalis was technically the capital of Idris, it wasn’t that big, and everyone knew her by sight. Judging by the stories Siri had heard from passing **ramblemen**, her home was hardly even a village compared with the massive metropolises in other nations."
        # Context: "...Siri had heard from passing **ramblemen**, her home was hardly even..."
        # Let's see what radius=5 gives:
        # Before: "stories Siri had heard from passing" (6 words) -> keep 5: "Siri had heard from passing"
        # After: "her home was hardly even a" (6 words) -> keep 5: "her home was hardly even a"
        # Wait, the user example result was "...Siri had heard from passing **ramblemen**, her home was hardly even..."
        # "her home was hardly even" is 5 words.

        expected = "...Siri had heard from passing **ramblemen**, her home was hardly even..."
        # Note: checking punctuation handling might be tricky with simple split.
        # But let's assume basic split is fine for now.
        result = self.renderer._truncate_example(text, radius=5)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
