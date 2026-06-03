"""
Tests for anonymous rate-limit key derivation across trusted proxy hops.

Production contract: bare single-layer Caddy directly on AWS public net (no CDN)
appends the real client IP to the END of X-Forwarded-For. So hops=1 (default)
selects the last segment — byte-for-byte identical to the prior `xff.split(",")[-1]`
behavior. RATE_LIMIT_TRUSTED_HOPS=N+1 is the future knob for N fronting proxies.
"""

from __future__ import annotations

from kg.api import _anon_rate_limit_key


class TestDefaultHopsBackcompat:
    """hops=1 must equal the legacy xff.split(',')[-1].strip() behavior."""

    def test_two_segments_takes_last(self):
        # XFF="fake, real" — Caddy appended the real IP at the tail.
        assert _anon_rate_limit_key("fake, real", "1.2.3.4", 1) == "real"

    def test_single_segment_takes_it(self):
        assert _anon_rate_limit_key("evil", "1.2.3.4", 1) == "evil"

    def test_segments_are_stripped(self):
        assert _anon_rate_limit_key("a ,  192.168.0.1 ", "1.2.3.4", 1) == "192.168.0.1"

    def test_empty_xff_falls_back_to_client_host(self):
        assert _anon_rate_limit_key("", "9.9.9.9", 1) == "9.9.9.9"

    def test_empty_xff_no_client_host_returns_unknown(self):
        assert _anon_rate_limit_key("", None, 1) == "unknown"


class TestMultipleTrustedHops:
    def test_two_hops_takes_second_from_end(self):
        # 2 trusted fronting proxies: XFF="real, proxy1, proxy2"
        # proxy2 is added by the outermost trusted proxy; the real client is
        # the segment 2 from the end.
        assert _anon_rate_limit_key("real, proxy1, proxy2", "1.2.3.4", 2) == "proxy1"

    def test_three_hops(self):
        assert _anon_rate_limit_key("client, a, b, c", "1.2.3.4", 3) == "a"


class TestHopsExceedsSegments:
    """hops greater than available segments must not crash; safe fallback."""

    def test_hops_gt_segments_takes_first_segment(self):
        # Only 2 segments but 5 trusted hops claimed — fall back to the
        # frontmost (least-spoofable-by-this-contract) segment, no IndexError.
        assert _anon_rate_limit_key("client, proxy", "1.2.3.4", 5) == "client"

    def test_hops_gt_segments_single(self):
        assert _anon_rate_limit_key("only", "1.2.3.4", 9) == "only"

    def test_hops_zero_or_negative_safe(self):
        # Defensive: a non-positive hops is a misconfig; clamp to 1 so we fall
        # back to the production-correct last-segment behavior (not a crash).
        assert _anon_rate_limit_key("a, b", "1.2.3.4", 0) == "b"
        assert _anon_rate_limit_key("a, b", "1.2.3.4", -5) == "b"
