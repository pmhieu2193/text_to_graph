from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router

from app.core.database import Base, engine

# Import để đăng ký toàn bộ SQLAlchemy models.
import app.models


@asynccontextmanager
async def lifespan(app: FastAPI):

    Base.metadata.create_all(bind=engine)

    yield


app = FastAPI(
    title="Vietnamese Knowledge Graph API",
    description="Document upload and Knowledge Graph extraction API",
    version="0.2.0",
    lifespan=lifespan,
)


app.include_router(
    api_router,
    prefix="/api/v1",
)


@app.get("/health", tags=["Health"])
def health_check():

    return {
        "status": "ok",
    }