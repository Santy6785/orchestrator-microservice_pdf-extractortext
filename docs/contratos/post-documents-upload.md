# Contrato de Endpoint: Subir y Procesar Documento PDF

## 1. Identificación
- **Método HTTP:** `POST`
- **Ruta:** `/api/v1/documents/upload`
- **Etiqueta:** `documents`
- **Descripción:** Recibe un archivo PDF, valida formato y tamaño, calcula el checksum SHA-256 en memoria, valida unicidad ante persistencia, orquesta la extracción de texto en el extractor y persiste el documento resultante.

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `Content-Type` | `string` | Sí | `multipart/form-data` |
| `X-Request-ID` | `string` | No | Identificador único de correlación (UUID v4). Si no se envía, el orquestador lo autogenera. |

### 2.2. Parámetros de Ruta / Query
*Ninguno.*

### 2.3. Request Body (Form Data)
| Campo | Tipo | Requerido | Restricciones |
|---|---|---|---|
| `file` | `UploadFile (binary)` | Sí | Extensión `.pdf`, Content-Type `application/pdf`, tamaño máximo según configuración (por defecto 10 MB). |

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK
Devuelve el documento recién creado y persistido con su ID asignado.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
  "extracted_text": "Texto completo extraído del documento PDF...",
  "created_at": "2026-10-19T10:30:00",
  "filename": "documento.pdf",
  "page_count": 16,
  "file_size_bytes": 1048576
}
```

**Tipos de los campos de respuesta:**

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | `string` | Identificador único asignado por el servicio de persistencia. |
| `checksum` | `string` | Checksum SHA-256 del PDF subido (64 caracteres hexadecimales). |
| `extracted_text` | `string` | Texto extraído del documento PDF. |
| `created_at` | `string` | Timestamp de creación del documento en persistencia. |
| `filename` | `string` | Nombre original del archivo PDF subido. |
| `page_count` | `integer` | Cantidad de páginas del PDF. |
| `file_size_bytes` | `integer` | Tamaño del archivo PDF en bytes. |

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa | Formato JSON de Error |
|---|---|---|
| **400 Bad Request** | El archivo no tiene Content-Type `application/pdf`, o no termina en `.pdf`, o excede el tamaño máximo permitido (10 MB). | `{"detail": "El archivo debe ser PDF. Tipo recibido: text/plain"}` o `{"detail": "El archivo excede el tamaño máximo permitido de 10MB"}` |
| **409 Conflict** | Ya existe un documento persistido con el mismo checksum SHA-256 (duplicado). | `{"detail": "Document with checksum <hash> already exists (409 Conflict)"}` |
| **422 Unprocessable Entity** | El PDF está corrupto, encriptado con contraseña o no contiene páginas legibles. | `{"detail": "No se pudo procesar el PDF: PDF corrupto o no legible: EOF marker not found"}` |
| **502 Bad Gateway** | Fallo en la comunicación con el extractor o la persistencia tras agotar reintentos con backoff. | `{"detail": "Error de comunicación con el servicio downstream: <servicio>"}` |
| **503 Service Unavailable** | El orquestador se encuentra en estado pausado (`/pause`) o el servicio de persistencia no está disponible. | `{"detail": "Servicio temporalmente pausado"}` |

---

## 5. Efectos Colaterales
- **Persistencia:** Si el archivo es válido y único, se almacena un nuevo registro en la colección de documentos de MongoDB vía microservicio de persistencia.
- **Llamadas Downstream:**
  1. `GET /api/v1/documents/checksum/{checksum}` a Persistencia (verificación fail-fast).
  2. `POST /api/v1/extract` al Extractor (solo si el checksum no existe).
  3. `POST /api/v1/documents` a Persistencia (guardar el documento).
- **Idempotencia:** No idempotente. Enviar el mismo archivo dos veces produce 200 en la primera y 409 Conflict en la segunda.

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:**
  - Chequeo de duplicado (409 fail-fast): `< 50 ms`.
  - Flujo completo exitoso (archivo de 5 páginas / ~1MB): `< 500 ms` p95.
- **Concurrencia:** Soportar al menos 50 peticiones simultáneas de subida sin agotar memoria (gestión 100% en streaming / memoria acotada a 10 MB por request).
- **Timeouts:** Timeout en llamada al extractor: `30s`. Timeout en llamada a persistencia: `5s`.
