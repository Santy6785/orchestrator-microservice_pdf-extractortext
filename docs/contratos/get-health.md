# Contrato de Endpoint: Comprobación de Salud del Sistema (Health Check)

## 1. Identificación
- **Métodos y Rutas:**
  - `GET /health` (Ruta raíz para Traefik / Docker healthcheck)
  - `GET /api/v1/health` (Ruta bajo prefijo de API para compatibilidad con el monolito)
- **Etiqueta:** `monitoring`
- **Descripción:** Verifica el estado operativo de la aplicación y la conectividad activa con todas sus dependencias downstream (`extractor` y `persistencia`).

---

## 2. Petición (Entrada)

### 2.1. Headers
| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |

### 2.2. Parámetros / Body
*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK (Todas las dependencias saludables)
**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "dependencies": {
    "extractor": {
      "status": "connected",
      "url": "http://extractor:8001"
    },
    "persistence": {
      "status": "connected",
      "url": "http://persistence:8002"
    }
  }
}
```

### 3.2. Degradado o Fallo: HTTP 503 Service Unavailable (Una o más dependencias no responden)
**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "status": "unhealthy",
  "version": "0.1.0",
  "dependencies": {
    "extractor": {
      "status": "connected",
      "url": "http://extractor:8001"
    },
    "persistence": {
      "status": "disconnected",
      "url": "http://persistence:8002",
      "error": "Connection refused"
    }
  }
}
```

---

## 4. Códigos de Estado y Errores
| Código HTTP | Causa |
|---|---|
| **200 OK** | El orquestador y todos los microservicios downstream responden a sus respectivos healthchecks. |
| **503 Service Unavailable** | El orquestador está pausado, o al menos un microservicio downstream (`extractor` o `persistencia`) está inaccesible o no saludable. |

---

## 5. Efectos Colaterales
- **Persistencia:** Ninguno.
- **Llamadas Downstream:**
  - `GET /health` hacia el microservicio Extractor.
  - `GET /health` hacia el microservicio Persistencia.
- **Idempotencia:** Idempotente (`GET`).

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia Objetivo:** `< 100 ms` p95 (consultas en paralelo con `asyncio.gather`).
- **Concurrencia:** Soportar sondeos de monitoreo frecuentes (cada 5 a 10s desde Traefik y orquestadores).
- **Timeouts:** Timeout por chequeo individual de dependencia: `2s`.
