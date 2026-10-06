"""Immutable bulk branch-ref observations used by inventory projection."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import InvalidReceipt

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class BranchInventory:
    local: tuple[tuple[str, str], ...] = ()
    remote: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        for label, rows in (("local", self.local), ("remote", self.remote)):
            if type(rows) is not tuple:
                raise InvalidReceipt(f"{label} branch inventory must be a tuple")
            names: list[str] = []
            for row in rows:
                if (
                    type(row) is not tuple
                    or len(row) != 2
                    or type(row[0]) is not str
                    or not row[0]
                    or any(
                        ord(character) < 32 or ord(character) == 127
                        for character in row[0]
                    )
                    or type(row[1]) is not str
                    or not _SHA_RE.fullmatch(row[1])
                ):
                    raise InvalidReceipt(f"{label} branch inventory row is malformed")
                names.append(row[0])
            if len(names) != len(set(names)):
                raise InvalidReceipt(f"{label} branch inventory contains duplicates")

    @property
    def local_by_name(self) -> dict[str, str]:
        return dict(self.local)

    @property
    def remote_by_name(self) -> dict[str, str]:
        return dict(self.remote)
