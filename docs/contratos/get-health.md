# Contrato de Endpoint: Comprobación de Salud del Sistema (Health Check)

## 1. Identificación

- **Métodos y Rutas:**
  - `GET /api/v1/control/health/live` — Liveness: verifica que el proceso del Orchestrator responde. No llama a dependencias downstream.
  - `GET /api/v1/control/health/ready` — Readiness: verifica el Orchestrator y sus dependencias downstream (Extractor y Persistencia).
  - `GET /api/v1/control/health` — Alias de `/ready`. Mantiene compatibilidad con los health checks de Docker y Traefik.
- **Etiqueta:** `monitoring`
- **Descripción:** Verifica el estado operativo de la aplicación y la conectividad activa con las dependencias downstream (`extractor` y `persistencia`).

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

### 3.1. Liveness: HTTP 200 OK

El proceso del Orchestrator está funcionando. No se consulta a dependencias externas.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "orchestrator": "alive"
}
```

### 3.2. Readiness: HTTP 200 OK (todas las dependencias saludables)

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "orchestrator": "healthy",
  "extractor": "ok",
  "persistence": "ready"
}
```

### 3.3. Readiness: HTTP 503 Service Unavailable (una o más dependencias no responden)

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "orchestrator": "healthy",
  "extractor": "ok",
  "persistence": "unreachable"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Ruta | Causa |
|---|---|---|
| **200 OK** | `/health/live` | El proceso del Orchestrator responde. |
| **200 OK** | `/health/ready` | El orquestador y ambas dependencias (Extractor, Persistencia) están disponibles. |
| **503 Service Unavailable** | `/health/ready` | Al menos una dependencia downstream no responde o no está lista. |
| **200 OK / 503 Service Unavailable** | `/health` | Mismo comportamiento que `/health/ready` (alias). |

---

## 5. Efectos Colaterales

- **Persistencia:** Ninguno.
- **Llamadas Downstream (solo `/ready` y `/health`):**
  - `GET /health` hacia el microservicio Extractor (espera `{"status": "ok"}`).
  - `GET /health/ready` hacia el microservicio Persistencia (espera `{"status": "ready"}`).
- **Llamadas Downstream (solo `/live`):** Ninguna.
- **Idempotencia:** Idempotente (`GET`).

---

## 6. Requisitos No Funcionales (RNF)

- **Latencia Objetivo:** `< 100 ms` p95 (consultas en paralelo con `asyncio.gather`).
- **Concurrencia:** Soportar sondeos de monitoreo frecuentes (cada 5 a 10s desde Traefik y orquestadores).
- **Timeouts:**
  - Timeout por chequeo individual de dependencia: `2s` (`HEALTH_TIMEOUT_SECONDS`).
  - Timeout global para el chequeo de readiness: `5s` (`HEALTH_GLOBAL_TIMEOUT_SECONDS`).
- **Bloqueo:** Ningún health check queda bloqueado indefinidamente. El timeout global acota el tiempo de espera total.
