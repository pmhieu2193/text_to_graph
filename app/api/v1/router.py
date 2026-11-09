from fastapi import APIRouter

from app.api.v1.routes.documents import (
    router as documents_router,
)

from app.api.v1.routes.extraction import (
    router as extraction_router,
)


api_router = APIRouter()

api_router.include_router(
    documents_router,
    prefix="/documents",
    tags=["Documents"],
)

api_router.include_router(
    extraction_router,
    prefix="/documents",
    tags=["Entity Extraction"],
)