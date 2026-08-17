from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.kg_board.thread_mirror import collect_thread_mirror, normalise_thread_mirror


def test_normalise_thread_mirror_keeps_mutable_title_separate_from_thread_id():
    payload = normalise_thread_mirror({
        "complete": True,
        "threads": [{
            "id": "thread-a",
            "name": "改名後的 Agent",
            "parentThreadId": "thread-parent",
            "sessionId": "session-root",
            "agentNickname": "Dewey",
            "agentRole": "subagent",
            "status": {"type": "active"},
        }],
    })

    assert payload["complete"] is True
    assert payload["threads"] == [{
        "thread_id": "thread-a",
        "title": "改名後的 Agent",
        "parent_thread_id": "thread-parent",
        "session_id": "session-root",
        "nickname": "Dewey",
        "role": "subagent",
        "status": "active",
    }]


def test_collect_thread_mirror_uses_read_only_thread_read(tmp_path):
    fake = tmp_path / "fake-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "while IFS= read -r line; do\n"
        "  case \"$line\" in\n"
        "    *initialize*) printf '%s\\n' '{\"id\":1,\"result\":{}}' ;;\n"
        "    *thread/read*) id=$(printf '%s' \"$line\" | sed -E 's/.*\\\"id\\\": ([0-9]+).*/\\1/'); printf '%s\\n' \"{\\\"id\\\":$id,\\\"result\\\":{\\\"thread\\\":{\\\"id\\\":\\\"thread-a\\\",\\\"name\\\":\\\"Renamed\\\",\\\"status\\\":{\\\"type\\\":\\\"active\\\"},\\\"agentRole\\\":\\\"subagent\\\"}}}\" ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    payload = collect_thread_mirror(["thread-a"], codex_bin=str(fake), timeout=2)

    assert payload["complete"] is True
    assert payload["threads"] == [{
        "thread_id": "thread-a",
        "title": "Renamed",
        "role": "subagent",
        "status": "active",
    }]


def test_thread_error_makes_the_whole_mirror_incomplete(tmp_path):
    fake = tmp_path / "error-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "while IFS= read -r line; do\n"
        "  case \"$line\" in\n"
        "    *initialize*) printf '%s\\n' '{\"id\":1,\"result\":{}}' ;;\n"
        "    *thread/read*) printf '%s\\n' '{\"id\":2,\"error\":{\"message\":\"thread missing\"}}' ;;\n"
        "  esac\n"
        "done\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    payload = collect_thread_mirror(["thread-a"], codex_bin=str(fake), timeout=2)

    assert payload["complete"] is False
    assert "thread missing" in payload["error"]
    assert payload["threads"][0]["status"] == "unavailable"


def test_normalise_thread_mirror_rejects_rows_with_errors():
    payload = normalise_thread_mirror({
        "complete": True,
        "threads": [{
            "thread_id": "thread-a", "status": "unavailable", "error": "gone",
        }],
    })

    assert payload["complete"] is False
    assert "thread-a" in payload["error"]


def test_collect_thread_mirror_fails_closed_when_app_server_closes_stdout(tmp_path):
    fake = tmp_path / "closed-codex"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'not-json'\n"
        "sleep 0.05\n"
        "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)

    payload = collect_thread_mirror(["thread-a"], codex_bin=str(fake), timeout=0.2)

    assert payload["complete"] is False
    assert payload["error"]
