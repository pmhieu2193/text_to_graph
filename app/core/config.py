from pathlib import Path


from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):

    # Database
    database_url: str = "sqlite:///./data/app.db"

    # Storage
    storage_dir: Path = "./storage/documents"
    extracted_text_dir: Path = "./storage/extracted"

    # Upload
    max_upload_size_mb: int = 30

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # LLM
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    llm_api_key: str | None = None

    # Retry
    llm_max_retries: int = 3
    llm_base_delay: float = 2.0
    llm_max_delay: float = 20.0

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

Path(settings.storage_dir).mkdir(
    parents=True,
    exist_ok=True,
)

Path(settings.extracted_text_dir).mkdir(
    parents=True,
    exist_ok=True,
)