from __future__ import annotations

from typing import get_type_hints

from fastapi.routing import APIRoute

import kg.deps as deps
from kg.routers import billing, notebook, pipeline, podcast, translate, user, vocab

_ROUTER_MODULES = [
    billing,
    notebook,
    pipeline,
    podcast,
    translate,
    user,
    vocab,
]


def test_router_user_params_use_named_auth_contract_aliases():
    offenders: list[str] = []

    for module in _ROUTER_MODULES:
        for route in module.router.routes:
            if not isinstance(route, APIRoute):
                continue
            hints = get_type_hints(route.endpoint, globalns=vars(module), include_extras=True)
            user_hint = hints.get("user")
            if user_hint is None:
                continue
            if user_hint not in {deps.CurrentUser, deps.OptionalCurrentUser}:
                offenders.append(f"{module.__name__}:{route.path} -> {user_hint!r}")

    assert not offenders, "Router auth contracts must use deps.CurrentUser / deps.OptionalCurrentUser:\n" + "\n".join(offenders)
