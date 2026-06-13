from .admin import build_admin_router, build_admin_routers
from .auth import router as auth_router
from .billing import router as billing_router
from .library import router as library_router
from .notebook import router as notebook_router
from .pipeline import router as pipeline_router
from .podcast import router as podcast_router
from .static_pages import router as static_pages_router
from .system import router as system_router
from .translate import router as translate_router
from .user import router as user_router
from .vocab import router as vocab_router
from .web_auth import router as web_auth_router

__all__ = [
    "build_admin_router",
    "build_admin_routers",
    "auth_router",
    "billing_router",
    "library_router",
    "notebook_router",
    "pipeline_router",
    "podcast_router",
    "static_pages_router",
    "system_router",
    "translate_router",
    "user_router",
    "vocab_router",
    "web_auth_router",
]
