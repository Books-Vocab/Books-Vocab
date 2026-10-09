"""ops/podcast_upload.sh staging dir: unique per run, removed on every exit (#2069).

The staging dir used to be the fixed path /tmp/podcast_upload_<sid>, wiped with
`rm -rf` at start and end but not covered by the EXIT trap. An aborted upload
(ffmpeg / aws failure under `set -e`) leaked hundreds of MB of audio, and two
uploads of the same series (a publish retry racing a still-running attempt,
dashboard + CLI) shared — and deleted — one staging tree; the reconcile step
then prunes every remote key missing from that half-empty tree.

The script runs for real with fake ffmpeg / uv / aws on PATH, so these tests
need no network or credentials. --dry-run tests never reach aws. The live tests
run the script's real embedded Python (metadata, reconcile, index) on the test
interpreter with a fake boto3 that records every delete_objects key.

    uv run --python 3.13 --with pytest pytest -q ops/tests/test_podcast_upload.py
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "ops" / "podcast_upload.sh"

_FAKE_FFMPEG = """#!/bin/sh
# Records the output path (last argv), then fails or writes it.
for dst; do :; done
echo "$dst" >> "$FAKE_FFMPEG_LOG"
[ "$FAKE_FFMPEG_MODE" = fail ] && exit 1
: > "$dst"
"""
_FAKE_UV = "#!/bin/sh\ncat >/dev/null\n"
_FAKE_AWS = '#!/bin/sh\necho "aws $*" >> "$FAKE_AWS_LOG"\nexit 97\n'


@pytest.fixture
def upload(tmp_path):
    series_id = f"kgtest_upload_{uuid.uuid4().hex[:12]}"
    legacy_staging = Path("/tmp") / f"podcast_upload_{series_id}"

    ws = tmp_path / series_id
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "overview.md").write_text("# Test Series\n")
    (ws / "scripts").mkdir()
    (ws / "scripts" / "ep_1_pro.m4a").write_bytes(b"not really audio")

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, body in (("ffmpeg", _FAKE_FFMPEG), ("uv", _FAKE_UV), ("aws", _FAKE_AWS)):
        (fakebin / name).write_text(body)
        (fakebin / name).chmod(0o755)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    logs = {"ffmpeg": tmp_path / "ffmpeg.log", "aws": tmp_path / "aws.log"}

    def run(ffmpeg_mode: str = "ok") -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmpdir),
            "PODCAST_BUCKET": "kg-test-bucket",
            "FAKE_FFMPEG_MODE": ffmpeg_mode,
            "FAKE_FFMPEG_LOG": str(logs["ffmpeg"]),
            "FAKE_AWS_LOG": str(logs["aws"]),
        }
        return subprocess.run(
            ["bash", str(_SCRIPT), str(ws), "--dry-run"],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def stagings() -> list[Path]:
        """Staging dirs the script used, recovered from the preview paths ffmpeg saw."""
        lines = logs["ffmpeg"].read_text().split() if logs["ffmpeg"].exists() else []
        return [Path(line).parent.parent for line in lines]

    yield SimpleNamespace(
        run=run,
        stagings=stagings,
        series_id=series_id,
        tmpdir=tmpdir,
        aws_log=logs["aws"],
        legacy_staging=legacy_staging,
    )
    # Pre-fix the script wrote to the shared /tmp path; remove only our own.
    shutil.rmtree(legacy_staging, ignore_errors=True)


def test_staging_is_removed_when_upload_aborts(upload):
    proc = upload.run(ffmpeg_mode="fail")

    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "ffmpeg failed" in proc.stderr
    (staging,) = upload.stagings()  # positive control: staging was created and used
    assert not staging.exists(), f"aborted upload leaked its staging dir {staging}"
    assert not upload.legacy_staging.exists()
    assert not upload.aws_log.exists(), "dry-run must never call aws"


def test_each_run_gets_its_own_staging_dir_and_removes_it(upload):
    first = upload.run()
    second = upload.run()

    assert first.returncode == 0, first.stdout + first.stderr
    assert second.returncode == 0, second.stdout + second.stderr
    a, b = upload.stagings()
    assert a != b, f"two uploads of one series shared staging dir {a}"
    for staging in (a, b):
        assert staging.parent.resolve() == upload.tmpdir.resolve(), staging
        assert staging.name.startswith(f"podcast_upload_{upload.series_id}."), staging
        assert not staging.exists(), f"staging dir {staging} left behind"
    assert not upload.aws_log.exists(), "dry-run must never call aws"
    assert os.listdir(upload.tmpdir) == []


# ── Live upload: reconcile must never prune against a missing staging tree ────
# Stand-in for `uv run [--with PKG]... python - ARGS`: drop uv's own arguments and
# exec the heredoc on the test interpreter (fake boto3 first on PYTHONPATH). exec
# keeps python a direct child of the script, like the real `uv run`, which
# forwards SIGTERM to its python.
_FAKE_UV_LIVE = """#!/bin/sh
[ "$1" = run ] && shift
while :; do
  case "$1" in
    --with) shift 2 ;;
    --*) shift ;;
    *) break ;;
  esac
