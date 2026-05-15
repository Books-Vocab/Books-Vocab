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

from .models import LINK_LABELS, CandidatePair, GraphLink, LinkKind
from .store import GraphStore

__all__ = [
    "LINK_LABELS",
    "CandidatePair",
    "GraphLink",
    "GraphStore",
    "LinkKind",
]
