# Contrato de Endpoint: Métricas Operativas

## 1. Identificación
- **Método HTTP:** `GET`
- **Ruta:** `/metrics`
- **Etiqueta:** `monitoring`
- **Descripción:** Expone métricas operativas del orquestador en formato JSON: peticiones totales, peticiones por código de estado, peticiones activas, estado actual y uptime.

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |

### 2.2. Request Body
*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK
**Response Headers:**
- `Content-Type: application/json`

**Payload JSON:**
```json
{
  "service": "orchestrator",
  "status": "running",
  "uptime_seconds": 3600.5,
  "active_requests": 2,
  "requests_total": 1450,
  "requests_by_status": {
    "200": 1200,
    "400": 150,
    "409": 80,
    "422": 15,
    "502": 5
  },
  "downstream_calls": {
    "extractor": {
      "total": 1220,
      "errors": 20
    },
    "persistence": {
      "total": 2400,
      "errors": 5
    }
  }
}
```

---

## 4. Códigos de Estado y Errores
| Código HTTP | Causa |
|---|---|
| **200 OK** | Métricas generadas correctamente. |

---

## 5. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 10 ms` (cálculo puramente en memoria).
- **Sobrecarga:** Cero I/O para recolectar métricas.
