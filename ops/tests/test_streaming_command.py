from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

OPS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_ROOT))
from lib import streaming_command  # noqa: E402
from lib.streaming_command import run_streamed_command  # noqa: E402


HEARTBEAT_SHAPE = re.compile(
    r"^\[test\] gate=\S+ phase=heartbeat elapsed=\d+\.\d+s pid=\d+ alive=(?:true|false) "
    r"stalled=(?:true|false) outBytes=\d+ idle=\d+\.\d+s$"
)


def _heartbeats(progress: str) -> list[str]:
    return [line for line in progress.splitlines() if "phase=heartbeat" in line]


def _assert_stalled_agrees_with_idle(beats: list[str], interval: float) -> None:
    """``stalled`` must be exactly the predicate the same line's ``idle`` implies.

    This compares two fields of one line, so it holds whatever the machine's timing
    turned out to be — it can lose discriminating power under load but can never go
    falsely red, which is the property a timing-adjacent assertion needs. It is what
    pins the THRESHOLD: an implementation that fires stalled at half an interval
    still satisfies "silent child stalls" and "busy child does not", and is caught
    only here, and only when some beat's idle lands between the two thresholds.
    """
    for beat in beats:
        idle = float(_field(beat, "idle").rstrip("s"))
        if abs(idle - interval) < 0.02:  # printed at 2dp; do not judge the boundary
            continue
        assert _field(beat, "stalled") == str(idle >= interval).lower(), beat


def _field(line: str, key: str) -> str:
    for token in line.split():
        if token.startswith(f"{key}="):
            return token.split("=", 1)[1]
    raise AssertionError(f"heartbeat line is missing {key!r}: {line!r}")


def _process_is_live(pid: int) -> bool:
    completed = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    state = completed.stdout.strip()
    return completed.returncode == 0 and bool(state) and not state.startswith("Z")


def test_progress_contract_and_separate_streams(tmp_path: Path) -> None:
    parent_stdout = io.StringIO()
    parent_stderr = io.StringIO()

    with redirect_stdout(parent_stdout), redirect_stderr(parent_stderr):
        completed = run_streamed_command(
            [
                sys.executable,
                "-c",
                "import sys,time; print('json'); print('diagnostic', file=sys.stderr); time.sleep(.06)",
            ],
            cwd=tmp_path,
            label_key="producer",
            label="contract-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
        )

    assert parent_stdout.getvalue() == ""
    assert completed.stdout == "json\n"
    assert completed.stderr == "diagnostic\n"
    progress_lines = parent_stderr.getvalue().splitlines()
    phases = [line.split("phase=", 1)[1].split()[0] for line in progress_lines]
    assert phases[0:2] == ["start", "spawned"]
    assert "heartbeat" in phases
    assert phases[-1] == "done"
    for line in progress_lines:
        assert "elapsed=" in line
        assert "pid=" in line
        assert "alive=" in line


def test_silent_child_heartbeat_reports_stalled_with_stable_field_order(tmp_path: Path) -> None:
    """A child that is alive but producing nothing must be distinguishable.

    This is the half of the contract that ``alive=true`` alone could never carry:
    a wedged child and a working child looked identical on the wire.
    """
    progress = io.StringIO()

    with redirect_stderr(progress):
        completed = run_streamed_command(
            [sys.executable, "-c", "import time; time.sleep(0.45)"],
            cwd=tmp_path,
            label_key="gate",
            label="silent-child",
            progress_prefix="[test]",
            heartbeat_interval=0.05,
        )

    assert completed.returncode == 0
    beats = _heartbeats(progress.getvalue())
    # Beat COUNT is not the contract — it is the machine's mood. Under load this is
    # the one assertion here that goes red while the behaviour under test is fine.
    assert beats, "a 0.45s child at a 0.05s heartbeat must emit at least one heartbeat"
    # Field order is load-bearing: ops/tests/test_ios_ops_release_heartbeat.sh greps an
    # unanchored `... alive=true` prefix, so the new fields must stay strictly after it.
    for beat in beats:
        assert HEARTBEAT_SHAPE.match(beat), beat
    assert all(_field(beat, "stalled") == "true" for beat in beats), beats
    assert all(_field(beat, "outBytes") == "0" for beat in beats), beats
    _assert_stalled_agrees_with_idle(beats, 0.05)
    idles = [float(_field(beat, "idle").rstrip("s")) for beat in beats]
    assert idles == sorted(idles), idles


