from fastapi import APIRouter

from app.api.v1.routes.documents import router as documents_router
from app.api.v1.routes.extraction import router as extraction_router
from app.api.v1.routes.entity_resolution import router as entity_resolution_router
from app.api.v1.routes.dashboard import router as dashboard_router
from app.api.v1.routes.raw_data import router as raw_data_router\nfrom app.api.v1.routes.settings import router as settings_router

api_router = APIRouter()

# Canonical paths: documents_router already owns the "/documents" prefix.
api_router.include_router(documents_router)
api_router.include_router(extraction_router, prefix="/documents", tags=["Entity Extraction"])
api_router.include_router(entity_resolution_router, tags=["Entity Resolution"])

api_router.include_router(dashboard_router)
api_router.include_router(raw_data_router)\napi_router.include_router(settings_router)
