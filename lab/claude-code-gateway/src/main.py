from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.config import settings
from src.routes import chat_completions, health, models

app = FastAPI(
    title="Claude Code Gateway",
    description="OpenAI-compatible API gateway for Claude Code CLI",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not settings.api_token or request.url.path == "/health":
        return await call_next(request)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(token, settings.api_token):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)


app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat_completions.router)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)