def test_busy_child_heartbeat_never_reports_stalled(tmp_path: Path) -> None:
    """A steadily-producing child must never be slandered as stalled.

    This half blocks the cheap fake fix (always print ``stalled=true``) and it also
    pins the drain semantics: with ``read`` instead of ``read1`` the parent sees this
    child's bytes only at EOF, so a low-volume-but-working child would read as wedged.
    """
    progress = io.StringIO()

    with redirect_stderr(progress):
        completed = run_streamed_command(
            [
                sys.executable,
                "-c",
                "import sys,time\n"
                "end=time.monotonic()+1.2\n"
                "while time.monotonic()<end:\n"
                "    sys.stdout.write('tick\\n'); sys.stdout.flush(); time.sleep(0.005)\n",
            ],
            cwd=tmp_path,
            label_key="gate",
            label="busy-child",
            progress_prefix="[test]",
            # Margin is a RATIO, not a quiet machine: the child writes every ~5ms
            # against a 0.5s interval, so slandering a PRODUCING child would take
            # 100 consecutive tick periods of starvation.
            heartbeat_interval=0.5,
        )

    assert completed.returncode == 0
    # The child is duration-bounded, so the tick COUNT is load-dependent and pinning
    # it would smuggle the machine's mood into the assertion. What must hold is that
    # chunked reads reassembled cleanly: every line intact, none torn or duplicated.
    lines = completed.stdout.splitlines()
    assert set(lines) == {"tick"}, completed.stdout[:200]
    assert len(lines) > 20, len(lines)
    beats = _heartbeats(progress.getvalue())
    # Scope the claim to what the contract actually says. A beat with outBytes=0 is a
    # child that has not been SEEN to produce yet (interpreter still starting under
    # load) — legitimately quiet, and marking it stalled is correct, not a bug. The
    # claim being pinned is narrower: a child we have watched produce is never
    # slandered. `assert producing` keeps that from passing vacuously.
    producing = [beat for beat in beats if int(_field(beat, "outBytes")) > 0]
    assert producing, f"the child produced {len(lines)} lines but no beat saw any: {beats}"
    assert all(_field(beat, "stalled") == "false" for beat in producing), producing
    _assert_stalled_agrees_with_idle(beats, 0.5)
    seen = [int(_field(beat, "outBytes")) for beat in beats]
    assert seen == sorted(seen), seen
    assert seen[-1] > 0, seen


def test_idle_is_measured_from_the_byte_not_from_the_beat(tmp_path: Path) -> None:
    """``idle`` must time the child's silence, not the reporter's sampling.

    A child that emits once and then wedges is the shape that matters: if the
    progress timestamp is taken when the heartbeat PRINTS rather than when output
    is OBSERVED, the first beat reports ``idle=0.0s`` for a child that has already
    been quiet for nearly a full interval — a 20-second understatement at the
    default, told to exactly the callers who would set budgets from it. So the
    assertion is `elapsed - idle` (≈ when the byte landed), not a raw threshold.
    """
    interval = 0.6
    progress = io.StringIO()

    with redirect_stderr(progress):
        completed = run_streamed_command(
            [
                sys.executable,
                "-c",
                # Sleeping a QUARTER interval before the single byte is deliberate:
                # it aims the first producing beat's idle at ~0.75 interval, i.e.
                # between a correct threshold and a halved one, which is the only
                # place a wrong threshold becomes observable. Startup drift can move
                # it out of that band, costing detection but never causing a red.
                "import sys,time; time.sleep(0.15); sys.stdout.write('x');"
                " sys.stdout.flush(); time.sleep(1.5)",
            ],
            cwd=tmp_path,
            label_key="gate",
            label="one-byte-then-wedged",
            progress_prefix="[test]",
            heartbeat_interval=interval,
        )

    assert completed.returncode == 0
    beats = _heartbeats(progress.getvalue())
    producing = [beat for beat in beats if int(_field(beat, "outBytes")) > 0]
    assert producing, beats
    for beat in producing:
        elapsed = float(_field(beat, "elapsed").rstrip("s"))
        idle = float(_field(beat, "idle").rstrip("s"))
        # Sampling at print time pins this difference at EXACTLY one interval
        # (0.6s); sampling at observation time makes it the child's startup cost,
        # which is ~40ms idle but was measured at 0.3s under 20x oversubscription.
        # 0.75 leaves ~1.5x on both sides of those two populations. This threshold
        # is the whole test — halving or doubling it must still fail the mutant.
        assert elapsed - idle < interval * 0.75, beat
    # One byte does not buy indefinite grace: silence eventually reads as silence.
    # Deliberately NOT asserting that the first producing beat is un-stalled — that
    # holds only while beats stay one interval apart, and under load they drift. The
    # "a producing child is never slandered" half lives in the busy-child test, where
    # output is continuous and the claim survives a loaded machine.
    assert all(_field(beat, "stalled") == "true" for beat in producing[1:]), producing
    assert _field(beats[-1], "stalled") == "true", beats[-1]
    _assert_stalled_agrees_with_idle(beats, interval)


