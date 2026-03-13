from .admin import build_admin_router
from .auth import router as auth_router
from .billing import router as billing_router
from .pipeline import router as pipeline_router
from .static_pages import router as static_pages_router
from .translate import router as translate_router
from .user import router as user_router
from .vocab import router as vocab_router

__all__ = [
    "build_admin_router",
    "auth_router",
    "billing_router",
    "pipeline_router",
    "static_pages_router",
    "translate_router",
    "user_router",
    "vocab_router",
]