done
[ "$1" = python ] && shift
exec "$FAKE_UV_PYTHON" "$@"
"""
# `aws s3 cp [opts] SRC DST`. Fetching the existing remote metadata (DST "-")
# finds none. FAKE_AWS_SABOTAGE makes staging vanish right after metadata.json —
# the last upload before reconcile — is sent.
_FAKE_AWS_LIVE = """#!/bin/sh
case " $* " in *" --endpoint-url "*) [ -n "${FAKE_AWS_ENDPOINT_FAILS:-}" ] && { echo "endpoint-attempt $*" >> "$FAKE_AWS_LOG"; exit 5; } ;; esac
src=; dst=
for a; do src=$dst; dst=$a; done
[ "$dst" = - ] && exit 1
echo "aws $*" >> "$FAKE_AWS_LOG"
case "$src" in
  */metadata.json)
    case "${FAKE_AWS_SABOTAGE:-}" in
      remove-staging) rm -rf "$(dirname "$src")" ;;
      empty-staging) find "$(dirname "$src")" -mindepth 1 -delete ;;
    esac ;;
esac
exit 0
"""
_FAKE_BOTO3 = """\
import io, json, os, time

_SID = os.environ["FAKE_S3_SERIES"]
if os.environ.get("FAKE_BOTO3_STARTED"):
    with open(os.environ["FAKE_BOTO3_STARTED"], "a") as f:
        f.write(f"{os.getpid()}\\n")
time.sleep(float(os.environ.get("FAKE_BOTO3_IMPORT_DELAY", "0")))

# What the bucket already holds for the series: the three objects this upload
# stages, plus one genuine orphan (an episode that no longer exists locally).
REMOTE = [
    f"{_SID}/{rel}"
    for rel in ("metadata.json", "ep_01/audio.m4a", "ep_01/preview.m4a", "ep_07/audio.m4a")
]


class _Paginator:
    def paginate(self, Bucket, Prefix="", Delimiter=None):
        if Delimiter:
            yield {"CommonPrefixes": [{"Prefix": f"{_SID}/"}]}
        else:
            yield {"Contents": [{"Key": k} for k in REMOTE if k.startswith(Prefix)]}


class _Client:
    def get_paginator(self, name):
        return _Paginator()

    def delete_objects(self, Bucket, Delete):
        with open(os.environ["FAKE_S3_DELETE_LOG"], "a") as f:
            for obj in Delete["Objects"]:
                f.write(obj["Key"] + "\\n")

    def get_object(self, Bucket, Key):
        body = json.dumps({"id": _SID, "title": "t", "episodes": []}).encode()
        return {"Body": io.BytesIO(body)}


def client(service, **kwargs):
    return _Client()
