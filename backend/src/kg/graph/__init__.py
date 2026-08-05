"""Graph storage for card relationships.

Public surface preserved for ``from kg.graph import X`` callers. The
implementation is split across focused submodules:

- ``models``      -- LinkKind, LINK_LABELS, GraphLink, CandidatePair
- ``persistence`` -- atomic JSON write + snapshot/flush helpers
- ``links``       -- link CRUD + blocked-pair operations
- ``candidates``  -- candidate pairs + pending-judge operations
- ``store``       -- the GraphStore facade composing the above
"""

from __future__ import annotations

from .lifecycle import GraphLifecycleRollbackError
from .models import (
    LINK_LABELS,
    CandidatePair,
    GraphCardLifecycleSnapshot,
    GraphLink,
    LinkKind,
)
from .store import GraphStore

__all__ = [
    "LINK_LABELS",
    "CandidatePair",
    "GraphCardLifecycleSnapshot",
    "GraphLifecycleRollbackError",
    "GraphLink",
    "GraphStore",
    "LinkKind",
]
