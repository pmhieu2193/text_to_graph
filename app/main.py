from fastapi import FastAPI

from app.api.v1.router import api_router


app = FastAPI(
    title="Vietnamese Knowledge Graph API",
    description="Document upload and Knowledge Graph extraction API",
    version="0.3.0",
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
