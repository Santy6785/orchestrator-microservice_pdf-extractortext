# Contratos Downstream: Orquestador -> Microservicio Persistencia

> **Propósito:** Define los contratos formales de las llamadas HTTP que el Orquestador realiza hacia el microservicio **Persistencia** (puerto por defecto `8002`, URL configurada vía `PERSISTENCE_SERVICE_URL`).

---

## 1. Llamada: `GET /api/v1/documents/checksum/{checksum}` (Chequeo de Duplicado)

### 1.1. Contexto de Invocación
Invocado de forma inmediata por el Orquestador al recibir un archivo en `/upload` una vez calculado su SHA-256 en memoria.

### 1.2. Petición
- **Método:** `GET`
- **Ruta:** `/api/v1/documents/checksum/{checksum}`
- **Headers:** `X-Request-ID: <uuid>`

### 1.3. Respuestas Esperadas
- **HTTP 200 OK (Existe duplicado):**
  ```json
  {
    "exists": true,
    "document_id": "65f1a2b3c4d5e6f7a8b9c0d1",
    "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
  }
  ```
  *Acción en Orquestador:* Retornar de inmediato `HTTP 409 Conflict` al cliente sin llamar al Extractor.
- **HTTP 404 Not Found (Es único, no existe duplicado):**
  ```json
  {
    "exists": false,
    "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b"
  }
  ```
  *Acción en Orquestador:* Continuar el flujo enviando el PDF al Extractor.

---

## 2. Llamada: `POST /api/v1/documents` (Crear Documento)

### 2.1. Contexto de Invocación
Invocado por el Orquestador tras recibir la respuesta exitosa del Extractor.

### 2.2. Petición
- **Método:** `POST`
- **Ruta:** `/api/v1/documents`
- **Headers:**
  - `Content-Type: application/json`
  - `X-Request-ID: <uuid>`
- **Body (JSON):**
  ```json
  {
    "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
    "extracted_text": "Texto completo extraído...",
    "created_at": "2026-10-19T10:30:00"
  }
  ```

### 2.3. Respuestas Esperadas
- **HTTP 201 Created (o 200 OK):**
  ```json
  {
    "id": "65f1a2b3c4d5e6f7a8b9c0d1",
    "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
    "extracted_text": "Texto completo extraído...",
    "created_at": "2026-10-19T10:30:00"
  }
  ```
- **HTTP 409 Conflict:** Si ocurrió una colisión concurrente (índice único de MongoDB).

---

## 3. Llamada: `GET /api/v1/documents` (Listar con Paginación)

### 3.1. Petición
- **Método:** `GET`
- **Ruta:** `/api/v1/documents?skip={skip}&limit={limit}`
- **Headers:** `X-Request-ID: <uuid>`

### 3.2. Respuestas Esperadas
- **HTTP 200 OK:**
  ```json
  [
    {
      "id": "65f1a2b3c4d5e6f7a8b9c0d1",
      "checksum": "c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b",
      "created_at": "2026-10-19T10:30:00"
    }
  ]
  ```

---

## 4. Llamada: `GET /api/v1/documents/{document_id}` (Obtener Documento)

### 4.1. Petición
- **Método:** `GET`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Headers:** `X-Request-ID: <uuid>`

### 4.2. Respuestas Esperadas
- **HTTP 200 OK:** Devuelve documento completo con `id`, `checksum`, `extracted_text`, `created_at`.
- **HTTP 404 Not Found:** `{"detail": "Documento no encontrado"}`.

---

## 5. Llamada: `PUT /api/v1/documents/{document_id}` (Actualizar Texto)

### 5.1. Petición
- **Método:** `PUT`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Headers:** `Content-Type: application/json`, `X-Request-ID: <uuid>`
- **Body:** `{"extracted_text": "Texto actualizado"}`

### 5.2. Respuestas Esperadas
- **HTTP 200 OK:** Devuelve documento actualizado.
- **HTTP 404 Not Found:** Si no existe el ID.

---

## 6. Llamada: `DELETE /api/v1/documents/{document_id}` (Eliminar Documento)

### 6.1. Petición
- **Método:** `DELETE`
- **Ruta:** `/api/v1/documents/{document_id}`
- **Headers:** `X-Request-ID: <uuid>`

### 6.2. Respuestas Esperadas
- **HTTP 204 No Content:** Eliminado exitosamente.
- **HTTP 404 Not Found:** Si no existía.

---

## 7. Llamada: `GET /health` (Salud de Persistencia y MongoDB)

### 7.1. Petición y Respuesta
- **Método:** `GET`
- **Ruta:** `/health`
- **HTTP 200 OK:**
  ```json
  {
    "status": "healthy",
    "service": "persistence",
    "database": "connected"
  }
  ```
- **HTTP 503 Service Unavailable:** Si MongoDB no responde al ping.

---

## 8. Políticas de Red y Resiliencia en el Orquestador
- **Timeouts:** `5.0 segundos` para operaciones de lectura/escritura; `2.0 segundos` para health check.
- **Retry Policy:** Reintentar hasta 3 veces con backoff exponencial (`0.2s`, `0.5s`, `1.0s`) para fallos de conexión o 502/503/504 en lecturas y chequeo de duplicados.
- **Idempotencia en Escritura:** Reintentos seguros para `GET`, `PUT`, `DELETE`. En `POST`, reintentar solo en errores de conexión previos al handshake, evitando duplicados.
