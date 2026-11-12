from datetime import datetime
from pydantic import BaseModel,ConfigDict
from app.models.document import DocumentStatus
class DocumentResponse(BaseModel):
    id:str; original_filename:str; stored_filename:str; content_type:str; file_size:int; sha256:str
    status:DocumentStatus; uploaded_at:datetime; updated_at:datetime|None=None; page_count:int|None=None; chunk_count:int=0
    processed_at:datetime|None=None; error_message:str|None=None
    model_config=ConfigDict(from_attributes=True)
class DocumentListResponse(BaseModel):
    items:list[DocumentResponse]; total:int; page:int; page_size:int
class ChunkResponse(BaseModel):
    id:str; document_id:str; chunk_index:int; content:str; char_count:int
    page_start:int|None; page_end:int|None
    model_config=ConfigDict(from_attributes=True)
class ChunkListResponse(BaseModel):
    items:list[ChunkResponse]; total:int; page:int; page_size:int
class ProcessResult(BaseModel):
    document_id:str; status:DocumentStatus; page_count:int; chunk_count:int; extracted_char_count:int