"""


@pytest.fixture
def live_upload(tmp_path):
    series_id = f"kgtest_live_{uuid.uuid4().hex[:12]}"
    ws = tmp_path / series_id
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "overview.md").write_text("# Test Series\n")
    (ws / "scripts").mkdir()
    (ws / "scripts" / "ep_1_pro.m4a").write_bytes(b"not really audio")

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, body in (
        ("ffmpeg", _FAKE_FFMPEG),
        ("uv", _FAKE_UV_LIVE),
        ("aws", _FAKE_AWS_LIVE),
    ):
        (fakebin / name).write_text(body)
        (fakebin / name).chmod(0o755)
    fakepy = tmp_path / "fakepy" / "boto3"
    fakepy.mkdir(parents=True)
    (fakepy / "__init__.py").write_text(_FAKE_BOTO3)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    logs = {
        name: tmp_path / f"{name}.log"
        for name in ("ffmpeg", "aws", "delete", "boto3", "stdout", "stderr")
    }
    procs: list[subprocess.Popen] = []

    def env(**extra: str) -> dict[str, str]:
        return {
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmpdir),
            "PYTHONPATH": str(fakepy.parent),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PODCAST_BUCKET": "kg-test-bucket",
            "FAKE_UV_PYTHON": sys.executable,
            "FAKE_FFMPEG_MODE": "ok",
            "FAKE_FFMPEG_LOG": str(logs["ffmpeg"]),
            "FAKE_AWS_LOG": str(logs["aws"]),
            "FAKE_S3_SERIES": series_id,
            "FAKE_S3_DELETE_LOG": str(logs["delete"]),
            **extra,
        }

    def start(**extra: str) -> subprocess.Popen:
        # Output goes to files, not pipes: an orphaned child holding the pipe
        # open would make communicate() wait for it and hide that it outlived
        # the script. Own session so teardown can reap any such orphan.
        with open(logs["stdout"], "w") as out, open(logs["stderr"], "w") as err:
            proc = subprocess.Popen(
                ["bash", str(_SCRIPT), str(ws)],
                env=env(**extra),
                stdout=out,
                stderr=err,
                start_new_session=True,
            )
        procs.append(proc)
        return proc

    def run(**extra: str) -> subprocess.CompletedProcess:
        proc = start(**extra)
        proc.wait(timeout=120)
        return subprocess.CompletedProcess(
            proc.args,
            proc.returncode,
            logs["stdout"].read_text(),
            logs["stderr"].read_text(),
        )

    def deleted() -> list[str]:
        path = logs["delete"]
        return path.read_text().split() if path.exists() else []

    def staging() -> Path:
        (preview,) = logs["ffmpeg"].read_text().split()
        return Path(preview).parent.parent

    yield SimpleNamespace(
        start=start,
        run=run,
        deleted=deleted,
        staging=staging,
        stderr=logs["stderr"].read_text,
        series_id=series_id,
        aws_log=logs["aws"],
        boto3_started=logs["boto3"],
    )
    for proc in procs:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_live_upload_prunes_only_true_orphans(live_upload):
    """Positive control: the harness drives the real reconcile, which prunes the
    one remote key that is not staged and keeps everything that is."""
    proc = live_upload.run()

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert live_upload.deleted() == [f"{live_upload.series_id}/ep_07/audio.m4a"]
    assert "index.json" in live_upload.aws_log.read_text()
    assert not live_upload.staging().exists()


@pytest.mark.parametrize("sabotage", ["remove-staging", "empty-staging"])
def test_reconcile_refuses_to_prune_without_a_complete_staging_tree(
    live_upload, sabotage
):
    """Every key the series has is "missing" from a vanished or emptied staging
    tree; reconcile must fail the upload instead of deleting the live series."""
    proc = live_upload.run(FAKE_AWS_SABOTAGE=sabotage)

    assert live_upload.deleted() == [], (
        f"reconcile pruned live objects against a {sabotage} tree"
    )
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "refusing to prune" in proc.stderr, proc.stderr
    assert "index.json" not in live_upload.aws_log.read_text()


def test_sigterm_mid_reconcile_stops_the_child_before_staging_goes(live_upload):
    """The pipeline's publish timeout SIGTERMs only the bash PID, and bash does not
    pass it on to the foreground child it is waiting on. The EXIT trap then
    removed staging while the orphaned reconcile went on to walk it, saw nothing,
    and pruned the whole series from the bucket."""
    delay_s = 4.0
    proc = live_upload.start(
        FAKE_BOTO3_STARTED=str(live_upload.boto3_started),
        FAKE_BOTO3_IMPORT_DELAY=str(delay_s),
    )
    deadline = time.monotonic() + 60
    while not live_upload.boto3_started.exists():
        assert proc.poll() is None, live_upload.stderr()
        assert time.monotonic() < deadline, "reconcile step never started"
        time.sleep(0.05)
    started = time.monotonic()
    child = int(live_upload.boto3_started.read_text().split()[0])

    proc.send_signal(signal.SIGTERM)  # the bash PID only, like pipeline._stop_child
    proc.wait(timeout=30)
    try:
        os.kill(child, 0)
        child_alive = True
    except ProcessLookupError:
        child_alive = False
    time.sleep(max(0.0, started + delay_s + 2 - time.monotonic()))

    assert live_upload.deleted() == [], (
        "orphaned reconcile pruned the live series after staging was removed"
    )
    assert not child_alive, "reconcile child outlived the upload script"
    assert not live_upload.staging().exists()


# ── Partial republish: --only-episodes / --no-prune never delete (#2094) ──────
# Series of three episodes; only 1 and 3 were re-rendered locally, episode 2's
# audio exists only in S3. The fake aws serves a remote metadata.json for the
# `cp <s3-uri> -` fetch and records every uploaded metadata.json body. The fake
# boto3 (reconcile / index) still lists ep_02 as a remote-only key, so any prune
# would delete it and show up in the delete log.
_PARTIAL_OVERVIEW = """# Test Series

