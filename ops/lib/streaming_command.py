"""Bounded subprocess capture with machine-output-safe progress heartbeats."""

from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import BinaryIO


# The ctype every child of this runner gets. THIS VALUE IS CHOSEN, NOT INHERITED —
# that is the whole point of it existing, and the reason it is a named constant
# rather than a line in the code below.
#
# Measured 2026-08-08 (IMP-20260808-3bbfa2): `devops.sh` died on
# `dest\xef: unbound variable` through the gate and ran clean eight times by hand.
# bash under a UTF-8 ctype reads the first byte of a full-width `（` as part of the
# variable name; under `C` it stops at the byte boundary and the line is harmless.
# Which path a script took depended on WHO STARTED IT: an interactive shell here
# leaves LC_CTYPE unset (C), while CPython's PEP 538 coercion sets `C.UTF-8` before
# spawning anything. So the tool and the human were running different parsers, and
# the diff between them was invisible in every log either one produced.
#
# `C.UTF-8` is the stricter of the two and matches what the gate already ran under,
# so this pins today's gate behaviour rather than changing it. Strictness is the
# tie-breaker: the strict parse fails on things the permissive one waves through, and
# a gate that is more permissive than a user's terminal is a gate that ships the bug.
CHILD_LC_CTYPE = "C.UTF-8"


def _child_env(env: dict[str, str] | None) -> dict[str, str]:
    """The child's environment with the locale decision made explicitly.

    `LC_ALL` is REMOVED, not left alone, and that is load-bearing: POSIX makes
    `LC_ALL` outrank every `LC_*`, so setting `LC_CTYPE` beside an inherited
    `LC_ALL` yields a variable that reads back exactly as intended and changes
    nothing. Measured: `LC_ALL=C LC_CTYPE=C.UTF-8` gives an effective ctype of `C`.
    Leaving it would reintroduce the exact disease — an invisible, caller-dependent
    difference in how children parse — while looking like the cure.

    Dropping it does let the caller's other categories (messages, time, numeric) fall
    back to their own `LC_*`/`LANG`, which is what they would have been without an
    `LC_ALL` at all. That is a deliberate, bounded trade: none of those categories
    changes how a shell tokenizes a script, and ctype is the one that does.
    """
    resolved = dict(os.environ if env is None else env)
    resolved.pop("LC_ALL", None)
    resolved["LC_CTYPE"] = CHILD_LC_CTYPE
    return resolved


