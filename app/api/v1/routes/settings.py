from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.config import persist_runtime_settings, settings

router = APIRouter(tags=["Settings"])


class RuntimeSettingsUpdate(BaseModel):
    llm_api_key: str | None = None
    llm_fallback_api_key: str | None = None
    llm_model: str = Field(min_length=1, max_length=120)
    llm_provider: str = Field(min_length=1, max_length=40)
    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = Field(min_length=1, max_length=120)


def _masked(value: str | None) -> dict:
    return {"configured": bool(value), "masked": "••••••••" if value else ""}


@router.get("/settings")
def get_runtime_settings():
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_api_key": _masked(settings.llm_api_key),
        "llm_fallback_api_key": _masked(settings.llm_fallback_api_key),
        "neo4j_uri": settings.neo4j_uri or "bolt://localhost:7687",
        "neo4j_username": settings.neo4j_username or "neo4j",
        "neo4j_password": _masked(settings.neo4j_password),
        "neo4j_database": settings.neo4j_database,
    }


@router.put("/settings")
def update_runtime_settings(payload: RuntimeSettingsUpdate):
    values = payload.model_dump(exclude_unset=True)
    # Blank secret fields mean "leave unchanged"; explicit clearing uses the
    # dedicated clear_secrets endpoint to avoid accidental loss on form save.
    for key in ("llm_api_key", "llm_fallback_api_key", "neo4j_password"):
        if values.get(key) == "":
            values.pop(key, None)
    try:
        persist_runtime_settings(values)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Không thể lưu settings: {exc}") from exc
    return get_runtime_settings()


@router.delete("/settings/secrets/{secret_name}")
def clear_runtime_secret(secret_name: str):
    allowed = {"llm_api_key", "llm_fallback_api_key", "neo4j_password"}
    if secret_name not in allowed:
        raise HTTPException(status_code=400, detail="Secret không hợp lệ.")
    from app.core.config import persist_runtime_settings
    persist_runtime_settings({secret_name: None})
    return {"cleared": secret_name}
