from __future__ import annotations

from kg.user_handlers import _build_user_config_response


class TestBuildUserConfigTranslationFallback:
    """Translation config should never be None — new users get defaults."""

    def test_empty_config_returns_default_translation(self):
        resp = _build_user_config_response({})
        assert resp.translation is not None
        assert resp.translation.source_lang == "en"
        assert resp.translation.target_lang == "zh-Hant"

    def test_existing_translation_preserved(self):
        config = {"translation": {"source_lang": "ja", "target_lang": "en"}}
        resp = _build_user_config_response(config)
        assert resp.translation is not None
        assert resp.translation.source_lang == "ja"
        assert resp.translation.target_lang == "en"

    def test_non_dict_translation_returns_default(self):
        for bad_value in [42, "broken", True, [], None]:
            resp = _build_user_config_response({"translation": bad_value})
            assert resp.translation is not None, f"Failed for translation={bad_value!r}"
            assert resp.translation.source_lang == "en"
            assert resp.translation.target_lang == "zh-Hant"
