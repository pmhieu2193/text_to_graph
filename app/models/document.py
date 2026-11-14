import enum, uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
class DocumentStatus(str, enum.Enum):
    UPLOADED = 'UPLOADED'
    CHUNKED = 'CHUNKED'
    PARTIAL_EXTRACTION = 'PARTIAL_EXTRACTION'
    EXTRACTED = 'EXTRACTED'
    ENTITY_RESOLUTION = 'ENTITY_RESOLUTION'
    HUMAN_REVIEW = 'HUMAN_REVIEW'
    FINALIZED = 'FINALIZED'
    NEO4J_SYNCED = 'NEO4J_SYNCED'
    # Legacy values retained so existing rows and clients remain readable.
    PENDING = 'PENDING'
    PROCESSING = 'PROCESSING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
class Document(Base):
    __tablename__='documents'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    original_filename: Mapped[str]=mapped_column(String(255),nullable=False)
    stored_filename: Mapped[str]=mapped_column(String(255),unique=True,nullable=False)
    file_path: Mapped[str]=mapped_column(String(500),nullable=False)
    content_type: Mapped[str]=mapped_column(String(100),nullable=False,default='application/pdf')
    file_size: Mapped[int]=mapped_column(Integer,nullable=False)
    sha256: Mapped[str]=mapped_column(String(64),nullable=False)
    status: Mapped[DocumentStatus]=mapped_column(Enum(DocumentStatus),nullable=False,default=DocumentStatus.UPLOADED)
    uploaded_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc),onupdate=lambda:datetime.now(timezone.utc))
    page_count: Mapped[int|None]=mapped_column(Integer,nullable=True)
    chunk_count: Mapped[int]=mapped_column(Integer,nullable=False,default=0)
    extracted_text_path: Mapped[str|None]=mapped_column(String(500),nullable=True)
    processed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True),nullable=True)
    error_message: Mapped[str|None]=mapped_column(Text,nullable=True)
