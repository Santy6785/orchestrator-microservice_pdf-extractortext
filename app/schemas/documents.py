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

class ProcessingResult(BaseModel):
    """Result of the asynchronous processing pipeline.
    Returned immediately with HTTP 202; later the client can query the status.
    """
    document_id: str = Field(..., description="Document identifier")
    status: str = Field(..., description="Current processing status (e.g., queued, processing, completed, failed)")
    detail: Optional[str] = Field(None, description="Additional information or error message")
