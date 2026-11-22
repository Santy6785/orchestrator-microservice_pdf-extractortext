# Contrato de Endpoint: Obtener Documento por ID

## 1. Identificación
- **Método HTTP:** `GET`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Etiqueta:** `documents`
- **Descripción:** Obtiene los detalles completos de un documento almacenado identificado por su ID único (incluyendo el texto extraído).

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |

### 2.2. Parámetros de Ruta
| Parámetro | Tipo | Requerido | Descripción |
|---|---|---|---|
| `document_id` | `string` (UUID v4) | Sí | Identificador único del documento en formato UUID v4. Un ID con formato inválido produce HTTP 422 Unprocessable Entity. |

### 2.3. Request Body
*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK
Devuelve el documento completo.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
  "extracted_text": "Texto completo extraído del documento PDF...",
  "created_at": "2026-10-19T10:30:00"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa | Formato JSON de Error |
|---|---|---|
| **404 Not Found** | El ID indicado no corresponde a ningún documento existente. | `{"detail": "Documento con ID 65f1a2b3c4d5e6f7a8b9c0d1 no encontrado"}` |
| **422 Unprocessable Entity** | El ID recibido no tiene formato UUID v4 válido. | `{"detail": [...]}` (error de validación de FastAPI) |
| **502 Bad Gateway** | Error al consultar el microservicio de persistencia. | `{"detail": "Error de comunicación con el servicio de persistencia"}` |
| **503 Service Unavailable** | Orquestador en estado pausado. | `{"detail": "Servicio temporalmente pausado"}` |

---

## 5. Efectos Colaterales
- **Persistencia:** Ninguno (operación de solo lectura).
- **Llamadas Downstream:** `GET /api/v1/documents/{document_id}` al microservicio de Persistencia.
- **Idempotencia:** Idempotente (`GET`).

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 50 ms` p95.
- **Concurrencia:** Soportar al menos 300 peticiones concurrentes.
- **Timeouts:** Timeout hacia persistencia: `3s`.
