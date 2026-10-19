from pydantic import BaseModel, Field
from typing import Optional

class ErrorResponse(BaseModel):
    """Standard JSON error payload returned by the orchestrator.
    
    Fields follow the contract defined in `docs/contratos/`.
    """
    code: str = Field(..., description="Machine‑readable error identifier")
    message: str = Field(..., description="Human‑readable description of the error")
    request_id: Optional[str] = Field(None, description="Correlation ID for the request")
