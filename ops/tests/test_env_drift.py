from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import env_drift  # noqa: E402

# A fake ssh that, like the real one, hands the final remote command string to
# a shell.  The first non-option arguments are the server and the command.
_FAKE_SSH = """#!/bin/sh
while [ "$#" -gt 0 ]; do
  case "$1" in
    -o) shift 2 ;;
    -T) shift ;;
    --) shift; break ;;
    *) break ;;
  esac
done
shift  # server
exec /bin/sh -c "$*"
"""


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    binary = tmp_path / "fake-ssh"
    binary.write_text(_FAKE_SSH, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("KG_SSH_BIN", str(binary))
    return tmp_path


def test_ordinary_remote_path_is_read(fake_ssh: Path) -> None:
    env_file = fake_ssh / "remote.env"
    env_file.write_text("SAFE=value\n", encoding="utf-8")

    assert env_drift._read_remote(str(env_file), "fixture") == {"SAFE": "value"}


def test_remote_path_with_spaces_is_read(fake_ssh: Path) -> None:
    directory = fake_ssh / "dir with spaces"
    directory.mkdir()
    env_file = directory / "remote.env"
    env_file.write_text("SPACED=yes\n", encoding="utf-8")

    assert env_drift._read_remote(str(env_file), "fixture") == {"SPACED": "yes"}


@pytest.mark.parametrize(
    "template",
    [
        "{env}; touch {mark}",
        "{env} && touch {mark}",
        "{env} $(touch {mark})",
        "{env} `touch {mark}`",
        "{env}\ntouch {mark}",
        "{env} | touch {mark}",
        "{env} > {mark}",
    ],
    ids=["semicolon", "and", "subst", "backtick", "newline", "pipe", "redirect"],
)
def test_remote_path_is_data_not_shell_syntax(fake_ssh: Path, template: str) -> None:
    env_file = fake_ssh / "remote.env"
    env_file.write_text("SAFE=value\n", encoding="utf-8")
    mark = fake_ssh / "injected"

    hostile = template.format(env=env_file, mark=mark)
    try:
        env_drift._read_remote(hostile, "fixture")
    except SystemExit:
        pass  # a path that does not exist must fail, never execute

    assert not mark.exists(), f"remote path executed shell syntax: {hostile!r}"


def test_remote_failure_still_exits_with_message(fake_ssh: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        env_drift._read_remote(str(fake_ssh / "missing.env"), "fixture")

    assert "無法讀取遠端 .env" in str(raised.value)


def test_option_like_remote_path_is_not_a_cat_flag(fake_ssh: Path) -> None:
    with pytest.raises(SystemExit):
        env_drift._read_remote("--version", "fixture")


# ── compare_envs: host-path layout (#2314) ──────────────────────────────────
# .env 放 host 路徑（docs/sop/deploy.md）；devops.sh 傳入遠端 repo 真實目錄當 container_root。
_KEYS = ("APP_STORE_ROOT_CA_PATH", "APP_STORE_CONNECT_PRIVATE_KEY_PATH")


def _compare(local_path: str, remote_path: str) -> list[tuple[str, str, str, str]]:
    local = dict.fromkeys(_KEYS, local_path)
    remote = dict.fromkeys(_KEYS, remote_path)
    return env_drift.compare_envs(
        local,
        remote,
        local_dir=Path("/Users/x/kg/backend"),
        container_root="/Users/y/kg-prod/backend",
    )


def test_compare_envs_host_path_layout_has_no_drift() -> None:
    assert (
        _compare(
            "/Users/x/kg/backend/certs/AuthKey_X.p8",
            "/Users/y/kg-prod/backend/certs/AuthKey_X.p8",
        )
        == []
    )


def test_compare_envs_host_path_different_filename_is_drift_per_key() -> None:
    mismatches = _compare(
        "/Users/x/kg/backend/certs/AuthKey_X.p8",
        "/Users/y/kg-prod/backend/certs/AuthKey_Y.p8",
    )
    assert sorted(m[0] for m in mismatches) == sorted(_KEYS)


def test_compare_envs_remote_path_outside_certs_is_drift() -> None:
    mismatches = _compare(
        "/Users/x/kg/backend/certs/AuthKey_X.p8", "/app/certs/AuthKey_X.p8"
    )
    assert sorted(m[0] for m in mismatches) == sorted(_KEYS)
