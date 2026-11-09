import uuid
from sqlalchemy import ForeignKey,Integer,String,Text,UniqueConstraint
from sqlalchemy.orm import Mapped,mapped_column
from app.core.database import Base
class DocumentChunk(Base):
    __tablename__='document_chunks'
    __table_args__=(UniqueConstraint('document_id','chunk_index',name='uq_document_chunk_index'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    document_id: Mapped[str]=mapped_column(String(36),ForeignKey('documents.id',ondelete='CASCADE'),nullable=False,index=True)
    chunk_index: Mapped[int]=mapped_column(Integer,nullable=False)
    content: Mapped[str]=mapped_column(Text,nullable=False)
    char_count: Mapped[int]=mapped_column(Integer,nullable=False)
    page_start: Mapped[int|None]=mapped_column(Integer,nullable=True)
    page_end: Mapped[int|None]=mapped_column(Integer,nullable=True)
