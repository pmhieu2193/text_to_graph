from fastapi import APIRouter

from app.api.v1.routes.documents import router as documents_router
from app.api.v1.routes.extraction import router as extraction_router
from app.api.v1.routes.entity_resolution import router as entity_resolution_router

api_router = APIRouter()

# documents_router already declares its own "/documents" prefix.
api_router.include_router(documents_router)
api_router.include_router(extraction_router, prefix="/documents", tags=["Entity Extraction"])
api_router.include_router(entity_resolution_router, tags=["Entity Resolution"])
