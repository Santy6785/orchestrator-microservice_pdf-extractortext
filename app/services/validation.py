"""Funciones de validación y utilidades para archivos subidos.

Centraliza las reglas de validación y funciones auxiliares que aplican al
endpoint de upload para evitar duplicarlas en el router o en el servicio
de ingesta.
"""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, status

# Tamaño máximo permitido para un archivo subido: 10 MB (10 * 1024 * 1024 bytes).
MAX_FILE_SIZE = 10 * 1024 * 1024


def validate_file_size(data: bytes) -> None:
    """Valida que el tamaño de los bytes del archivo no exceda el máximo permitido.

    Args:
        data: Contenido del archivo leído desde el request multipart.

    Raises:
        HTTPException: HTTP 400 con ``detail`` cuando el archivo supera
            ``MAX_FILE_SIZE``.
    """
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo excede el tamaño máximo permitido de 10MB",
        )


PDF_MAGIC_BYTES = b"%PDF-"


def validate_pdf_magic_bytes(data: bytes) -> None:
    """Valida que el contenido del archivo comience con los magic bytes de PDF.

    La comprobación se realiza sobre los bytes reales del archivo, no sobre
    su extensión ni sobre el Content-Type enviado por el cliente.

    Args:
        data: Contenido del archivo leído desde el request multipart.

    Raises:
        HTTPException: HTTP 400 con ``detail`` cuando el archivo no comienza
            con ``%PDF-`` (incluido el archivo vacío).
    """
    if not data.startswith(PDF_MAGIC_BYTES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo no es un PDF válido",
        )


def compute_sha256_hex(data: bytes) -> str:
    """Calcula el checksum SHA-256 hexadecimal en minúsculas de los bytes dados.

    El hash se calcula sobre los bytes originales, sin modificar ni normalizar
    el contenido. La salida de ``hashlib.sha256().hexdigest()`` es una cadena
    de exactamente 64 caracteres hexadecimales en minúsculas.

    Args:
        data: Contenido del archivo en bytes leído desde el request multipart.

    Returns:
        Checksum SHA-256 como string hexadecimal de 64 caracteres en minúsculas.
    """
    return hashlib.sha256(data).hexdigest()
