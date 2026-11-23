# Contratos Downstream: Orquestador -> Microservicio Extractor

> **Propósito:** Define los contratos formales de las llamadas HTTP que el Orquestador realiza hacia el microservicio **Extractor** (puerto por defecto `8001`, URL configurada vía `EXTRACTOR_SERVICE_URL`).

---

## 1. Llamada: `POST /api/v1/extract` (Extraer Texto de PDF)

### 1.1. Contexto de Invocación
Invocado por el Orquestador (`IngestionService.process_document` -> `ExtractorClient.extract_document`) durante el flujo de subida (`POST /api/v1/documents/upload`), **únicamente después** de verificar mediante `GET /api/v1/documents/by-checksum/{checksum}` que el archivo no existe previamente en Persistencia (optimización fail-fast).

### 1.2. Petición (Orquestador -> Extractor)
- **Método:** `POST`
- **Ruta:** `/api/v1/extract`
- **Headers:**
  - `Content-Type: multipart/form-data; boundary=...`
  - `X-Request-ID: <uuid>` (propagado automáticamente desde `request_id_var`)
- **Body (Multipart):**
  - `file`: Única parte multipart con los bytes binarios del PDF (`bytes`), el nombre original del archivo (`filename`) y tipo MIME `application/pdf`. No se envían campos JSON adicionales.

#### Ejemplo Ejecutable (`curl`)
```bash
curl -i -X POST "http://localhost:8001/api/v1/extract" \
  -H "X-Request-ID: 550e8400-e29b-41d4-a716-446655440000" \
  -F "file=@./sample.pdf;type=application/pdf"