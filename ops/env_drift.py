#!/usr/bin/env -S uv run --python 3.13
"""Offline-testable local/remote .env drift checker.

The shell entrypoint supplies paths and the server identity; this module owns
parsing and comparison so it can be tested without sourcing a production shell
dispatch or embedding a second Python program in it.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple


UNSAFE_FLAGS = (
    "APP_STORE_ALLOW_UNSIGNED_SYNC",
    "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS",
)

HOST_SPECIFIC = {
    "APP_STORE_ROOT_CA_PATH": ("certs", "{container_root}/certs"),
    "APP_STORE_CONNECT_PRIVATE_KEY_PATH": ("certs", "{container_root}/certs"),
}


def parse_env_text(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def env_flag_truthy(value: str) -> bool:
    """Whether the backend would read this decoded value as ON.

    `value` is what Compose hands the container (see `ComposeEnv`), not the raw
    .env token.  Mirrors backend/src/kg/settings.py `_env_truthy` (pinned by
    ops/tests/test_env_check.py).
    """
    return value.strip().lower() in {"1", "true", "yes"}


class EnvDecodeError(ValueError):
    """A .env value whose Compose-decoded form cannot be determined with confidence.

    The message names lines, keys and variable names only, never a value.
    """


class _Assignment(NamedTuple):
    lineno: int
    key: str
    # Text after the first '=' or ':', leading blanks kept (they delimit a comment);
    # None for a bare `KEY` line, whose value Compose takes from the host's own env.
    raw: str | None


_NAME = r"[A-Za-z_][A-Za-z0-9_]*"
# `$$`, `${NAME}`, `${NAME:-default}`, `${NAME-default}`, `$NAME`.  A default may not
# itself contain `$`, `{` or `}` (nested expressions are not decoded).
_INTERPOLATION = re.compile(
    r"\$(?:(?P<escaped>\$)"
    r"|\{(?P<braced>" + _NAME + r")(?:(?P<op>:?-)(?P<default>[^${}]*))?\}"
    r"|(?P<bare>" + _NAME + r"))"
)


def parse_env_assignments(text: str) -> list[_Assignment]:
    """Assignments in the key spellings Compose's env_file reader accepts.

    Unlike `parse_env_text` (raw text, for env-drift comparison), an optional
    leading `export` and blanks around the key are dropped and the first `=` *or*
    `:` splits key from value, so `export K=v`, `K = v` and `K: v` all name `K`.
    A line with neither separator is a bare `KEY` (raw is None).
    """
    assignments: list[_Assignment] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sep = re.search(r"[=:]", line)
        key = re.sub(r"^export\s+", "", line[: sep.start()].strip() if sep else line)
        assignments.append(_Assignment(lineno, key, line[sep.end() :] if sep else None))
    return assignments


class ComposeEnv:
    """Values of a .env body as `docker compose` env_file hands them to the container.

    Decoded (verified against `docker compose config`, v2.40.3):
    - unquoted: an inline comment starts at whitespace + `#` (so `KEY= # note` is
      empty; Compose versions differ there and empty is the conservative reading);
      the rest is trimmed and interpolated;
    - double-quoted: interpolated; single-quoted: literal; only whitespace or a
      `#` comment may follow the closing quote;
    - interpolation: `$$`, `$NAME`, `${NAME}`, `${NAME:-d}` (unset or empty),
      `${NAME-d}` (unset).  A name resolves from an earlier line of the same file,
      then from `environ`.  The process env checked is that of the env-check run;
      the Compose host's own process env cannot be observed from here.
    - the last assignment of a key wins.

    Anything else raises `EnvDecodeError` instead of guessing, so callers fail
    closed: other `$` forms (`${NAME:?e}`, `${NAME:+x}`, nested defaults, a lone
    `$`), unterminated quotes (possibly multi-line), backslashes inside quotes,
    text after a closing quote, undefined names without a default, names defined
    only on a later line or differently in file and environment, and a bare `KEY`
    line (Compose then reads the Compose host's own environment).
    """

    def __init__(self, text: str, environ: Mapping[str, str] | None = None) -> None:
        self._entries = parse_env_assignments(text)
        self._environ = os.environ if environ is None else environ
        self._decoded: dict[int, str] = {}

    def get(self, key: str) -> str | None:
        """Decoded value of `key`, or None when it is never assigned."""
        for index in range(len(self._entries) - 1, -1, -1):
            if self._entries[index].key == key:
                return self._decode(index)
        return None

    def _decode(self, index: int) -> str:
        if index not in self._decoded:
            entry = self._entries[index]
            try:
                self._decoded[index] = self._decode_raw(entry.raw, index)
            except EnvDecodeError as exc:
                raise EnvDecodeError(f"第 {entry.lineno} 行：{exc}") from None
        return self._decoded[index]

    def _decode_raw(self, raw: str | None, index: int) -> str:
        if raw is None:
            raise EnvDecodeError("只有 KEY、沒有值：Compose 會改取執行主機的環境變數")
        body = raw.lstrip()
        if body[:1] in {"'", '"'}:
            quote = body[0]
            end = body.find(quote, 1)
            if end == -1:
                raise EnvDecodeError("引號未結束（可能是多行值）")
            inner, rest = body[1:end], body[end + 1 :].strip()
            if "\\" in inner:
                raise EnvDecodeError("引號內含反斜線，跳脫結果無法確認")
            if rest and not rest.startswith("#"):
                raise EnvDecodeError("結尾引號後有多餘內容")
            return inner if quote == "'" else self._expand(inner, index)
        comment = re.search(r"\s#", raw)
        return self._expand((raw[: comment.start()] if comment else raw).strip(), index)

    def _expand(self, text: str, index: int) -> str:
        parts: list[str] = []
        pos = 0
        while (at := text.find("$", pos)) != -1:
            parts.append(text[pos:at])
            ref = _INTERPOLATION.match(text, at)
            if ref is None:
                raise EnvDecodeError(
                    "不支援的 $ 用法（只解析 $NAME、${NAME}、${NAME:-預設}、"
                    "${NAME-預設}、$$；字面 $ 請寫 $$ 或改用單引號）"
                )
            parts.append(self._interpolate(ref, index))
            pos = ref.end()
        parts.append(text[pos:])
        return "".join(parts)

    def _interpolate(self, ref: re.Match[str], index: int) -> str:
        if ref["escaped"]:
            return "$"
        name = ref["braced"] or ref["bare"]
        value = self._lookup(name, index)
        op = ref["op"]
        if op is None:
            if value is None:
                raise EnvDecodeError(f"變數 {name} 未定義且沒有預設值")
            return value
        if value is None or (op == ":-" and value == ""):
            return ref["default"]
        return value

    def _lookup(self, name: str, index: int) -> str | None:
        if any(entry.key == name for entry in self._entries[index + 1 :]):
            raise EnvDecodeError(
                f"變數 {name} 在較後的行才定義，各 Compose 版本的求值順序不一致"
            )
        earlier = [i for i in range(index) if self._entries[i].key == name]
        in_file = self._decode(earlier[-1]) if earlier else None
        in_env = self._environ.get(name)
        if in_file is not None and in_env is not None and in_file != in_env:
            raise EnvDecodeError(
                f"變數 {name} 在 .env 與環境中的值不同，無法確認採用哪個"
            )
        return in_file if in_file is not None else in_env


class EnvVerdict(NamedTuple):
    missing: list[str]
    unsafe: list[str]
    undecodable: dict[str, str]  # key -> why its value cannot be decoded


def check_env_text(
    text: str,
    required: Iterable[str],
    flags: Iterable[str] = UNSAFE_FLAGS,
    environ: Mapping[str, str] | None = None,
) -> EnvVerdict:
    """Judge a .env body by the values Compose passes to the container.

    A key whose value cannot be decoded confidently is reported in `undecodable`
    and counts as neither present nor safe: callers must treat it as a failure.
    """
    required, flags = list(required), list(flags)
    env = ComposeEnv(text, environ)
    values: dict[str, str | None] = {}
    undecodable: dict[str, str] = {}
    for key in dict.fromkeys([*required, *flags]):
        try:
            values[key] = env.get(key)
        except EnvDecodeError as exc:
            undecodable[key] = str(exc)
    missing = [
        key for key in required if key in values and not (values[key] or "").strip()
    ]
    unsafe = [
        key for key in flags if key in values and env_flag_truthy(values[key] or "")
    ]
    return EnvVerdict(missing, unsafe, undecodable)


def env_check_main(required: list[str]) -> int:
    """`env-check KEY...`: .env text on stdin; prints per-key verdicts."""
    text = sys.stdin.read()
    verdict = check_env_text(text, required)
    for key in required:
        if key in verdict.undecodable:
            print(f"✗ {key} (無法解析：{verdict.undecodable[key]})")
        else:
            print(f"✗ {key} (缺少)" if key in verdict.missing else f"✓ {key}")
    for key in UNSAFE_FLAGS:
        if key in verdict.undecodable:
            print(f"✗ {key} (無法解析：{verdict.undecodable[key]})")
        else:
            print(
                f"✗ {key} (production 不可啟用)"
                if key in verdict.unsafe
                else f"✓ {key}"
            )
    if verdict.missing:
        print(
            f"✗ 缺少必要環境變數：{' '.join(verdict.missing)}，請手動 SSH 更新 .env 後重試",
            file=sys.stderr,
        )
    if verdict.unsafe:
        print(
            f"✗ 偵測到不安全的 App Store fallback 開關：{' '.join(verdict.unsafe)}，production 請移除或設為 false",
            file=sys.stderr,
        )
    if verdict.undecodable:
        print(
            f"✗ 無法確認下列 .env 值 Compose 會傳給容器的內容（fail closed）：{' '.join(verdict.undecodable)}，請改成可明確解析的寫法後重試",
            file=sys.stderr,
        )
    return 1 if verdict.missing or verdict.unsafe or verdict.undecodable else 0


def _read_local(path: Path) -> dict[str, str]:
    if not path.exists():
        raise SystemExit(f"✗ 本地 .env 不存在：{path}")
    return parse_env_text(path.read_text(encoding="utf-8"))


def _read_remote(path: str, server: str) -> dict[str, str]:
    ssh_bin = os.environ.get("KG_SSH_BIN", "ssh")
    proc = subprocess.run(
        [
            ssh_bin,
            "-T",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "BatchMode=yes",
            server,
            f"cat -- {shlex.quote(path)}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"✗ 無法讀取遠端 .env：{proc.stderr.strip()}")
    return parse_env_text(proc.stdout)


def compare_envs(
    local: dict[str, str],
    remote: dict[str, str],
    *,
    local_dir: Path,
    container_root: str,
) -> list[tuple[str, str, str, str]]:
    mismatches: list[tuple[str, str, str, str]] = []
    for key in sorted(set(local) & set(remote)):
        lv, rv = local[key], remote[key]
        if key in HOST_SPECIFIC:
            local_base = local_dir / HOST_SPECIFIC[key][0]
            remote_base = HOST_SPECIFIC[key][1].format(container_root=container_root)
            if not lv.startswith(str(local_base) + "/"):
                mismatches.append((key, lv, rv, f"本地值應位於 {local_base}/ 下"))
                continue
            if not rv.startswith(remote_base + "/"):
                mismatches.append((key, lv, rv, f"遠端值應位於 {remote_base}/ 下"))
                continue
            if Path(lv).name != Path(rv).name:
                mismatches.append((key, lv, rv, "本地與遠端指向的檔名不同"))
        elif lv != rv:
            mismatches.append((key, lv, rv, "值不同"))
    return mismatches


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "env-check":
        return env_check_main(argv[2:])
    if len(argv) != 6:
        print(
            "usage: env_drift.py LOCAL_ENV REMOTE_ENV LOCAL_DIR CONTAINER_ROOT SERVER",
            file=sys.stderr,
        )
        return 64
    local_path, remote_path, local_dir, container_root, server = argv[1:]
    local = _read_local(Path(local_path))
    remote = _read_remote(remote_path, server)
    missing_remote = sorted(set(local) - set(remote))
    missing_local = sorted(set(remote) - set(local))
    mismatches = compare_envs(
        local,
        remote,
        local_dir=Path(local_dir).resolve(),
        container_root=container_root,
    )
    if missing_remote or missing_local or mismatches:
        if missing_remote:
            print("✗ 遠端缺少以下 key:")
            for key in missing_remote:
                print(f"  - {key}")
        if missing_local:
            print("✗ 本地缺少以下 key:")
            for key in missing_local:
                print(f"  - {key}")
        if mismatches:
            print("✗ 本地/遠端 .env 存在不一致:")
            for key, lv, rv, reason in mismatches:
                print(f"  - {key}: {reason}")
                print(f"      local : {lv}")
                print(f"      remote: {rv}")
        return 1
    print("✓ 本地/遠端 .env 已一致（host-specific path key 已正規化檢查）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
