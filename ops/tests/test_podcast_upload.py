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
