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
  "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
  "extracted_text": "Texto extraído de todas las páginas del PDF...",
  "page_count": 3
}
```

#### Errores Mapeables:
- **HTTP 400 Bad Request:** El archivo recibido no es un PDF válido o está vacío.
- **HTTP 422 Unprocessable Entity:** PDF corrupto, dañado o con contraseña (`{"detail": "PDF corrupto o no legible: EOF marker not found"}`). El orquestador propaga este mensaje al cliente.
- **HTTP 500 / 503:** Error interno del extractor. El orquestador aplica política de reintentos con backoff exponencial.

### 1.4. Políticas de Red y Resiliencia en el Orquestador
- **Timeout:** `30.0 segundos` (la extracción de PDFs complejos puede ser costosa).
- **Retry:** Reintentar hasta 3 veces con backoff exponencial (`0.5s`, `1.0s`, `2.0s`) solo para errores de conexión o HTTP 502/503/504. **Nunca reintentar errores 4xx**.

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
