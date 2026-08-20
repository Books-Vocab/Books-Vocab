from __future__ import annotations

import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib.compute_receipt import AckReplayError, OscarAckAuthority


def test_forged_mac_fails_closed_without_consuming_valid_ack(tmp_path: Path) -> None:
    authority = OscarAckAuthority(tmp_path / "ack-ledger.json", key=b"k" * 32)
    ack = authority.issue("job-1335", "a" * 64)
    forged = dict(ack, mac="0" * len(ack["mac"]))

    with pytest.raises(AckReplayError, match="invalid"):
        authority.verify(forged)

    assert authority.verify(ack) is True
    with pytest.raises(AckReplayError, match="replay"):
        authority.verify(ack)


def test_mac_check_uses_caller_submitted_value_with_constant_time_compare(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lib import compute_receipt

    authority = OscarAckAuthority(tmp_path / "ack-ledger.json", key=b"k" * 32)
    ack = authority.issue("job-1335", "a" * 64)
    forged = dict(ack, mac="0" * len(ack["mac"]))
    comparisons: list[tuple[object, object]] = []
    original_compare_digest = compute_receipt.hmac.compare_digest

    def capture_compare_digest(left: object, right: object) -> bool:
        comparisons.append((left, right))
        return original_compare_digest(left, right)

    monkeypatch.setattr(compute_receipt.hmac, "compare_digest", capture_compare_digest)

    with pytest.raises(AckReplayError, match="invalid"):
        authority.verify(forged)

    assert comparisons
    assert forged["mac"] in comparisons[0]
    assert ack["mac"] in comparisons[0]
