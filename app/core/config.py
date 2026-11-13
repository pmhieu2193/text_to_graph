import json
import shutil
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "settings.json"


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/app.db"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    storage_dir: Path = DATA_DIR / "documents"
    extracted_text_dir: Path = DATA_DIR / "extracted"
    max_upload_size_mb: int = 30
    chunk_size: int = 1000
    chunk_overlap: int = 150

    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    llm_api_key: str | None = None
    llm_fallback_api_key: str | None = None
    llm_max_retries: int = 1
    llm_base_delay: float = 2.0
    llm_max_delay: float = 20.0

    er_index_dir: Path = DATA_DIR / "entity_resolution" / "indexes"
    er_report_dir: Path = DATA_DIR / "entity_resolution" / "reports"
    er_embedding_model: str = "BAAI/bge-m3"
    er_embedding_batch_size: int = 16
    er_embedding_max_length: int = 128
    er_faiss_top_k: int = 50
    er_embedding_candidate_limit: int = 10
    er_string_top_k: int = 10
    er_fuzzy_auto_threshold: float = 0.92
    er_embedding_auto_threshold: float = 0.90
    er_fuzzy_review_threshold: float = 0.80
    er_embedding_review_threshold: float = 0.80
    er_auto_merge_exact: bool = False
    er_report_format: str = "xlsx"

    neo4j_uri: str | None = None
    neo4j_username: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_assignment=True,
    )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()


def _normalize_data_path(value: Path, folder: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        normalized = path.as_posix().removeprefix("./")
        if normalized.startswith("storage/"):
            normalized = "data/" + normalized.removeprefix("storage/")
        path = BASE_DIR / normalized
    return path.resolve()


for setting_name, folder in (
    ("storage_dir", "documents"),
    ("extracted_text_dir", "extracted"),
    ("er_index_dir", "entity_resolution/indexes"),
    ("er_report_dir", "entity_resolution/reports"),
):
    configured = Path(getattr(settings, setting_name))
    if not configured.is_absolute():
        normalized = configured.as_posix().removeprefix("./")
        if normalized.startswith("storage/"):
            normalized = "data/" + normalized.removeprefix("storage/")
        configured = BASE_DIR / normalized
    setattr(settings, setting_name, configured.resolve())


def _migrate_legacy_storage() -> None:
    """Move old ./storage artifacts into ./data while preserving existing files."""
    legacy_root = BASE_DIR / "storage"
    if not legacy_root.exists():
        return
    destinations = {
        "documents": settings.storage_dir,
        "extracted": settings.extracted_text_dir,
        "entity_resolution/indexes": settings.er_index_dir,
        "entity_resolution/reports": settings.er_report_dir,
    }
    for relative, destination in destinations.items():
        source = legacy_root / relative
        if not source.exists():
            continue
        for old_file in source.rglob("*"):
            if not old_file.is_file():
                continue
            target = destination / old_file.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.move(str(old_file), str(target))
        # Remove empty legacy directories only; never delete non-empty files.
        for directory in sorted(source.rglob("*"), reverse=True):
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
        try:
            source.rmdir()
        except OSError:
            pass
    try:
        legacy_root.rmdir()
    except OSError:
        pass


_migrate_legacy_storage()


def _load_persisted_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        payload = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        return payload
    except (OSError, json.JSONDecodeError):
        return {}


def persist_runtime_settings(updates: dict[str, Any]) -> None:
    """Persist editable connection settings outside the application image."""
    allowed = {
        "llm_api_key", "llm_fallback_api_key", "neo4j_uri",
        "neo4j_username", "neo4j_password", "neo4j_database",
        "llm_model", "llm_provider",
    }
    current = _load_persisted_settings()
    for key, value in updates.items():
        if key not in allowed:
            continue
        current[key] = value
        setattr(settings, key, value)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(SETTINGS_FILE)


def apply_persisted_settings() -> None:
    for key, value in _load_persisted_settings().items():
        if hasattr(settings, key) and key in {
            "llm_api_key", "llm_fallback_api_key", "neo4j_uri",
            "neo4j_username", "neo4j_password", "neo4j_database",
            "llm_model", "llm_provider",
        }:
            setattr(settings, key, value)


apply_persisted_settings()

# Resolve all relative paths against the repository/application root, never the
# caller's current working directory. This is predictable in Docker as well.
for name in ("storage_dir", "extracted_text_dir", "er_index_dir", "er_report_dir"):
    value = Path(getattr(settings, name))
    if not value.is_absolute():
        value = (BASE_DIR / value).resolve()
    setattr(settings, name, value)
    value.mkdir(parents=True, exist_ok=True)

if settings.database_url.startswith("sqlite:///"):
    raw_path = settings.database_url.removeprefix("sqlite:///")
    if raw_path != ":memory:":
        db_path = Path(raw_path)
        if not db_path.is_absolute():
            db_path = (BASE_DIR / db_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        settings.database_url = "sqlite:///" + db_path.as_posix()
