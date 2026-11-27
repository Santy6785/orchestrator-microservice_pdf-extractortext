# Contrato de Endpoint: Métricas Operativas

## 1. Identificación

- **Método HTTP:** `GET`
- **Ruta:** `/api/v1/control/metrics`
- **Etiqueta:** `monitoring`
- **Acceso:** Interno (no expuesto públicamente por Traefik). Solo accesible desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
- **Descripción:** Expone métricas operativas del orquestador en formato JSON: peticiones totales, peticiones por código de estado, peticiones activas, errores, latencias, llamadas y reintentos downstream, y estado de componentes.

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

### 3.1. Éxito: HTTP 200 OK

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**

```json
{
  "service": "orchestrator",
  "uptime_seconds": 3600.5,
  "status": "running",
  "active_requests": 2,
  "requests_total": 1450,
  "requests_by_status": {
    "2xx": 1200,
    "4xx": 150,
    "5xx": 5
  },
  "requests_by_method": {
    "GET": 1000,
    "POST": 400,
    "DELETE": 50
  },
  "requests_by_endpoint": {
    "documents": 800,
    "control": 600,
    "other": 50
  },
  "request_latency_ms": {
    "buckets": [10, 50, 100, 250, 500, 1000, 2500, 5000],
    "counts": [500, 300, 100, 50, 20, 10, 5, 2, 3],
    "sum": 45000.5,
    "count": 1450
  },
  "errors_total": 175,
  "errors_by_code": {
    "http_404": 80,
    "http_422": 15,
    "http_502": 5
  },
  "errors_by_service": {
    "extractor": 20,
    "persistence": 5
  },
  "downstream_calls": {
    "extractor": {
      "success": 1200,
      "error": 20
    },
    "persistence": {
      "success": 2395,
      "error": 5
    }
  },
  "downstream_retries_total": {
    "extractor": 2,
    "persistence": 1
  },
  "downstream_latency_ms": {
    "extractor": {
      "buckets": [10, 50, 100, 250, 500, 1000, 2500, 5000],
      "counts": [400, 200, 50, 20, 10, 5, 2, 1, 0],
      "sum": 30000.0,
      "count": 1220
    },
    "persistence": {
      "buckets": [10, 50, 100, 250, 500, 1000, 2500, 5000],
      "counts": [800, 400, 100, 30, 10, 5, 2, 1, 0],
      "sum": 15000.0,
      "count": 1400
    }
  }
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa |
|---|---|
| **200 OK** | Métricas generadas correctamente. |
| **403 Forbidden** | Acceso desde host no interno y sin `X-Internal-Token` válido. |

---

## 5. Requisitos No Funcionales (RNF)

- **Latencia Objetivo:** `< 10 ms` (cálculo puramente en memoria).
- **Sobrecarga:** Cero I/O para recolectar métricas.
- **Cardinalidad:** Las etiquetas son de baja cardinalidad (`method`, `status_group`, `endpoint_group`, `service`, `outcome`, `code`). No se permiten etiquetas de alta variabilidad como `request_id`, `document_id` o paths completos.
- **Retención:** Las métricas viven en memoria por instancia de proceso y se reinician al reiniciar el contenedor.
