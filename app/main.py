from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Day 1: create the initial SQLite schema.
    # Add Alembic migrations when the schema starts evolving.
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Vietnamese Knowledge Graph API",
    description="Document upload and management API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
