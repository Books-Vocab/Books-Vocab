"""Transport boundary + Oscar-side receipt verification tests (no ssh, no network)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

from lib import xmachine_transport as xt  # noqa: E402
from lib.compute_receipt import OscarAckAuthority, ReceiptSigner  # noqa: E402

NOW = 2_000_000.0
COMMIT = "a" * 40
TREE = "b" * 64
SPEC = "c" * 64
RUNNER = "sha256:" + "d" * 64
PROFILE = "ops.docs-lint-registry"


def _ids():
    job, nonce = xt.new_job_id(), xt.new_nonce()
    digest = xt.request_digest(
        job_id=job, nonce=nonce, profile=PROFILE, spec_digest=SPEC, commit=COMMIT, tree_digest=TREE
    )
    expected = {
        "job_id": job,
        "nonce": nonce,
        "request_digest": digest,
        "profile": PROFILE,
        "spec_digest": SPEC,
        "runner_image_digest": RUNNER,
        "commit_sha": COMMIT,
        "tree_sha256": TREE,
    }
    return expected


def _receipt(signer, expected, *, log="ok\n", **over):
    body = {
        "schema": xt.RECEIPT_SCHEMA,
        "job_id": expected["job_id"],
        "nonce": expected["nonce"],
        "request_digest": expected["request_digest"],
        "profile": expected["profile"],
        "spec_digest": expected["spec_digest"],
        "runner_image_digest": expected["runner_image_digest"],
        "source": {"commit_sha": COMMIT, "tree_sha256": TREE},
        "host": {"host_id": "felix-host", "host_role": "felix"},
        "issued_at": NOW - 10,
        "returncode": 0,
        "log_digest": hashlib.sha256(log.encode()).hexdigest(),
        "artifact_digests": {},
    }
    body.update(over)
    return signer.sign(body)


@pytest.fixture(scope="module")
def signer():
    return ReceiptSigner.generate()


@pytest.fixture()
def pinned(signer):
    return ReceiptSigner.from_public_bytes(signer.public_bytes())


def _launcher(tmp_path):
    path = tmp_path / "launcher"
    path.write_text("#!/bin/sh\n")
    return path


# ---------------------------------------------------------------- argv boundary


def test_job_id_and_nonce_are_csprng_hex():
    assert len({xt.new_job_id() for _ in range(50)}) == 50
    assert all(len(xt.new_job_id()) == 32 for _ in range(3))


def test_argv_is_literal_list_with_each_dynamic_value_separate(tmp_path):
    job = xt.new_job_id()
    hostile = "x; rm -rf / $(id) `id` && -- --launcher"
    argv = xt.build_argv(
        "submit",
        job_id=job,
        fields={"commit": COMMIT, "profile": PROFILE, "spec-digest": SPEC},
        params={"test_path": hostile},
        launcher=_launcher(tmp_path),
    )
    assert isinstance(argv, list) and all(isinstance(item, str) for item in argv)
    assert argv[1:4] == ["submit", "--job-id", job]
    assert hostile in argv  # whole, as its own element, never split or interpolated
    assert argv[argv.index(hostile) - 2 :][:3] == ["--param", "test_path", hostile]
    assert not any(item == "sh" or item == "-c" for item in argv)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"verb": "exec"}, "verb"),
        ({"verb": "probe", "job_id": "../x"}, "job-id"),
        ({"verb": "submit", "fields": {"host": "10.0.0.1"}}, "field"),
        ({"verb": "submit", "fields": {"commit": "HEAD; id"}}, "field-value"),
        ({"verb": "submit", "fields": {"profile": "Bad Key"}}, "field-value"),
        ({"verb": "submit", "fields": {"spec-digest": "xyz"}}, "field-value"),
        ({"verb": "submit", "params": {"Bad-Name": "v"}}, "param"),
        ({"verb": "submit", "params": {"ok": ""}}, "param"),
    ],
)
def test_argv_rejects_non_closed_inputs(kwargs, code):
    kwargs.setdefault("job_id", xt.new_job_id())
    with pytest.raises(xt.TransportError) as caught:
        xt.build_argv(**kwargs)
    assert caught.value.code == code


def test_call_uses_runner_with_list_argv_and_parses_single_json(tmp_path):
    seen = []

    def runner(argv):
        seen.append(argv)
        return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True}), "")

    transport = xt.XmachineTransport(runner=runner, launcher=_launcher(tmp_path))
    assert transport.probe(xt.new_job_id()) == {"ok": True}
    assert isinstance(seen[0], list) and seen[0][1] == "probe"


@pytest.mark.parametrize(
    ("stdout", "returncode", "code"),
    [("not json", 0, "launcher-output"), ("[1]", 0, "launcher-output"), ("{}", 3, "launcher-exit")],
)
def test_call_fails_closed_on_bad_launcher_output(tmp_path, stdout, returncode, code):
    transport = xt.XmachineTransport(
        runner=lambda argv: subprocess.CompletedProcess(argv, returncode, stdout, ""),
        launcher=_launcher(tmp_path),
    )
    with pytest.raises(xt.TransportError) as caught:
        transport.probe(xt.new_job_id())
    assert caught.value.code == code


def test_missing_launcher_never_invokes_runner(tmp_path):
    transport = xt.XmachineTransport(
        runner=lambda argv: pytest.fail("must not run"), launcher=tmp_path / "absent"
    )
    with pytest.raises(xt.TransportError) as caught:
        transport.probe(xt.new_job_id())
    assert caught.value.code == "launcher-missing"


def test_default_runner_streams_without_shell(monkeypatch, tmp_path):
    captured = {}

    def fake_streamed(command, **kwargs):
        captured.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0, "{}", "")

    import lib.streaming_command as streaming

    monkeypatch.setattr(streaming, "run_streamed_command", fake_streamed)
    job = xt.new_job_id()
    xt.streamed_runner(job, tmp_path)(["/x", "probe"])
    assert captured["command"] == ["/x", "probe"]
    assert captured["label"] == job
    assert captured["progress_prefix"].startswith("[compute]")


# ------------------------------------------------------------------- receipts


def _verify(signer, expected, receipt, log="ok\n", **over):
    args = dict(signer=signer, expected=expected, caller_host_id="oscar-host", now=NOW)
    args.update(over)
    return xt.verify_receipt(receipt, log, **args)


def test_valid_receipt_verifies(signer, pinned):
    expected = _ids()
    assert _verify(pinned, expected, _receipt(signer, expected))["returncode"] == 0


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"nonce": "e" * 32}, "receipt-nonce"),
        ({"request_digest": "e" * 64}, "receipt-request-digest"),
        ({"job_id": "e" * 32}, "receipt-job"),
        ({"profile": "other.profile"}, "receipt-profile"),
        ({"spec_digest": "e" * 64}, "receipt-spec"),
        ({"runner_image_digest": "sha256:" + "e" * 64}, "receipt-runner"),
        ({"source": {"commit_sha": "e" * 40, "tree_sha256": TREE}}, "receipt-source"),
        ({"source": {"commit_sha": COMMIT, "tree_sha256": "e" * 64}}, "receipt-source"),
        ({"host": {"host_id": "oscar-host", "host_role": "felix"}}, "receipt-host"),
        ({"host": {"host_id": "felix-host", "host_role": "oscar"}}, "receipt-host"),
        ({"issued_at": NOW - 99999}, "receipt-stale"),
        ({"schema": "other"}, "receipt-schema"),
        ({"log_digest": "e" * 64}, "receipt-log-digest"),
    ],
)
def test_receipt_mismatches_are_named(signer, pinned, over, code):
    expected = _ids()
    with pytest.raises(xt.TransportError) as caught:
        _verify(pinned, expected, _receipt(signer, expected, **over))
    assert caught.value.code == code


def test_receipt_signed_by_unpinned_key_is_rejected(pinned):
    rogue = ReceiptSigner.generate()
    expected = _ids()
    with pytest.raises(xt.TransportError) as caught:
        _verify(pinned, expected, _receipt(rogue, expected))
    assert caught.value.code == "receipt-signature"


def test_tampered_receipt_is_rejected(signer, pinned):
    expected = _ids()
    receipt = _receipt(signer, expected)
    receipt["returncode"] = 1
    with pytest.raises(xt.TransportError) as caught:
        _verify(pinned, expected, receipt)
    assert caught.value.code == "receipt-signature"


# ----------------------------------------------------------- accept / ack flow


class FakeTransport:
    def __init__(self, authority, *, cleanup="acked", echo=True):
        self.authority = authority
        self.cleanup = cleanup
        self.echo = echo
        self.acks = []

    def ack(self, job_id, *, fields):
        self.acks.append((job_id, fields))
        ack = {
            "token": fields["ack-token"],
            "job_id": job_id,
            "receipt_digest": fields["receipt-digest"],
            "mac": fields["ack-mac"],
        }
        return {"cleanup": self.cleanup, **({"ack": ack} if self.echo else {})}


def _accept(tmp_path, signer, pinned, expected, receipt, *, transport=None, authority=None):
    authority = authority or OscarAckAuthority(tmp_path / "ack.json", key=b"k" * 32)
    transport = transport or FakeTransport(authority)
    return xt.accept_receipt(
        receipt,
        "ok\n",
        transport=transport,
        signer=pinned,
        authority=authority,
        expected=expected,
        caller_host_id="oscar-host",
        cache_root=tmp_path / "cache",
        now=NOW,
    ), transport


def test_accept_persists_before_ack_and_reports_acked(tmp_path, signer, pinned):
    expected = _ids()
    result, transport = _accept(tmp_path, signer, pinned, expected, _receipt(signer, expected))
    path = Path(result["result_path"])
    assert path == tmp_path / "cache" / expected["job_id"] / "result.json"
    stored = json.loads(path.read_text())
    assert stored["ack_verified"] is True and stored["cleanup"] == {"state": "acked"}
    assert stored["signature_verified"] and stored["nonce_verified"] and stored["replay_checked"]
    assert len(transport.acks) == 1
    assert not list((tmp_path / "cache").rglob(".*.tmp")) and not [
        p for p in (tmp_path / "cache" / expected["job_id"]).iterdir() if p.name != "result.json"
    ]


def test_replayed_receipt_is_refused_without_second_ack(tmp_path, signer, pinned):
    expected = _ids()
    receipt = _receipt(signer, expected)
    _accept(tmp_path, signer, pinned, expected, receipt)
    transport = FakeTransport(OscarAckAuthority(tmp_path / "ack2.json", key=b"k" * 32))
    with pytest.raises(xt.TransportError) as caught:
        _accept(tmp_path, signer, pinned, expected, receipt, transport=transport)
    assert caught.value.code == "receipt-replay"
    assert transport.acks == []


def test_invalid_receipt_writes_no_result_and_no_ack(tmp_path, signer, pinned):
    expected = _ids()
    transport = FakeTransport(OscarAckAuthority(tmp_path / "ack.json", key=b"k" * 32))
    with pytest.raises(xt.TransportError):
        _accept(
            tmp_path, signer, pinned, expected, _receipt(signer, expected, nonce="e" * 32),
            transport=transport,
        )
    assert transport.acks == [] and not (tmp_path / "cache").exists()


@pytest.mark.parametrize("kind", ["no-cleanup", "no-echo"])
def test_ack_must_be_verified_end_to_end(tmp_path, signer, pinned, kind):
    expected = _ids()
    authority = OscarAckAuthority(tmp_path / "ack.json", key=b"k" * 32)
    transport = FakeTransport(
        authority, cleanup="pending" if kind == "no-cleanup" else "acked", echo=kind != "no-echo"
    )
    with pytest.raises(xt.TransportError) as caught:
        _accept(tmp_path, signer, pinned, expected, _receipt(signer, expected),
                transport=transport, authority=authority)
    assert caught.value.code == "ack-failed"
    stored = json.loads((tmp_path / "cache" / expected["job_id"] / "result.json").read_text())
    assert "ack_verified" not in stored  # persisted, but never reported as acked


def test_atomic_write_leaves_no_temporary_on_failure(tmp_path):
    class Boom:
        pass

    with pytest.raises(TypeError):
        xt.atomic_write_json(tmp_path / "d" / "r.json", {"x": Boom()})
    assert not (tmp_path / "d" / "r.json").exists()
    assert list((tmp_path / "d").iterdir()) == []