def test_large_dual_stream_output_is_drained_and_bounded(tmp_path: Path) -> None:
    completed = run_streamed_command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'o'*200000); sys.stderr.buffer.write(b'e'*200000)",
        ],
        cwd=tmp_path,
        label_key="producer",
        label="large-output",
        progress_prefix="[test]",
        heartbeat_interval=0.02,
        capture_limit=4096,
    )

    assert completed.returncode == 0
    assert completed.stdout == "o" * 4096
    assert completed.stderr == "e" * 4096


def test_signal_return_code_is_preserved(tmp_path: Path) -> None:
    completed = run_streamed_command(
        [
            sys.executable,
            "-c",
            "import os,signal; os.kill(os.getpid(), signal.SIGTERM)",
        ],
        cwd=tmp_path,
        label_key="gate",
        label="signal-test",
        progress_prefix="[test]",
        heartbeat_interval=0.02,
    )

    assert completed.returncode == -signal.SIGTERM
    assert os.WTERMSIG(-completed.returncode) == signal.SIGTERM


def test_progress_never_logs_raw_command_arguments(tmp_path: Path) -> None:
    secret = "password=SECRET-CANARY-9d61"
    progress = io.StringIO()

    with redirect_stderr(progress):
        completed = run_streamed_command(
            [sys.executable, "-c", "print('ok')", secret],
            cwd=tmp_path,
            label_key="producer",
            label="redaction-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
        )

    assert completed.returncode == 0
    assert secret not in progress.getvalue()
    assert "SECRET-CANARY" not in progress.getvalue()


def test_interrupt_terminates_child_process_group(tmp_path: Path, monkeypatch) -> None:
    pid_file = tmp_path / "pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )
    original_get = streaming_command.queue.Queue.get

    def interrupt_after_grandchild_started(self, timeout=None):
        deadline = time.monotonic() + 3
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not pid_file.exists():
            return original_get(self, timeout=timeout)
        raise KeyboardInterrupt

    monkeypatch.setattr(streaming_command.queue.Queue, "get", interrupt_after_grandchild_started)
    pids: dict[str, int] = {}
    try:
        with pytest.raises(KeyboardInterrupt):
            run_streamed_command(
                [sys.executable, "-c", child_script, str(pid_file)],
                cwd=tmp_path,
                label_key="gate",
                label="interrupt-test",
                progress_prefix="[test]",
                heartbeat_interval=0.02,
            )
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        for pid in pids.values():
            if _process_is_live(pid):
                os.kill(pid, signal.SIGKILL)


