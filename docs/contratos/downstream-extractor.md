# Contratos Downstream: Orquestador -> Microservicio Extractor

> **Propósito:** Define los contratos formales de las llamadas HTTP que el Orquestador realiza hacia el microservicio **Extractor** (puerto por defecto `8001`, URL configurada vía `EXTRACTOR_SERVICE_URL`).

---

## 1. Llamada: `POST /api/v1/extract` (Extraer Texto de PDF)

### 1.1. Contexto de Invocación
Invocado por el Orquestador durante el flujo de subida (`POST /api/v1/documents/upload`), **únicamente después** de que se ha verificado que el checksum del archivo no existe previamente en Persistencia (optimización fail-fast).

### 1.2. Petición (Orquestador -> Extractor)
- **Método:** `POST`
- **Ruta:** `/api/v1/extract`
- **Headers:**
  - `Content-Type: multipart/form-data`
  - `X-Request-ID: <uuid>` (propagado desde la petición original)
- **Body (Multipart):**
  - `file`: Binario del PDF en memoria (`bytes`), con nombre original y tipo `application/pdf`.

### 1.3. Respuestas Esperadas (Extractor -> Orquestador)

#### Éxito: HTTP 200 OK
```json
{
  "content": "# Título\n\ntexto en Markdown...",
  "page_count": 16
}
```
`Content-Type: application/json`. Campos: `content` (texto extraído en Markdown) y `page_count` (cantidad de páginas procesadas).

#### Errores Mapeables:
- **HTTP 400 Bad Request:** El archivo recibido no es un PDF válido o está vacío (`Missing multipart field 'file'`, `Not a PDF (missing %PDF- header)` o `Extraction Failed`).
- **HTTP 413 Payload Too Large:** El PDF excede el tamaño máximo permitido (`PDF_MAX_FILE_SIZE_MB`).
- **HTTP 415 Unsupported Media Type:** Content-Type no soportado (debe ser `multipart/form-data`, `application/pdf` o `application/octet-stream`).
- **HTTP 422 Unprocessable Entity:** PDF corrupto, dañado, no legible o protegido con contraseña.
- **HTTP 429 Too Many Requests:** Cola de espera llena o timeout de cola superado (`Queue is full` / `Queue timeout`). Incluye header `Retry-After: 1`. **No se reintenta automáticamente desde el Orquestador** (es un error 4xx).
- **HTTP 500 / 503:** Error interno del extractor.

### 1.4. Políticas de Red y Resiliencia en el Orquestador
- **Timeout:** `30.0 segundos` (la extracción de PDFs complejos puede ser costosa).
- **Retry:** El cliente de HTTP (`BaseClient`) reintenta hasta 3 veces con backoff exponencial (`0.5s`, `1.0s`, `2.0s`) solo para errores de conexión o HTTP 5xx. **Nunca reintentar errores 4xx** (incluyendo 400, 413, 415, 422 y 429).

---

## 2. Llamada: `GET /health` (Comprobación de Salud del Extractor)

### 2.1. Contexto de Invocación
Invocado periódicamente por el endpoint `/health` del Orquestador para determinar la disponibilidad de la dependencia.

### 2.2. Petición (Orquestador -> Extractor)
- **Método:** `GET`
- **Ruta:** `/health`
- **Headers:**
  - `X-Request-ID: <uuid>`

### 2.3. Respuestas Esperadas
- **HTTP 200 OK:**
  ```json
  {
    "status": "healthy",
    "service": "extractor",
    "version": "0.1.0"
  }
  ```
- **Timeout:** `2.0 segundos`. Sin reintentos (fail-fast para healthchecks).
