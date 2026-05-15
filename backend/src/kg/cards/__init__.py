"""Card storage and CRUD operations.

This package was split out of the former single-file ``kg.cards`` module.
All public names are re-exported here so that existing
``from kg.cards import X`` callers continue to work unchanged.
"""

from __future__ import annotations

from .model import Card, CardMode
from .store import CardStore

__all__ = ["Card", "CardMode", "CardStore"]
