from pydantic import BaseModel, Field
from typing import Optional

class DocumentUploadRequest(BaseModel):
    """Payload for uploading a PDF document.
    The actual file will be uploaded via multipart/form-data; this model
    represents any additional JSON fields that may accompany the upload.
    """
    filename: str = Field(..., description="Original filename of the uploaded PDF")
    metadata: Optional[dict] = Field(None, description="Optional user‑provided metadata")

class DocumentResponse(BaseModel):
    """Response after a successful upload.
    Includes the orchestrator‑generated document ID and a URL to check status.
    """
    document_id: str = Field(..., description="Unique identifier assigned by the orchestrator")
    status_url: str = Field(..., description="Endpoint to query processing status")

class DocumentUploadResponse(BaseModel):
    """Response after a successful document upload and processing.
    Matches the frontend contract for POST /api/v1/documents/upload (HTTP 200).
    """
    id: str = Field(..., description="Unique identifier assigned by the persistence service")
    checksum: str = Field(..., description="SHA-256 checksum of the uploaded PDF")
    extracted_text: str = Field(..., description="Text extracted from the PDF")
    created_at: str = Field(..., description="Timestamp when the document was persisted")
    filename: str = Field(..., description="Original filename of the uploaded PDF")
    page_count: int = Field(..., description="Number of pages in the PDF")
    file_size_bytes: int = Field(..., description="Size of the uploaded PDF in bytes")


class DocumentListItem(BaseModel):
    """Documento en formato resumido para listados paginados.
    Coincide con el contrato GET /api/v1/documents/ (id, checksum, created_at).
    """
    id: str = Field(..., description="Unique identifier of the document")
    checksum: str = Field(..., description="SHA-256 checksum of the document")
    created_at: str = Field(..., description="Timestamp when the document was persisted")


class DocumentDetailResponse(BaseModel):
    """Respuesta completa de un documento.
    Coincide con el contrato GET/PUT /api/v1/documents/{document_id}.
    """
    id: str = Field(..., description="Unique identifier of the document")
    checksum: str = Field(..., description="SHA-256 checksum of the document")
    extracted_text: str = Field(..., description="Text extracted from the document")
    created_at: str = Field(..., description="Timestamp when the document was persisted")


class DocumentUpdateRequest(BaseModel):
    """Cuerpo de petición para actualizar el texto extraído de un documento.
    Coincide con el contrato PUT /api/v1/documents/{document_id}.
    """
    extracted_text: str = Field(..., description="New extracted text for the document")
