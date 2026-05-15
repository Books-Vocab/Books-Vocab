"""Backwards-compatible shim for the former monolithic admin handlers module.

The implementation now lives in the :mod:`kg.admin` package, split into
responsibility-scoped submodules. This module re-exports every public name so
existing ``from kg.admin_handlers import X`` / ``import kg.admin_handlers``
callers keep working unchanged.

``hmac`` is re-exported deliberately: tests patch ``kg.admin_handlers.hmac``.
Since :mod:`hmac` is a process-wide module singleton, patching it through any
namespace mutates the shared object that :mod:`kg.admin.auth` also references.
"""

from __future__ import annotations

import hmac  # noqa: F401 — kept importable for test patching of kg.admin_handlers.hmac

from .admin import *  # noqa: F401,F403 — re-export the package's public API
from .admin import __all__ as __all__