| # | Title | Focus | Length |
|---|---|---|---|
| 1 | One | a | ~10 min |
| 2 | Two | b | ~10 min |
| 3 | Three | c | ~10 min |
"""
_REMOTE_META = {
    "id": "x",
    "title": "Old",
    "audioFormat": "m4a",
    "coverImageURL": "/api/podcasts/x/cover?v=abc",
    "createdAt": "2026-01-01T00:00:00+00:00",
    "episodes": [
        {"episodeNumber": 1, "title": "One", "durationSec": 11, "audioAvailable": True},
        {"episodeNumber": 2, "title": "Two", "durationSec": 22, "audioAvailable": True},
        {
            "episodeNumber": 3,
            "title": "Three",
            "durationSec": 33,
            "audioAvailable": True,
        },
    ],
}
_FAKE_AWS_PARTIAL = """#!/bin/sh
src=; dst=
for a; do src=$dst; dst=$a; done
echo "aws $*" >> "$FAKE_AWS_LOG"
if [ "$dst" = - ]; then
  [ -n "${FAKE_REMOTE_META:-}" ] && [ -f "$FAKE_REMOTE_META" ] && cat "$FAKE_REMOTE_META" && exit 0
  exit 1
fi
case "$src" in
  */metadata.json) cp "$src" "$FAKE_META_OUT" ;;
