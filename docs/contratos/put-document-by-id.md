# Contrato de Endpoint: Actualizar Texto Extraído de un Documento

## 1. Identificación
- **Método HTTP:** `PUT`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Etiqueta:** `documents`
- **Descripción:** Actualiza el campo `extracted_text` de un documento existente en persistencia sin modificar su checksum original ni su ID.

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `Content-Type` | `string` | Sí | `application/json` |
| `X-Request-ID` | `string` | No | Identificador de correlación. |

### 2.2. Parámetros de Ruta
| Parámetro | Tipo | Requerido | Descripción |
|---|---|---|---|
| `document_id` | `string` | Sí | ID del documento a actualizar. |

### 2.3. Request Body (JSON)
```json
{
  "extracted_text": "Texto corregido o actualizado manualmente por el usuario."
}
```

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK
Devuelve el documento completo con el texto actualizado.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "id": "65f1a2b3c4d5e6f7a8b9c0d1",
  "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
  "extracted_text": "Texto corregido o actualizado manualmente por el usuario.",
  "created_at": "2026-10-19T10:30:00"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa | Formato JSON de Error |
|---|---|---|
| **404 Not Found** | El ID indicado no existe en persistencia. | `{"detail": "Documento con ID 65f1a2b3c4d5e6f7a8b9c0d1 no encontrado"}` |
| **422 Unprocessable Entity** | Body JSON malformado o falta el campo requerido `extracted_text`. | `{"detail": [{"loc": ["body", "extracted_text"], "msg": "Field required", "type": "missing"}]}` |
| **502 Bad Gateway** | Error al invocar la actualización en persistencia tras reintentos. | `{"detail": "Error de comunicación con el servicio de persistencia"}` |
| **503 Service Unavailable** | Orquestador en estado pausado. | `{"detail": "Servicio temporalmente pausado"}` |

---

## 5. Efectos Colaterales
- **Persistencia:** Modifica el registro en MongoDB a través del microservicio de persistencia.
- **Llamadas Downstream:** `PUT /api/v1/documents/{document_id}` a Persistencia.
- **Idempotencia:** Idempotente (`PUT`). Aplicar la misma modificación múltiples veces produce el mismo resultado final en la base de datos.

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 80 ms` p95.
- **Concurrencia:** Soportar al menos 100 actualizaciones simultáneas.
- **Timeouts:** Timeout hacia persistencia: `3s`.
