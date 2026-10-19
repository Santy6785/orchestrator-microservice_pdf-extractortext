# Contrato de Endpoint: Listar Documentos con Paginación

## 1. Identificación
- **Método HTTP:** `GET`
- **Ruta:** `/api/v1/documents/`
- **Etiqueta:** `documents`
- **Descripción:** Obtiene una lista paginada de documentos almacenados en formato resumido (id, checksum, created_at).

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación único. |

### 2.2. Parámetros Query
| Parámetro | Tipo | Requerido | Default | Restricciones | Descripción |
|---|---|---|---|---|---|
| `skip` | `integer` | No | `0` | `>= 0` | Número de documentos a saltar (offset). |
| `limit` | `integer` | No | Config (`20`) | `1 <= limit <= 100` | Cantidad máxima de documentos a retornar. Si no se indica, usa `default_page_size` de configuración. |

### 2.3. Request Body
*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK
Devuelve un array JSON con los documentos en formato resumido.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
[
  {
    "id": "65f1a2b3c4d5e6f7a8b9c0d1",
    "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
    "created_at": "2026-10-19T10:30:00"
  },
  {
    "id": "65f1a2b3c4d5e6f7a8b9c0d2",
    "checksum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "created_at": "2026-10-19T11:15:22"
  }
]
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa | Formato JSON de Error |
|---|---|---|
| **422 Unprocessable Entity** | Parámetros query inválidos (`skip < 0`, `limit < 1` o `limit > 100`). | `{"detail": [{"loc": ["query", "limit"], "msg": "Input should be greater than or equal to 1", "type": "greater_than_equal"}]}` |
| **502 Bad Gateway** | Error en la llamada al microservicio de persistencia tras reintentos. | `{"detail": "Error de comunicación con el servicio de persistencia"}` |
| **503 Service Unavailable** | Orquestador en estado pausado. | `{"detail": "Servicio temporalmente pausado"}` |

---

## 5. Efectos Colaterales
- **Persistencia:** Ninguno (operación de solo lectura).
- **Llamadas Downstream:** `GET /api/v1/documents?skip={skip}&limit={limit}` al microservicio de Persistencia.
- **Idempotencia:** Idempotente (`GET`).

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 100 ms` p95 para páginas de 20 documentos.
- **Concurrencia:** Soportar al menos 200 peticiones concurrentes de consulta.
- **Timeouts:** Timeout hacia persistencia: `3s`.
