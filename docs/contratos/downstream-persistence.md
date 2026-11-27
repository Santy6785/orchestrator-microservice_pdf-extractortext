# Contratos Downstream: Orquestador -> Microservicio Persistencia

> **Propósito:** Define los contratos formales de las llamadas HTTP que el Orquestador realiza hacia el microservicio **Persistencia** (puerto por defecto `8002`, URL configurada vía `PERSISTENCE_SERVICE_URL`).

---

## 1. Llamada: `GET /api/v1/documents/by-checksum/{checksum}` (Chequeo de Duplicado)

### 1.1. Contexto de Invocación
Invocado de forma inmediata por el Orquestador (`IngestionService.process_document` -> `PersistenceClient.check_duplicate_by_checksum`) al recibir un archivo en `POST /api/v1/documents/upload`, una vez calculado su SHA-256 en memoria (optimización fail-fast antes de llamar al Extractor).

### 1.2. Petición
- **Método:** `GET`
- **Ruta:** `/api/v1/documents/by-checksum/{checksum}`
- **Headers:** `X-Request-ID: <uuid>`

#### Ejemplo Ejecutable (`curl`)
```bash
curl -i -X GET "http://localhost:8002/api/v1/documents/by-checksum/c8ce4e97a404b12b1d8f0e245f04ff607be1048b16d973c2f23bab86655c808b" \
  -H "X-Request-ID: 550e8400-e29b-41d4-a716-446655440000"

---

## 2. Llamada: `GET /health/ready` (Health Check de Persistencia)

### 2.1. Contexto de Invocación

Invocado por el Orquestador (`control.py::_probe_health` -> `PersistenceClient.get`) durante el chequeo de readiness (`GET /api/v1/control/health/ready` y `GET /api/v1/control/health`). Se ejecuta en paralelo con el chequeo de Extractor y con timeout individual (`HEALTH_TIMEOUT_SECONDS`, default `2.0`) y timeout global (`HEALTH_GLOBAL_TIMEOUT_SECONDS`, `5.0`).

### 2.2. Petición (Orquestador -> Persistencia)

- **Método:** `GET`
- **Ruta:** `/health/ready`
- **Headers:** Ninguno obligatorio

### 2.3. Respuesta Esperada (Persistencia -> Orquestador)

| Estado | Código HTTP | Cuerpo JSON esperado | Significado para el Orquestador |
|--------|-------------|----------------------|---------------------------------|
| Saludable | `200 OK` | `{"status": "ready", "database": "connected"}` | El campo `status` pertenece a `_PERSISTENCE_HEALTHY_STATUSES = {"ready"}`. Dependencia considerada disponible. |
| No saludable | `503 Service Unavailable` | `{"status": "unhealthy", "database": "disconnected"}` | El campo `status` NO pertenece al set de saludables. Dependencia considerada `unreachable`. |
| Error / Fallo | Cualquier otro / timeout / excepción | — | Se trata como `unreachable`. El fallo de Persistencia no afecta el estado del Extractor; se reportan de forma independiente. |

> **Nota de compatibilidad:** El orquestador lee únicamente el campo `status` del cuerpo JSON. Otros campos adicionales (como `database`) son ignorados. Si el microservicio Persistencia cambia el valor de `"ready"` o la ruta `/health/ready`, el orquestador marcará la dependencia como `unreachable` y `/api/v1/control/health` devolverá `503`.

#### Ejemplo Ejecutable (`curl`) — Saludable

```bash
curl -i "http://localhost:8002/health/ready"
# HTTP/1.1 200 OK
# Content-Type: application/json
#
# {"status": "ready", "database": "connected"}
```

#### Ejemplo Ejecutable (`curl`) — No saludable

```bash
curl -i "http://localhost:8002/health/ready"
# HTTP/1.1 503 Service Unavailable
# Content-Type: application/json
#
# {"status": "unhealthy", "database": "disconnected"}
```

### 2.4. Coordinación entre ambos chequeos

El endpoint `GET /api/v1/control/health` del Orquestador devuelve `200` únicamente si **ambos** servicios (Extractor y Persistencia) reportan estado saludable. Si al menos uno falla, devuelve `503 Service Unavailable` con el detalle de cuál dependencia está `unreachable`.