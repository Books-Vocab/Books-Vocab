"""ops/podcast_upload.sh staging dir: unique per run, removed on every exit (#2069).

The staging dir used to be the fixed path /tmp/podcast_upload_<sid>, wiped with
`rm -rf` at start and end but not covered by the EXIT trap. An aborted upload
(ffmpeg / aws failure under `set -e`) leaked hundreds of MB of audio, and two
uploads of the same series (a publish retry racing a still-running attempt,
dashboard + CLI) shared — and deleted — one staging tree; the reconcile step
then prunes every remote key missing from that half-empty tree.

The script runs for real in --dry-run mode with fake ffmpeg / uv / aws on PATH
(aws must never be reached), so these tests need no network or credentials.

    uv run --python 3.13 --with pytest pytest -q ops/tests/test_podcast_upload.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
