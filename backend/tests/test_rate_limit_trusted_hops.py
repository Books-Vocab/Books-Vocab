"""
Tests for anonymous rate-limit key derivation across trusted proxy hops.

Production contract: bare single-layer Caddy directly on AWS public net (no CDN)
appends the real client IP to the END of X-Forwarded-For. So hops=1 (default)
selects the last segment — byte-for-byte identical to the prior `xff.split(",")[-1]`
behavior. RATE_LIMIT_TRUSTED_HOPS=N+1 is the future knob for N fronting proxies.
"""

from __future__ import annotations

import pytest

from kg.api import _anon_rate_limit_key


@pytest.mark.parametrize(
    "xff,host,hops,expected",
    [
        # --- hops=1 must equal the legacy xff.split(',')[-1].strip() behavior ---
        # XFF="fake, real" — Caddy appended the real IP at the tail.
        pytest.param("fake, real", "1.2.3.4", 1, "real", id="default-two-segments-takes-last"),
        pytest.param("evil", "1.2.3.4", 1, "evil", id="default-single-segment-takes-it"),
        pytest.param("a ,  192.168.0.1 ", "1.2.3.4", 1, "192.168.0.1", id="default-segments-stripped"),
        pytest.param("", "9.9.9.9", 1, "9.9.9.9", id="default-empty-xff-falls-back-to-host"),
        pytest.param("", None, 1, "unknown", id="default-empty-xff-no-host-unknown"),
        # --- multiple trusted fronting proxies: pick segment `hops` from the end ---
        # 2 trusted fronting proxies: XFF="real, proxy1, proxy2"; real client is
        # the segment 2 from the end.
        pytest.param("real, proxy1, proxy2", "1.2.3.4", 2, "proxy1", id="two-hops-second-from-end"),
        pytest.param("client, a, b, c", "1.2.3.4", 3, "a", id="three-hops"),
        # --- hops greater than available segments must not crash; safe fallback ---
        # Only 2 segments but 5 trusted hops claimed — fall back to the frontmost
        # (least-spoofable-by-this-contract) segment, no IndexError.
        pytest.param("client, proxy", "1.2.3.4", 5, "client", id="hops-gt-segments-takes-first"),
        pytest.param("only", "1.2.3.4", 9, "only", id="hops-gt-segments-single"),
        # Defensive: a non-positive hops is a misconfig; clamp to 1 so we fall back
        # to the production-correct last-segment behavior (not a crash).
        pytest.param("a, b", "1.2.3.4", 0, "b", id="hops-zero-clamps-to-last"),
        pytest.param("a, b", "1.2.3.4", -5, "b", id="hops-negative-clamps-to-last"),
    ],
)
def test_anon_rate_limit_key(xff, host, hops, expected):
    assert _anon_rate_limit_key(xff, host, hops) == expected
