"""Print the deterministic digest of the source tree rooted at the current directory.

Runs inside the Felix sandbox so the receipt's claimed tree digest has an
independent in-sandbox corroboration.  The algorithm is the one used by
``lib.compute_capsule`` (length-prefixed relative path and bytes, sorted).
Read-only; no network, no environment, no writes.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def tree_digest(root: Path) -> tuple[str, int]:
    files: list[tuple[str, bytes]] = []
    for current, directories, names in os.walk(root, followlinks=False):
        directories.sort()
        for name in names:
            path = Path(current) / name
            if path.is_symlink() or not path.is_file():
                raise SystemExit(f"non-regular file: {path.relative_to(root)}")
            files.append((path.relative_to(root).as_posix(), path.read_bytes()))
    files.sort()
    digest = hashlib.sha256()
    for relative, data in files:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest(), len(files)


def main() -> int:
    digest, count = tree_digest(Path.cwd())
    print(
        json.dumps(
            {"schema": "kg.source_identity.v1", "tree_sha256": digest, "files": count},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
