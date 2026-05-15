from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..notebook import validate_notebook_access


def _resolve_stores(
    user: dict[str, Any],
    notebook_id: str | None,
    *,
    card_store_factory: Callable[[Path], Any],
    graph_store_factory: Callable[..., Any] | None = None,
    notebook_store_factory: Callable[[Path], Any] | None = None,
) -> tuple[Any, Any]:
    """Validate notebook access and construct card + graph stores."""
    if notebook_id is not None and notebook_store_factory is not None:
        validate_notebook_access(notebook_store_factory(user["dir"]), notebook_id)
    cards = card_store_factory(user["dir"])
    graph = graph_store_factory(user["dir"], notebook_id=notebook_id or "default") if graph_store_factory is not None else None
    return cards, graph