def _terminate_process_group(proc: subprocess.Popen[bytes], timeout: float = 5.0) -> None:
    """Terminate the isolated child session, escalating to KILL at deadline."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        proc.wait()
        return

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return

    # The group leader may exit before a descendant that ignored SIGTERM.
    # Reap the leader, then make one final group-wide KILL attempt so no child
    # can keep inherited stdout/stderr pipes open.
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_streamed_command(
    command: list[str],
    *,
    cwd: Path | str,
    label_key: str,
    label: str,
    progress_prefix: str,
    heartbeat_interval: float = 20.0,
    capture_limit: int = 8 * 1024 * 1024,
    merge_stderr: bool = False,
    timeout_seconds: float | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a child with bounded capture and periodic progress on parent stderr.

    The child pipes are continuously drained through a bounded queue, preventing
    pipe-buffer deadlock. Only the final ``capture_limit`` bytes per stream are kept.
    Parent stdout is never written, so callers can retain a single-JSON contract.

    Each heartbeat also reports whether the child is *moving*, not merely present:
    ``outBytes`` is the cumulative child output observed so far — stdout and stderr
    COMBINED, since either one advancing means the child is alive and working —
    ``idle`` the time since output last advanced, and ``stalled=true`` means a whole
    heartbeat interval passed without a single byte on either stream. ``alive=true`` cannot carry this — a wedged child
    and a working one are indistinguishable by existence alone. Nothing here kills
    anything: ``stalled`` is exposed so callers can decide, and a caller that wants a
    hard ceiling still uses ``timeout_seconds``. Silence is not always failure (lock
    waits and slow downloads are legitimately quiet), so wiring ``stalled`` to a
    verdict requires per-call-site evidence that its quiet periods are bounded.

    ``env`` replaces the child's whole environment when given (``None`` inherits).
    It exists because some inherited variables are hazards rather than context: a
    child that opens an interactive editor blocks forever behind a pipe nobody is
    reading, and `git -c core.editor=...` cannot prevent that — ``GIT_EDITOR``
    outranks it. A caller that must not be interrupted has no other way to say so.

    Either way the child's ``LC_CTYPE`` is this module's choice, not the caller's —
    see ``CHILD_LC_CTYPE`` and ``_child_env`` for why that is not a detail.

    The returned ``CompletedProcess`` carries two extra attributes: ``elapsed_s`` is
    this runner's monotonic wall time, and ``timed_out`` is True iff THIS function
    enforced ``timeout_seconds``. ``returncode == 124`` cannot answer the latter — a
    child may exit 124 by itself — see the assignments at the end of this function.
    """
    if heartbeat_interval <= 0:
        raise ValueError("heartbeat_interval must be positive")
    if capture_limit <= 0:
        raise ValueError("capture_limit must be positive")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    print(
        # `lcCtype` is appended last, after the fields downstream greps already
        # match unanchored. It is here because reproducing a gate failure means
        # reproducing its environment, and the operator reading this line usually
        # has the log and not the source.
        f"{progress_prefix} {label_key}={label} phase=start elapsed=0.0s "
        f"pid=not-spawned alive=false argCount={len(command)} "
        f"lcCtype={CHILD_LC_CTYPE}",
        file=sys.stderr,
        flush=True,
    )
    started = time.monotonic()
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
        start_new_session=True,
        env=_child_env(env),
    )
    streams: dict[str, BinaryIO | None] = {}
    readers: list[threading.Thread] = []
    try:
        print(
            f"{progress_prefix} {label_key}={label} phase=spawned "
            f"elapsed={time.monotonic() - started:.1f}s pid={proc.pid} alive=true",
            file=sys.stderr,
            flush=True,
        )

        chunks: queue.Queue[tuple[str, bytes | None]] = queue.Queue(maxsize=16)
        streams = {"stdout": proc.stdout}
        if not merge_stderr:
            streams["stderr"] = proc.stderr

        def drain(stream_name: str) -> None:
            pipe = streams[stream_name]
            assert pipe is not None
            try:
                while True:
                    # ``read1``, not ``read``: BufferedReader.read(n) blocks until it
                    # has n bytes or EOF, so a child emitting less than 64 KiB hands
                    # the parent nothing until it exits. That is invisible while the
                    # only question is "what was the tail", and fatal once output is
                    # the progress signal — every low-volume child would read as
                    # stalled. ``read1`` returns whatever one raw read yields; it
                    # exists because Popen's default ``bufsize=-1`` makes these pipes
                    # BufferedReaders. An unbuffered ``bufsize=0`` would hand back
                    # raw FileIO objects, which have no ``read1``.
                    chunk = pipe.read1(64 * 1024)
                    if not chunk:
                        break
                    chunks.put((stream_name, chunk))
            except (OSError, ValueError):
                pass
            finally:
                chunks.put((stream_name, None))

        for stream_name in streams:
            reader = threading.Thread(
                target=drain,
                args=(stream_name,),
                name=f"stream-{label}-{stream_name}",
                daemon=True,
            )
            readers.append(reader)
            reader.start()

        tails = {stream_name: bytearray() for stream_name in streams}
        open_streams = set(streams)
        next_heartbeat = started + heartbeat_interval
        deadline = started + timeout_seconds if timeout_seconds is not None else None
        timed_out = False
        bytes_seen = 0
        last_progress_bytes = 0
        last_progress_at = started
        while open_streams:
            now = time.monotonic()
            timeout = max(0.001, next_heartbeat - now)
            if deadline is not None:
                timeout = min(timeout, max(0.001, deadline - now))
            try:
                stream_name, chunk = chunks.get(timeout=timeout)
            except queue.Empty:
                stream_name, chunk = "", b""
            if chunk is None:
                open_streams.discard(stream_name)
            elif chunk:
                bytes_seen += len(chunk)
                tail = tails[stream_name]
                tail.extend(chunk)
                if len(tail) > capture_limit:
                    del tail[:-capture_limit]

            now = time.monotonic()
            if bytes_seen > last_progress_bytes:
                # Timestamp progress where it is OBSERVED, not where it is reported.
                # Sampling this only at heartbeat time makes ``idle`` under-report
                # real silence by up to a whole interval — measured: a child that
                # went quiet at t=0.02s still printed idle=0.0s at the t=0.5s beat,
                # which at the default interval is a 20-second lie told to exactly
                # the callers who exist to set budgets from this number. It also
                # keeps ``stalled`` an honest predicate instead of one that is true
                # only because heartbeats happen never to fire early.
                last_progress_bytes = bytes_seen
                last_progress_at = now
            if deadline is not None and now >= deadline:
                # The group leader may have exited while a descendant still
                # owns inherited pipes. The open-stream deadline applies to
                # the whole isolated process group, not just ``proc``.
                _terminate_process_group(proc)
                timed_out = True
                deadline = None
            if now >= next_heartbeat and open_streams:
                alive = str(proc.poll() is None).lower()
                idle = now - last_progress_at
                # The progress fields are appended AFTER the existing ones: downstream
                # greps match an unanchored `... pid=N alive=true` prefix and must
                # keep matching.
                stalled = str(idle >= heartbeat_interval).lower()
                print(
                    f"{progress_prefix} {label_key}={label} phase=heartbeat "
                    f"elapsed={now - started:.1f}s pid={proc.pid} alive={alive} "
                    # ``idle`` prints 2dp while ``elapsed`` keeps 1dp on purpose: at
                    # 1dp a 0.48s idle renders as `stalled=false idle=0.5s` against a
                    # 0.5s interval, a line that contradicts itself. Rounding noise is
                    # tolerable in a duration; a self-contradicting line is not.
                    f"stalled={stalled} outBytes={bytes_seen} idle={idle:.2f}s",
                    file=sys.stderr,
                    flush=True,
                )
                next_heartbeat = now + heartbeat_interval
        returncode = proc.wait()
        if timed_out:
            returncode = 124
    except BaseException:
        _terminate_process_group(proc)
        for pipe in streams.values():
            if pipe is not None:
                pipe.close()
        raise
    finally:
        for reader in readers:
            reader.join(timeout=1)

    elapsed = time.monotonic() - started
    print(
        f"{progress_prefix} {label_key}={label} phase=done elapsed={elapsed:.1f}s "
        f"pid={proc.pid} alive=false rc={returncode}",
        file=sys.stderr,
        flush=True,
    )
    stdout = tails["stdout"].decode("utf-8", errors="replace")
    stderr = None if merge_stderr else tails["stderr"].decode("utf-8", errors="replace")
    result = subprocess.CompletedProcess(command, returncode, stdout, stderr)
    # Preserve the exact monotonic value that produced the done heartbeat. Re-parsing
    # its one-decimal rendering would discard the precision needed by short gates.
    result.elapsed_s = elapsed
    # The one fact only this function knows, stated instead of left to be inferred.
    #
    # `returncode == 124` is what this runner writes when IT enforced the deadline
    # — and it is also a number a child may exit with on its own, immediately. The
    # two are the same integer, so a caller that must distinguish "did not answer"
    # from "answered no" has nothing to key on but elapsed time, which is a guess
    # about scheduling. That is the shape of assertion this repo keeps filing
    # entries about: one satisfied by something other than its subject.
    #
    # An attribute rather than a wider return type: every existing caller unpacks
    # a CompletedProcess (rc / stdout / stderr) and none of them break by gaining
    # a field. It is set unconditionally, including when no deadline was given, so
    # reading it never needs a `getattr` default that would re-open the same hole.
    result.timed_out = timed_out
    return result


def _capture_cli(argv: list[str] | None = None) -> int:
    """Expose the runner to shell control planes without polluting stdout."""
    parser = argparse.ArgumentParser(description="capture a command with visible progress")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--heartbeat-interval", type=float, default=20.0)
    parser.add_argument("--timeout-seconds", type=float)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a child command is required after --")

    result = run_streamed_command(
        command,
        cwd=args.cwd,
        label_key="source",
        label=args.label,
        progress_prefix="[ios][progress]",
        heartbeat_interval=args.heartbeat_interval,
        timeout_seconds=args.timeout_seconds,
    )
    sys.stdout.write(result.stdout)
    sys.stdout.flush()
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(_capture_cli())
