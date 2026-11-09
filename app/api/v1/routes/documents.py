from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import DocumentListResponse,DocumentResponse,ChunkListResponse,ProcessResult
from app.services.document_service import DocumentService
from app.services.processing_service import DocumentProcessingService


router=APIRouter(prefix='/documents',tags=['Documents'])

@router.post(
    "/upload",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a PDF document",
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    service = DocumentService(db)
    return await service.upload(file)

@router.get('',response_model=DocumentListResponse)
def list_documents(page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),db:Session=Depends(get_db)):
    items,total=DocumentRepository(db).list(page,page_size);return dict(items=items,total=total,page=page,page_size=page_size)
@router.get('/{document_id}',response_model=DocumentResponse)
def get_document(document_id:str,db:Session=Depends(get_db)):
    doc=DocumentRepository(db).get_by_id(document_id)
    if doc is None: raise HTTPException(404,'Không tìm thấy tài liệu.')
    return doc
@router.post('/{document_id}/process',response_model=ProcessResult)
def process_document(document_id:str,db:Session=Depends(get_db)):
    try: return DocumentProcessingService(db).process(document_id)
    except LookupError as e: raise HTTPException(404,str(e)) from e
    except RuntimeError as e: raise HTTPException(409,str(e)) from e
    except ValueError as e: raise HTTPException(422,str(e)) from e
    except Exception as e: raise HTTPException(500,f'Xử lý PDF thất bại: {e}') from e
@router.get('/{document_id}/chunks',response_model=ChunkListResponse)
def list_chunks(document_id:str,page:int=Query(1,ge=1),page_size:int=Query(20,ge=1,le=100),db:Session=Depends(get_db)):
    repo=DocumentRepository(db)
    if repo.get_by_id(document_id) is None: raise HTTPException(404,'Không tìm thấy tài liệu.')
    items,total=repo.list_chunks(document_id,page,page_size);return dict(items=items,total=total,page=page,page_size=page_size)