def test_interrupt_during_spawned_progress_terminates_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "early-pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )

    def _pids_written() -> dict[str, int] | None:
        """Parsed contents, or None. EXISTENCE is not the signal.

        The child does `open(path,'w').write(...)`, and `open(..., 'w')` creates the
        file before anything is written to it — so `pid_file.exists()` goes true with
        the file still empty, and the `json.loads` after the interrupt gets `''`.
        Measured: green in isolation, red under full-suite load, which is the window
        widening rather than a different bug.
        """
        try:
            return json.loads(pid_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    class InterruptOnSpawned(io.StringIO):
        def write(self, value: str) -> int:
            if "phase=spawned" in value:
                deadline = time.monotonic() + 3
                while _pids_written() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise KeyboardInterrupt
            return super().write(value)

    pids: dict[str, int] = {}
    try:
        with redirect_stderr(InterruptOnSpawned()), pytest.raises(KeyboardInterrupt):
            run_streamed_command(
                [sys.executable, "-c", child_script, str(pid_file)],
                cwd=tmp_path,
                label_key="gate",
                label="early-interrupt-test",
                progress_prefix="[test]",
                heartbeat_interval=0.02,
            )
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        if pids and any(_process_is_live(pid) for pid in pids.values()):
            try:
                os.killpg(pids["child"], signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_timeout_terminates_child_process_group(tmp_path: Path) -> None:
    pid_file = tmp_path / "timeout-pids.json"
    child_script = (
        "import json,os,subprocess,sys,time; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps({'child':os.getpid(),'grandchild':grandchild.pid})); "
        "time.sleep(60)"
    )
    pids: dict[str, int] = {}
    try:
        completed = run_streamed_command(
            [sys.executable, "-c", child_script, str(pid_file)],
            cwd=tmp_path,
            label_key="source",
            label="timeout-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
            # 這個預算不能貼著跑：下面 assert 之前要先讀 pid_file，而那要求 child 在
            # timeout 開火**之前**已經生出 grandchild 直譯器並寫完檔。實測那段要
            # 92-97ms（load average 20 的機器上，2026-08-06），原本的 0.1s 只剩
            # 3-8ms 餘裕 = 擲硬幣：機器閒時綠、有負載時 FileNotFoundError。
            # child 寫完後 sleep(60)，所以放寬預算不會讓 timeout 失去意義——它照樣
            # 在行程還活著時開火，被斷言的契約（逾時殺整個 process group）一字未改。
            timeout_seconds=1.5,
        )
        assert completed.returncode == 124
        pids = json.loads(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while any(_process_is_live(pid) for pid in pids.values()) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not any(_process_is_live(pid) for pid in pids.values())
    finally:
        for pid in pids.values():
            if _process_is_live(pid):
                os.kill(pid, signal.SIGKILL)


def test_timeout_kills_grandchild_after_group_leader_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "leader-exited-grandchild.pid"
    child_script = (
        "import subprocess,sys; "
        "grandchild=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(str(grandchild.pid))"
    )
    grandchild_pid = 0
    try:
        started = time.monotonic()
        completed = run_streamed_command(
            [sys.executable, "-c", child_script, str(pid_file)],
            cwd=tmp_path,
            label_key="source",
            label="leader-exited-timeout-test",
            progress_prefix="[test]",
            heartbeat_interval=0.02,
            # 同上：child 要先 spawn grandchild 並寫檔（實測 92-97ms）才輪得到下面
            # 讀 pid_file，0.1s 沒有餘裕。grandchild sleep(60)，所以 timeout 照樣
            # 在它活著時開火。
            timeout_seconds=1.5,
        )
        elapsed = time.monotonic() - started
        assert completed.returncode == 124
        # 界線跟著預算走：這條要擋的是「等完 grandchild 的 60s 才回來」，不是
        # 卡死一個特定毫秒數。1.5s 預算 + 收屍時間仍遠低於 5s。
        assert elapsed < 5
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        deadline = time.monotonic() + 2
        while _process_is_live(grandchild_pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not _process_is_live(grandchild_pid)
    finally:
        if grandchild_pid and _process_is_live(grandchild_pid):
            os.kill(grandchild_pid, signal.SIGKILL)


# ============================================================================
# the child's LC_CTYPE is CHOSEN, not inherited (IMP-20260808-3bbfa2)
#
# Measured 2026-08-08: `devops.sh:669` wrote `...目錄：$dest（已標記...）`. bash under
# a UTF-8 LC_CTYPE eats the first byte of the full-width `（` into the variable name,
# so `set -u` killed the script on `dest\xef: unbound variable` — inside the very
# message that was supposed to explain a failure. It passed eight runs by hand and
# failed 4/4 through the orchestrator, because CPython's PEP 538 coercion hands
# children `LC_CTYPE=C.UTF-8` while an interactive shell here leaves it unset. The
# same script took two different parse paths depending on who started it.
#
# The fix is not a value, it is the fact that the value is WRITTEN DOWN. These tests
# pin both the choice and — separately — that the choice is actually in force.
# ============================================================================

def _effective_ctype(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("LC_CTYPE="):
            return line.split("=", 1)[1].strip().strip('"')
    raise AssertionError(f"`locale` printed no LC_CTYPE:\n{text}")


def test_child_lc_ctype_is_chosen_by_the_tool_not_inherited(tmp_path, monkeypatch):
    """The caller's value is distinctive and must NOT come back out."""
    monkeypatch.setenv("LC_CTYPE", "en_US.ISO8859-1")
    with redirect_stderr(io.StringIO()):
        completed = run_streamed_command(
            [sys.executable, "-c",
             "import os,sys; sys.stdout.write(os.environ.get('LC_CTYPE','<unset>'))"],
            cwd=tmp_path, label_key="gate", label="ctype-probe",
            progress_prefix="[test]", heartbeat_interval=0.05,
        )
    # The literal, not just the module constant: comparing the child's value only to
    # `streaming_command.CHILD_LC_CTYPE` is self-consistent for ANY value, including
    # one someone changes by accident. A decision that can drift silently is not a
    # decision that was written down.
    assert completed.stdout == "C.UTF-8"
    assert streaming_command.CHILD_LC_CTYPE == "C.UTF-8"
    assert completed.stdout != "en_US.ISO8859-1"


def test_child_lc_ctype_choice_survives_a_caller_who_set_lc_all(tmp_path, monkeypatch):
    """The trap this pair exists for.

    POSIX makes `LC_ALL` outrank every `LC_*`, so setting `LC_CTYPE` next to an
    inherited `LC_ALL` produces a variable that reads back exactly as intended and
    has no effect whatsoever. Measured here: `LC_ALL=C LC_CTYPE=C.UTF-8` gives an
    effective ctype of `C`. `locale` is asked for the EFFECTIVE value precisely
    because the environment variable cannot testify about itself.
    """
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.delenv("LC_CTYPE", raising=False)
    with redirect_stderr(io.StringIO()):
        completed = run_streamed_command(
            ["/usr/bin/locale"],
            cwd=tmp_path, label_key="gate", label="ctype-effective",
            progress_prefix="[test]", heartbeat_interval=0.05,
        )
    assert completed.returncode == 0
    assert _effective_ctype(completed.stdout) == "C.UTF-8"


@pytest.mark.parametrize("caller_env", [
    pytest.param({}, id="bare-caller"),
    pytest.param({"LC_ALL": "C"}, id="caller-forced-LC_ALL-C"),
    pytest.param({"LC_CTYPE": "C"}, id="caller-forced-LC_CTYPE-C"),
])
def test_lc_ctype_choice_makes_children_parse_shell_the_strict_way(
        tmp_path, monkeypatch, caller_env):
    """What the value is FOR, asserted as behaviour rather than as a string.

    `C.UTF-8` is the stricter of the two available parses: it is the one under which
    `$VAR` abutting full-width punctuation is a fatal `unbound variable`, so a bug
    that only a UTF-8 locale can see is caught in the gate instead of in production.
    Under `C` the same line runs fine — which is why "whatever the caller happened to
    have" was never an acceptable answer. Three caller environments, one outcome.
    """
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_CTYPE", raising=False)
    for key, value in caller_env.items():
        monkeypatch.setenv(key, value)
    script = tmp_path / "fw.sh"
    script.write_text('set -u\ndest=hello\necho "dir: $dest（marked）"\n',
                      encoding="utf-8")
    with redirect_stderr(io.StringIO()):
        completed = run_streamed_command(
            ["bash", str(script)],
            cwd=tmp_path, label_key="gate", label="ctype-behaviour",
            progress_prefix="[test]", heartbeat_interval=0.05, merge_stderr=True,
        )
    assert completed.returncode != 0, (
        "the child parsed the full-width punctuation byte-wise, i.e. it did NOT get "
        f"the chosen UTF-8 ctype; output was {completed.stdout!r}")
    assert "unbound variable" in completed.stdout


def test_the_chosen_lc_ctype_is_visible_in_the_progress_stream(tmp_path):
    """Reproducing a gate failure means reproducing its environment, so the value has
    to be legible from a log someone already has — not only from the source."""
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        run_streamed_command(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path, label_key="gate", label="ctype-visible",
            progress_prefix="[test]", heartbeat_interval=0.05,
        )
    start = [ln for ln in stderr.getvalue().splitlines() if "phase=start" in ln]
    assert start, stderr.getvalue()
    assert "lcCtype=C.UTF-8" in start[0], start[0]


def test_an_explicit_env_argument_still_gets_the_chosen_lc_ctype(tmp_path):
    """`env=` replaces the whole environment, and the callers that use it are the
    orchestrator's git mutations — the ones whose parse must match the gates'."""
    with redirect_stderr(io.StringIO()):
        completed = run_streamed_command(
            [sys.executable, "-c",
             "import os,sys; g=os.environ.get; sys.stdout.write('|'.join("
             "(g('LC_CTYPE','<unset>'), g('CANARY','<unset>'), g('LC_ALL','<unset>'))))"],
            cwd=tmp_path, label_key="gate", label="ctype-explicit-env",
            progress_prefix="[test]", heartbeat_interval=0.05,
            env={"CANARY": "kept", "LC_ALL": "C"},
        )
    # The caller's own variables survive; only the locale decision is overridden.
    # `LC_ALL` is asserted explicitly rather than left implied: without it this test
    # stays green when the `pop` is deleted (verified by mutation), which would leave
    # the explicit-`env=` path — the one `_git_mutation` uses — with no assertion at
    # all that the chosen ctype is in force rather than merely present.
    assert completed.stdout == "C.UTF-8|kept|<unset>"
