from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/app.db"
    storage_dir: Path = Path("./storage/documents")
    extracted_text_dir: Path = Path("./storage/extracted")
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

    er_index_dir: Path = Path("./storage/entity_resolution/indexes")
    er_report_dir: Path = Path("./storage/entity_resolution/reports")
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()

for directory in (
    settings.storage_dir,
    settings.extracted_text_dir,
    settings.er_index_dir,
    settings.er_report_dir,
):
    Path(directory).mkdir(parents=True, exist_ok=True)
