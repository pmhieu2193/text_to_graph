from datetime import datetime,timezone
from pathlib import Path
from app.core.config import settings
from app.models.document import DocumentStatus
from app.repositories.document_repository import DocumentRepository
from app.services.pdf_extractor import PDFExtractor
from app.services.text_chunker import TextChunker
class DocumentProcessingService:
    def __init__(self,db):
        self.repo=DocumentRepository(db);self.extractor=PDFExtractor()
        self.chunker=TextChunker(settings.chunk_size,settings.chunk_overlap)
    def process(self,document_id):
        doc=self.repo.get_by_id(document_id)
        if doc is None: raise LookupError('Không tìm thấy tài liệu.')
        if doc.status==DocumentStatus.PROCESSING: raise RuntimeError('Tài liệu đang được xử lý.')
        doc.status=DocumentStatus.PROCESSING;doc.error_message=None;self.repo.commit()
        try:
            extracted=self.extractor.extract(doc.file_path);chunks=self.chunker.split(extracted)
            path=Path(settings.extracted_text_dir)/f'{doc.id}.txt';tmp=path.with_suffix('.txt.tmp')
            tmp.write_text(extracted.full_text,encoding='utf-8');tmp.replace(path)
            rows=[dict(chunk_index=c.chunk_index,content=c.content,char_count=c.char_count,page_start=c.page_start,page_end=c.page_end) for c in chunks]
            self.repo.save_chunks(doc.id,rows)
            doc.page_count=len(extracted.pages);doc.chunk_count=len(chunks);doc.extracted_text_path=str(path)
            doc.processed_at=datetime.now(timezone.utc);doc.status=DocumentStatus.COMPLETED;doc.error_message=None
            self.repo.commit();self.repo.refresh(doc)
            return dict(document_id=doc.id,status=doc.status,page_count=doc.page_count,chunk_count=doc.chunk_count,extracted_char_count=len(extracted.full_text))
        except Exception as exc:
            doc.status=DocumentStatus.FAILED;doc.error_message=str(exc)[:2000];self.repo.commit();raise
