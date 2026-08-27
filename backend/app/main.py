from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.messages import router as messages_router
from app.api.meta import router as meta_router
from app.api.ws import router as ws_router
from app.core.config import settings
from app.core.rate_limit import RateLimitMiddleware

# Disable docs in production
docs_url = "/docs" if settings.env != "production" else None
redoc_url = "/redoc" if settings.env != "production" else None
openapi_url = "/openapi.json" if settings.env != "production" else None

app = FastAPI(
    title="Content Tracker API",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(messages_router)
app.include_router(meta_router)
app.include_router(ws_router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
