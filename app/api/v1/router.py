from fastapi import APIRouter

from app.api.v1.routes.documents import router as documents_router
from app.api.v1.routes.extraction import router as extraction_router
from app.api.v1.routes.entity_resolution import router as entity_resolution_router

api_router = APIRouter()

# Canonical paths: documents_router already owns the "/documents" prefix.
api_router.include_router(documents_router)

# Backward-compatible aliases for clients that used the former duplicated prefix.
api_router.include_router(documents_router, prefix="/documents", tags=["Documents (legacy)"])

api_router.include_router(extraction_router, prefix="/documents", tags=["Entity Extraction"])
api_router.include_router(entity_resolution_router, tags=["Entity Resolution"])
