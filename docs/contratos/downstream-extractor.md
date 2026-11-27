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

---

## 2. Llamada: `GET /health` (Health Check de Extractor)

### 2.1. Contexto de Invocación

Invocado por el Orquestador (`control.py::_probe_health` -> `ExtractorClient.get`) durante el chequeo de readiness (`GET /api/v1/control/health/ready` y `GET /api/v1/control/health`). Se ejecuta en paralelo con el chequeo de Persistencia y con timeout individual (`HEALTH_TIMEOUT_SECONDS`, default `2.0`) y timeout global (`HEALTH_GLOBAL_TIMEOUT_SECONDS`, `5.0`).

### 2.2. Petición (Orquestador -> Extractor)

- **Método:** `GET`
- **Ruta:** `/health` (sin prefijo `/api/v1`)
- **Headers:** Ninguno obligatorio

### 2.3. Respuesta Esperada (Extractor -> Orquestador)

| Estado | Código HTTP | Cuerpo JSON esperado | Significado para el Orquestador |
|--------|-------------|----------------------|---------------------------------|
| Saludable | `200 OK` | `{"status": "ok"}` | El campo `status` pertenece a `_EXTRACTOR_HEALTHY_STATUSES = {"ok"}`. Dependencia considerada disponible. |
| No saludable | `200 OK` | `{"status": "<otro>"}` | Cualquier otro valor de `status` se trata como `unreachable`. |
| Error / Fallo | Cualquier otro / timeout / excepción | — | Se trata como `unreachable`. El fallo del Extractor no afecta el estado de Persistencia; se reportan de forma independiente. |

> **Nota de compatibilidad:** El orquestador lee únicamente el campo `status` del cuerpo JSON. Otros campos adicionales en la respuesta son ignorados. Si el microservicio Extractor cambia el valor de `"ok"` o la ruta `/health`, el orquestador marcará la dependencia como `unreachable` y `/api/v1/control/health` devolverá `503`.

#### Ejemplo Ejecutable (`curl`)

```bash
curl -i "http://localhost:8001/health"
# HTTP/1.1 200 OK
# Content-Type: application/json
#
# {"status": "ok"}
```

#### Ejemplo de respuesta NO saludable

```bash
curl -i "http://localhost:8001/health"
# HTTP/1.1 200 OK
# Content-Type: application/json
#
# {"status": "degraded"}  # -> orquestador lo trata como "unreachable"
```