esac
exit 0
"""
_BOTO3_REMOTE_OLD = (
    '("metadata.json", "ep_01/audio.m4a", "ep_01/preview.m4a", "ep_07/audio.m4a")'
)
_BOTO3_REMOTE_NEW = (
    '("metadata.json", "ep_01/audio.m4a", "ep_01/preview.m4a",'
    ' "ep_02/audio.m4a", "ep_03/audio.m4a")'
)


@pytest.fixture
def partial(tmp_path):
    assert _BOTO3_REMOTE_OLD in _FAKE_BOTO3, "boto3 stub patch target moved"
    fake_boto3 = _FAKE_BOTO3.replace(_BOTO3_REMOTE_OLD, _BOTO3_REMOTE_NEW)
    series_id = f"kgtest_partial_{uuid.uuid4().hex[:12]}"
    ws = tmp_path / series_id
    (ws / "plan").mkdir(parents=True)
    (ws / "plan" / "overview.md").write_text(_PARTIAL_OVERVIEW)
    (ws / "plan" / "cover.png").write_bytes(b"new cover")
    (ws / "scripts").mkdir()
    for n in (1, 3):  # episode 2 is S3-only
        (ws / "scripts" / f"ep_{n}_pro.m4a").write_bytes(b"audio")

    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    for name, body in (
        ("ffmpeg", _FAKE_FFMPEG),
        ("uv", _FAKE_UV_LIVE),
        ("aws", _FAKE_AWS_PARTIAL),
    ):
        (fakebin / name).write_text(body)
        (fakebin / name).chmod(0o755)
    fakepy = tmp_path / "fakepy" / "boto3"
    fakepy.mkdir(parents=True)
    (fakepy / "__init__.py").write_text(fake_boto3)
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    remote_meta = tmp_path / "remote_meta.json"
    remote_meta.write_text(json.dumps(_REMOTE_META))
    logs = {
        "aws": tmp_path / "aws.log",
        "ffmpeg": tmp_path / "ffmpeg.log",
        "delete": tmp_path / "delete.log",
        "meta": tmp_path / "uploaded_metadata.json",
    }

    def run(*args: str, with_remote_meta: bool = True) -> subprocess.CompletedProcess:
        env = {
            "PATH": f"{fakebin}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "TMPDIR": str(tmpdir),
            "PYTHONPATH": str(fakepy.parent),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PODCAST_BUCKET": "kg-test-bucket",
            "FAKE_UV_PYTHON": sys.executable,
            "FAKE_FFMPEG_MODE": "ok",
            "FAKE_FFMPEG_LOG": str(logs["ffmpeg"]),
            "FAKE_AWS_LOG": str(logs["aws"]),
            "FAKE_S3_SERIES": series_id,
            "FAKE_S3_DELETE_LOG": str(logs["delete"]),
            "FAKE_META_OUT": str(logs["meta"]),
        }
        if with_remote_meta:
            env["FAKE_REMOTE_META"] = str(remote_meta)
        return subprocess.run(
            ["bash", str(_SCRIPT), str(ws), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

    def aws_calls() -> list[str]:
        return logs["aws"].read_text().splitlines() if logs["aws"].exists() else []

    def uploaded_keys() -> set[str]:
        """Destination keys (relative to the series prefix) of every `aws s3 cp` upload."""
        prefix = f"s3://kg-test-bucket/{series_id}/"
        keys = set()
        for line in aws_calls():
            dst = line.split()[-1]
            if dst.startswith(prefix):
                keys.add(dst[len(prefix) :])
            elif dst == "s3://kg-test-bucket/index.json":
                keys.add("index.json")
        return keys

    def deleted() -> list[str]:
        path = logs["delete"]
        return path.read_text().split() if path.exists() else []

    def meta() -> dict:
        return json.loads(logs["meta"].read_text())

    return SimpleNamespace(
        run=run,
        aws_calls=aws_calls,
        uploaded_keys=uploaded_keys,
        deleted=deleted,
        meta=meta,
        series_id=series_id,
        tmpdir=tmpdir,
    )


def test_default_mode_still_prunes_remote_only_keys(partial):
    """Default behaviour is unchanged: remote keys absent from staging are deleted
    (positive control for the no-prune assertions below)."""
    proc = partial.run()

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert partial.deleted() == [f"{partial.series_id}/ep_02/audio.m4a"]
    assert "cover.png" in partial.uploaded_keys()
    assert "pruned 1 orphan" in proc.stdout


def test_only_episodes_uploads_only_named_keys_and_never_deletes(partial):
    proc = partial.run("--only-episodes", "1,3")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert partial.deleted() == [], "partial republish deleted a remote key"
    calls = "\n".join(partial.aws_calls())
    for banned in (" rm ", "--delete", " sync ", " mv "):
        assert banned not in calls, f"{banned!r} issued: {calls}"
    # Only the named episodes' files (+ metadata, index); nothing for ep 2 or cover.
    assert partial.uploaded_keys() == {
        "ep_01/audio.m4a",
        "ep_01/preview.m4a",
        "ep_03/audio.m4a",
        "metadata.json",
        "index.json",
    }
    assert "Skipping reconcile" in proc.stdout


def test_only_episodes_keeps_untouched_episodes_listed_from_remote_metadata(partial):
    proc = partial.run("--only-episodes=1,3")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    meta = partial.meta()
    eps = {e["episodeNumber"]: e for e in meta["episodes"]}
    assert [e["episodeNumber"] for e in meta["episodes"]] == [1, 2, 3]
    assert eps[2] == _REMOTE_META["episodes"][1], "untouched episode was rewritten"
    assert eps[1]["audioAvailable"] and eps[3]["audioAvailable"]
    assert meta["createdAt"] == _REMOTE_META["createdAt"]
    assert meta["coverImageURL"] == _REMOTE_META["coverImageURL"]
    assert meta["audioFormat"] == "m4a"


def test_no_prune_alone_uploads_everything_local_but_deletes_nothing(partial):
    proc = partial.run("--no-prune")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert partial.deleted() == []
    assert {
        "ep_01/audio.m4a",
        "ep_03/audio.m4a",
        "cover.png",
    } <= partial.uploaded_keys()
    assert "Skipping reconcile" in proc.stdout


def test_only_episodes_missing_locally_aborts_before_any_upload(partial):
    proc = partial.run("--only-episodes", "1,2")

    assert proc.returncode != 0
    assert "episode 2 has no local" in proc.stderr
    assert partial.uploaded_keys() == set()
    assert partial.deleted() == []
    assert os.listdir(partial.tmpdir) == [], "staging leaked"


def test_only_episodes_without_remote_metadata_aborts_before_any_upload(partial):
    proc = partial.run("--only-episodes", "1,3", with_remote_meta=False)

    assert proc.returncode != 0
    assert "needs an existing remote" in proc.stderr
    assert partial.uploaded_keys() == set()
    assert partial.deleted() == []


@pytest.mark.parametrize("bad", ["", "a", "1,,3", "1;3"])
def test_only_episodes_rejects_malformed_lists(partial, bad):
    proc = partial.run("--only-episodes", bad)

    assert proc.returncode != 0
    assert partial.uploaded_keys() == set()


def test_only_episodes_dry_run_stages_only_named_and_calls_no_aws(partial):
    proc = partial.run("--only-episodes", "3", "--dry-run")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert partial.aws_calls() == []
    assert "ep_03/audio.m4a" in proc.stdout
    assert "ep_01" not in proc.stdout
    assert "NO prune" in proc.stdout


def test_make_preview_survives_empty_movflags_under_set_u(tmp_path):
    """mp3 previews leave movflags empty; bash 3.2 + set -u must not abort."""
    script = Path(__file__).resolve().parents[1] / "podcast_upload.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ffmpeg = fake_bin / "ffmpeg"
    ffmpeg.write_text('#!/bin/sh\nfor last; do :; done\necho "$@" > "$last"\n')
    ffmpeg.chmod(0o755)
    body = subprocess.run(
        ["sed", "-n", "/^make_preview() {/,/^}/p", str(script)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "make_preview" in body
    dst = tmp_path / "out.mp3"
    harness = (
        'set -euo pipefail\nPREVIEW_SECONDS=180\nerr() { echo "$*" >&2; exit 1; }\n'
        f'{body}\nmake_preview in.mp3 "{dst}" mp3\n'
    )
    r = subprocess.run(
        ["/bin/bash", "-c", harness],
        capture_output=True,
        text=True,
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
    )
    assert r.returncode == 0, r.stderr
    assert "-movflags" not in dst.read_text()


def test_failed_endpoint_call_is_not_retried_on_the_default_endpoint(live_upload):
    """run_aws must not fall back to the default endpoint/identity when the
    endpoint-scoped call fails (#2818: `A && B || C` reran it)."""
    live_upload.run(
        AWS_ENDPOINT_URL="https://endpoint.invalid", FAKE_AWS_ENDPOINT_FAILS="1"
    )

    lines = live_upload.aws_log.read_text().splitlines()
    assert lines, "harness never reached aws"
    assert all(line.startswith("endpoint-attempt") for line in lines), lines
