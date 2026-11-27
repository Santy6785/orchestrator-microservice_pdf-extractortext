# Contrato de Endpoint: Trace de Request/Response

## 1. Identificación

- **Método HTTP:** `GET`
- **Ruta:** `/api/v1/control/trace`
- **Etiqueta:** `monitoring`
- **Acceso:** Interno (no expuesto públicamente por Traefik). Solo accesible desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
- **Descripción:** Devuelve la última entrada de trace registrada por el orquestador. Contiene metadata segura del último request/response visto. Nunca incluye cuerpos de PDF, texto extraído, tokens, secretos ni credenciales.

---

## 2. Petición (Entrada)

### 2.1. Headers

| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |
| `X-Internal-Token` | `string` | No | Token de acceso interno. Requerido si `INTERNAL_CONTROL_TOKEN` está configurado y el cliente no es loopback. |

### 2.2. Request Body

*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK (sin traces registrados)

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**

```json
{
  "trace": null,
  "message": "No hay traces registrados aún."
}
```

### 3.2. Éxito: HTTP 200 OK (con trace disponible)

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**

```json
{
  "trace": {
    "request_id": "req-abc-123",
    "method": "GET",
    "path": "/api/v1/documents/upload",
    "status_code": 200,
    "response_size_bytes": 1024,
    "duration_ms": 45.67,
    "timestamp": 1732654800.123,
    "headers": {
      "accept": "application/json",
      "content-type": "multipart/form-data"
    },
    "query_params": {
      "page": "1"
    },
    "downstream_calls": []
  }
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa |
|---|---|
| **200 OK** | Trace devuelto correctamente (puede ser `null` si no hay traces). |
| **403 Forbidden** | Acceso desde host no interno y sin `X-Internal-Token` válido. |

---

## 5. Política de Redacción de Datos Sensibles

El endpoint `/trace` **nunca almacena ni devuelve**:

- Contenido binario de PDFs.
- Texto extraído de PDFs.
- Tokens, contraseñas ni secretos.
- Cabeceras de autenticación (`Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `X-Auth-Token`, `Access-Token`, `Refresh-Token`).
- Nombres de archivo ni contenido de archivos subidos.
- Query params con claves sensibles (`password`, `token`, `secret`, `api_key`, `access_token`, `refresh_token`, `session`, `session_id`).

Todos los valores de texto se truncan a 500 caracteres. Los campos de texto se sanitizan aplicando los mismos patrones de redacción que el logging estructurado.

## 6. Requisitos No Funcionales (RNF)

- **Retención:** Últimas 100 entradas por instancia de proceso (`deque(maxlen=100)`). Al llenarse, se descarta la entrada más antigua.
- **Concurrencia:** Escrituras y lecturas protegidas por `asyncio.Lock` para evitar race conditions.
- **Almacenamiento:** Solo en memoria. No se guarda información en disco.
- **Recursividad:** La propia ruta `/trace` no se registra en el trace para evitar recursividad.
