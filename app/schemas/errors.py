from pydantic import BaseModel, Field
from typing import Optional


class ErrorResponse(BaseModel):
    """Standard JSON error payload returned by the orchestrator.

    Contract:

        {
          "detail": "Descripción del error",
          "code": "error_code",
          "request_id": "uuid"
        }

    ``existing_id`` es opcional y solo se incluye en errores de duplicación
    de documentos.
    """

    detail: str = Field(..., description="Human‑readable description of the error")
    code: str = Field(..., description="Machine‑readable error identifier")
    request_id: Optional[str] = Field(
        None, description="Correlation ID for the request"
    )
    existing_id: Optional[str] = Field(
        None, description="ID of the existing document when reporting a duplicate"
    )
