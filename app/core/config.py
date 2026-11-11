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

    # Primary API key
    llm_api_key: str | None = None

    # Fallback API key
    llm_fallback_api_key: str | None = None

    # Deferred retry
    llm_max_retries: int = 1
    llm_base_delay: float = 2.0
    llm_max_delay: float = 20.0

    
    # ==========================================
    # ENTITY RESOLUTION
    # ==========================================

    # Storage
    er_index_dir: Path = Path("./storage/entity_resolution/indexes")
    er_report_dir: Path = Path("./storage/entity_resolution/reports")
    
    # Embedding model
    er_embedding_model: str = "BAAI/bge-m3"
    er_embedding_batch_size: int = 16
    er_embedding_max_length: int = 128

    # FAISS retrieval
    # Số vector lân cận được lấy cho mỗi vector truy vấn.
    er_faiss_top_k: int = 50

    # Số entity lân cận tối đa giữ lại cho mỗi entity nguồn.
    er_embedding_candidate_limit: int = 10

    # String matching
    er_string_top_k: int = 10

    # Decision thresholds
    er_fuzzy_auto_threshold: float = 0.92
    er_embedding_auto_threshold: float = 0.90

    er_fuzzy_review_threshold: float = 0.80
    er_embedding_review_threshold: float = 0.80

    # Exact match có được phép tự động đưa vào nhóm AUTO hay không.
    # Để False an toàn hơn trong giai đoạn đầu.
    er_auto_merge_exact: bool = False

    # Report format: xlsx hoặc txt
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

Path(settings.storage_dir).mkdir(
    parents=True,
    exist_ok=True,
)

Path(settings.extracted_text_dir).mkdir(
    parents=True,
    exist_ok=True,
)

Path(settings.er_index_dir).mkdir(
    parents=True,
    exist_ok=True
)
Path(settings.er_report_dir).mkdir(
    parents=True, 
    exist_ok=True
)