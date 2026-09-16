from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Document:
    id: str
    content: str
    metadata: dict[str, Any] | None = None


@dataclass
class ProcessingResult:
    document_id: str
    status: str
    message: str | None = None