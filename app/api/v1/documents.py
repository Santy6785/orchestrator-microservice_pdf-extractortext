import uuid

from fastapi import APIRouter, Depends, File, Path, Query, UploadFile, status

from app.dependencies import get_ingestion_service
from app.schemas.documents import (
    DocumentDetailResponse,
    DocumentListItem,
    DocumentUploadResponse,
)
from app.schemas.errors import ErrorResponse
from app.services.ingestion import IngestionService
from app.services.validation import (
    compute_sha256_hex,
    validate_file_size,
    validate_pdf_magic_bytes,
)

router = APIRouter(prefix="/documents", tags=["documents"])

@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
)
async def upload_document(
    file: UploadFile = File(...),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Accept a PDF file via multipart/form-data and process it.
    The file bytes are read in memory, forwarded to the ingestion service
    which extracts text, persists the document and returns the full document
    record with HTTP 200.
    """
    data = await file.read()
    validate_file_size(data)
    validate_pdf_magic_bytes(data)
    checksum = compute_sha256_hex(data)
    payload = {"filename": file.filename, "content": data, "checksum": checksum}
    result = await ingestion_service.process_document(payload)
    return result

@router.get(
    "/",
    response_model=list[DocumentListItem],
    status_code=status.HTTP_200_OK,
    responses={
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def list_documents(
    skip: int = Query(
        0, ge=0, description="Número de documentos a saltar (offset)"
    ),
    limit: int = Query(
        20, ge=1, le=100, description="Cantidad máxima de documentos a retornar"
    ),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Lista paginada de documentos.
    Delegata en IngestionService.list_documents, que a su vez llama a
    PersistenceClient.GET /api/v1/documents?skip=&limit=.
    """
    return await ingestion_service.list_documents(skip=skip, limit=limit)


@router.get(
    "/{document_id}",
    response_model=DocumentDetailResponse,
    status_code=status.HTTP_200_OK,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def get_document(
    document_id: uuid.UUID = Path(..., description="ID único del documento (UUID)"),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Obtiene un documento por su ID.
    Delegata en IngestionService.get_document, que a su vez llama a
    PersistenceClient.GET /api/v1/documents/{document_id}.
    """
    return await ingestion_service.get_document(str(document_id))


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def delete_document(
    document_id: str = Path(..., description="ID único del documento"),
    ingestion_service: IngestionService = Depends(get_ingestion_service),
):
    """Elimina un documento por su ID.
    Delegata en IngestionService.delete_document, que a su vez llama a
    PersistenceClient.DELETE /api/v1/documents/{document_id}.
    Retorna HTTP 204 No Content sin cuerpo de respuesta.
    """
    await ingestion_service.delete_document(document_id)
