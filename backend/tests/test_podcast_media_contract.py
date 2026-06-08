from __future__ import annotations

import kg.routers.podcast_media as media_mod


def test_podcast_media_module_exports_named_helper_surface():
    expected = {
        "_S3_AUDIO_FMT_CACHE",
        "_audio_filename",
        "_get_object_from_s3",
        "_is_s3_not_found",
        "_iter_s3_body",
        "_media_type_for",
        "_podcasts_dir",
        "_read_bytes_from_s3",
        "_read_json_file",
        "_read_json_from_s3",
        "_s3_audio_format",
        "_s3_client",
        "_s3_client_cached",
        "_s3_static_headers",
        "_serve_audio_from_s3",
        "_serve_static_media",
        "_settings",
        "_using_s3",
    }

    missing = [name for name in sorted(expected) if not hasattr(media_mod, name)]
    assert not missing, f"Missing podcast media helpers: {missing}"
