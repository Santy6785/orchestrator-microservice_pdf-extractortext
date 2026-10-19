# Contrato de Endpoint: Eliminar Documento por ID

## 1. Identificación
- **Método HTTP:** `DELETE`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Etiqueta:** `documents`
- **Descripción:** Elimina definitivamente un documento de la base de datos a través del microservicio de persistencia.

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |

### 2.2. Parámetros de Ruta
| Parámetro | Tipo | Requerido | Descripción |
|---|---|---|---|
| `document_id` | `string` | Sí | ID del documento a eliminar. |

### 2.3. Request Body
*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 204 No Content
La eliminación se ejecutó exitosamente. No contiene cuerpo de respuesta.

**Response Headers:**
- `X-Request-ID: <uuid>`

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa | Formato JSON de Error |
|---|---|---|
| **404 Not Found** | El ID indicado no existe en la base de datos. | `{"detail": "Documento con ID 65f1a2b3c4d5e6f7a8b9c0d1 no encontrado"}` |
| **502 Bad Gateway** | Error en la llamada al microservicio de persistencia tras reintentos. | `{"detail": "Error de comunicación con el servicio de persistencia"}` |
| **503 Service Unavailable** | Orquestador en estado pausado. | `{"detail": "Servicio temporalmente pausado"}` |

---

## 5. Efectos Colaterales
- **Persistencia:** Elimina el documento de la base de datos en MongoDB.
- **Llamadas Downstream:** `DELETE /api/v1/documents/{document_id}` a Persistencia.
- **Idempotencia:** Idempotente en intención, pero llamadas subsiguientes al mismo ID retornan 404 Not Found una vez borrado.

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 50 ms` p95.
- **Concurrencia:** Soportar al menos 100 eliminaciones concurrentes.
- **Timeouts:** Timeout hacia persistencia: `3s`.
