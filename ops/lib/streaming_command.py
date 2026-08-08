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
    """
    if heartbeat_interval <= 0:
        raise ValueError("heartbeat_interval must be positive")
    if capture_limit <= 0:
        raise ValueError("capture_limit must be positive")
    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    print(
        f"{progress_prefix} {label_key}={label} phase=start elapsed=0.0s "
        f"pid=not-spawned alive=false argCount={len(command)}",
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
        env=env,
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
    return subprocess.CompletedProcess(command, returncode, stdout, stderr)


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
