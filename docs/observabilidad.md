# Observabilidad del Orchestrator

Este documento consolida toda la información sobre observabilidad del microservicio Orquestador: health checks, trace, métricas, logging y lifecycle.

---

## 1. Health Checks

### 1.1. Endpoints

| Método | Ruta | Descripción | Downstream | Timeout | Código HTTP |
|--------|------|-------------|------------|---------|-------------|
| `GET` | `/api/v1/control/health/live` | Liveness: verifica que el proceso responde | Ninguno | N/A | 200 |
| `GET` | `/api/v1/control/health/ready` | Readiness: verifica Extractor + Persistencia | Extractor, Persistencia | Individual 2s / Global 5s | 200 / 503 |
| `GET` | `/api/v1/control/health` | Alias de `/ready` (Docker/Traefik) | Extractor, Persistencia | Individual 2s / Global 5s | 200 / 503 |

### 1.2. Respuestas

**Liveness (200):**
```json
{"orchestrator": "alive"}
```

**Readiness (200 - todas sanas):**
```json
{
  "orchestrator": "healthy",
  "extractor": "ok",
  "persistence": "ready"
}
```

**Readiness (503 - una o más fallan):**
```json
{
  "orchestrator": "healthy",
  "extractor": "ok",
  "persistence": "unreachable"
}
```

### 1.3. Comportamiento ante fallos

- Cada dependencia se sondea en paralelo con `asyncio.gather`.
- El fallo de una dependencia **no enmascara** el estado de la otra.
- Cualquier error de transporte, timeout o respuesta no saludable se reporta como `"unreachable"`.
- Timeout individual por dependencia: `HEALTH_TIMEOUT_SECONDS` (default 2s).
- Timeout global para el chequeo completo: 5s (`HEALTH_GLOBAL_TIMEOUT_SECONDS`).
- Ningún health check queda bloqueado indefinidamente.

### 1.4. Contratos downstream

- **Extractor:** `GET /health`, espera `{"status": "ok"}`.
- **Persistencia:** `GET /health/ready`, espera `{"status": "ready"}`.

---

## 2. Trace

### 2.1. Endpoint

| Método | Ruta | Descripción | Acceso |
|--------|------|-------------|--------|
| `GET` | `/api/v1/control/trace` | Último request/response (metadata segura) | Interno |

### 2.2. Respuesta (sin traces)

```json
{
  "trace": null,
  "message": "No hay traces registrados aún."
}
```

### 2.3. Respuesta (con trace)

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

### 2.4. Política de redacción

**Nunca se almacena ni devuelve:**
- Contenido binario de PDFs.
- Texto extraído de PDFs.
- Tokens, contraseñas ni secretos.
- Cabeceras de autenticación (`Authorization`, `Cookie`, `Set-Cookie`, etc.).
- Query params con claves sensibles (`password`, `token`, `secret`, etc.).

Todos los campos de texto se truncan a 500 caracteres. La ruta `/trace` no se registra a sí misma (evita recursividad).

### 2.5. Retención

Últimas 100 entradas por instancia de proceso. Escrituras y lecturas protegidas por `asyncio.Lock`. Solo en memoria, no se persiste en disco.

---

## 3. Métricas

### 3.1. Endpoint

| Método | Ruta | Descripción | Acceso |
|--------|------|-------------|--------|
| `GET` | `/api/v1/control/metrics` | Métricas operativas en JSON | Interno |

### 3.2. Métricas disponibles

| Métrica | Descripción | Etiquetas |
|---------|-------------|-----------|
| `uptime_seconds` | Tiempo transcurrido desde arranque | — |
| `status` | Estado del servicio (`running`) | — |
| `active_requests` | Peticiones en curso (gauge) | — |
| `requests_total` | Total de peticiones HTTP procesadas | — |
| `requests_by_status` | Conteo por grupo de estado | `status_group`: `2xx`, `4xx`, `5xx` |
| `requests_by_method` | Conteo por método HTTP | `method`: `GET`, `POST`, `PUT`, `DELETE` |
| `requests_by_endpoint` | Conteo por grupo de endpoint | `endpoint_group`: `documents`, `control`, `other` |
| `request_latency_ms` | Histograma de latencia HTTP | buckets: 10, 50, 100, 250, 500, 1000, 2500, 5000 ms |
| `errors_total` | Total de errores (4xx/5xx) | — |
| `errors_by_code` | Errores por código legible | `code`: `http_404`, `http_422`, `http_502`, etc. |
| `errors_by_service` | Errores por servicio downstream | `service`: `extractor`, `persistence` |
| `downstream_calls` | Llamadas a downstream por servicio y resultado | `service`, `outcome`: `success`, `error` |
| `downstream_errors` | Errores de downstream por servicio | `service` |
| `downstream_retries_total` | Reintentos downstream por servicio | `service` |
| `downstream_latency_ms` | Histograma de latencia downstream | `service`, buckets fijos |

### 3.3. Ejemplo de respuesta

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
  "errors_total": 175,
  "downstream_retries_total": {
    "extractor": 2,
    "persistence": 1
  }
}
```

### 3.4. Cardinalidad

Las etiquetas son de baja cardinalidad. No se permiten etiquetas de alta variabilidad como `request_id`, `document_id` o paths completos. Las métricas viven en memoria por instancia y se reinician al reiniciar el contenedor.

---

## 4. Logging

### 4.1. Formato

Todos los logs se emiten como JSON de una línea con los campos:

| Campo | Descripción |
|-------|-------------|
| `timestamp` | Timestamp ISO 8601 UTC |
| `level` | Nivel de log (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`) |
| `service` | Siempre `orchestrator` |
| `request_id` | ID de correlación de la petición |
| `message` | Mensaje del log (sanitizado) |

### 4.2. Destino

- **stdout:** Todos los niveles (`DEBUG` y superior según `LOG_LEVEL`).
- **stderr:** Niveles `WARNING` y superior (para separación de logs en contenedores Docker).

### 4.3. Niveles

| Nivel | Valor | Uso |
|-------|-------|-----|
| `DEBUG` | 10 | Depuración detallada |
| `INFO` | 20 | Información general (default) |
| `WARNING` / `WARN` | 30 | Advertencias |
| `ERROR` | 40 | Errores |
| `CRITICAL` | 50 | Errores críticos |

Configurado mediante `LOG_LEVEL` (default `INFO`).

### 4.4. Request ID

- Obtenido del header `X-Request-ID` o autogenerado (UUIDv4) si no está presente.
- Propagado vía `ContextVar` (`request_id_var`) a todos los logs de la petición.
- Enviado a servicios downstream en el header `X-Request-ID`.
- Incluido en todas las respuestas de error y en el header de respuesta `X-Request-ID`.

### 4.5. Redacción de datos sensibles

Los headers `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-Api-Key`, `X-Auth-Token`, `Access-Token`, `Refresh-Token` se redactan como `[REDACTED]`. El contenido PDF (`%PDF-`) se redacts como `[REDACTED_PDF_BYTES]`. Las rutas de usuario se redactan como `[REDACTED_PATH]`. Los stack traces se sanitizan antes de escribirse.

### 4.6. Evitar duplicación

- `uvicorn.access` no propaga al root logger (evita doble salida).
- Solo un handler por destino (`stdout` y `stderr`).
- `configure_logging()` limpia handlers preexistentes antes de configurar.

---

## 5. Lifecycle y Control de Admisión

### 5.1. Estados del servicio

| Estado | Descripción |
|--------|-------------|
| `RUNNING` | Servicio operativo, acepta peticiones. |
| `PAUSED` | Servicio pausado, rechaza nuevas peticiones no-control con 503. |
| `SHUTTING_DOWN` | Apagado en progreso, rechaza nuevas peticiones, drena activas. |
| `STOPPED` | Servicio detenido (terminal). |

### 5.2. Transiciones válidas

| Desde | Hacia | Acción |
|-------|-------|--------|
| `RUNNING` | `PAUSED` | `POST /pause` |
| `PAUSED` | `RUNNING` | `POST /resume` |
| `RUNNING` / `PAUSED` | `SHUTTING_DOWN` | `POST /shutdown` o `SIGTERM` |
| `SHUTTING_DOWN` | `STOPPED` | Fin del drenado o timeout de gracia |

Transiciones inválidas devuelven **HTTP 409 Conflict**.

### 5.3. Endpoints de ciclo de vida (todos internos)

| Método | Ruta | Descripción | Códigos HTTP |
|--------|------|-------------|--------------|
| `POST` | `/api/v1/control/pause` | Pausa el servicio | 200, 403, 409 |
| `POST` | `/api/v1/control/resume` | Reanuda el servicio | 200, 403, 409 |
| `POST` | `/api/v1/control/shutdown` | Apagado seguro con drenado | 200, 403, 409 |

### 5.4. Graceful Shutdown

1. `POST /shutdown` establece estado `SHUTTING_DOWN` y `PAUSED`.
2. Se programa una tarea en segundo plano que drena peticiones activas.
3. Espera hasta `GRACE_PERIOD_SECONDS` (15s) a que finalicen las peticiones en curso.
4. Envía `SIGTERM` al proceso propio.
5. El manejador de señales (`SIGTERM`/`SIGINT`) ejecuta un drenado rápido (20s) antes de `sys.exit()`.

### 5.5. Protección de acceso

Los endpoints `/pause`, `/resume`, `/shutdown`, `/metrics` y `/trace` están protegidos por `internal_access_middleware`:

- Si `INTERNAL_CONTROL_TOKEN` no está configurado (modo desarrollo): acceso permitido desde cualquier host.
- Si está configurado: se requiere header `X-Internal-Token` válido o host loopback.
- Cualquier otro origen recibe **HTTP 403 Forbidden**.

---

## 6. Manejo de Errores y Excepciones

### 6.1. Contrato uniforme

Todas las respuestas de error siguen el esquema `ErrorResponse`:

```json
{
  "detail": "Descripción legible",
  "code": "código_legible_por_maquina",
  "request_id": "uuid",
  "existing_id": "uuid (solo duplicados)"
}
```

### 6.2. Códigos HTTP estándar

| Rango | Uso |
|-------|-----|
| 200 | Éxito |
| 400 | Solicitud inválida (tamaño de archivo, formato PDF) |
| 404 | Recurso no encontrado |
| 409 | Conflicto (documento duplicado, transición inválida) |
| 413 | Payload demasiado grande |
| 422 | Error de validación |
| 429 | Demasiadas solicitudes (extractor) |
| 502 | Error de gateway (downstream falló tras reintentos) |
| 503 | Servicio no disponible (timeout de conexión, dependencia no responde) |

### 6.3. No exponer información interna

- No se exponen stack traces al cliente.
- No se revelan rutas internas, nombres de host, ni detalles de infraestructura.
- Los stack traces se registran internamente en logs (sanitizados) pero no se envían al cliente.

---

## 7. Variables de Configuración

| Variable | Default | Descripción |
|----------|---------|-------------|
| `EXTRACTOR_SERVICE_URL` | *requerido* | URL base del microservicio Extractor |
| `PERSISTENCE_SERVICE_URL` | *requerido* | URL base del microservicio Persistencia |
| `LOG_LEVEL` | `INFO` | Nivel de logging |
| `EXTRACTOR_TIMEOUT_SECONDS` | `30.0` | Timeout cliente Extractor (segundos) |
| `PERSISTENCE_TIMEOUT_SECONDS` | `5.0` | Timeout cliente Persistencia (segundos) |
| `HEALTH_TIMEOUT_SECONDS` | `2.0` | Timeout clientes health check (segundos) |
| `INTERNAL_CONTROL_TOKEN` | *ninguno* | Token opcional para endpoints de control internos |

---

## 8. Ejecución y Pruebas

### 8.1. Desarrollo local

```bash
uvicorn app.main:app --reload
```

### 8.2. Docker

```bash
./build.sh   # lint → test → docker build
docker compose up -d
```

### 8.3. Tests

```bash
uv run --extra dev pytest -q -m "not system"
```

Todos los tests deben pasar. Los tests de sistema (`-m system`) requieren los tres servicios levantados y se excluyen por defecto.

---

## 9. Referencias

- `docs/contratos/get-health.md` — Contrato detallado de health checks.
- `docs/contratos/get-trace.md` — Contrato detallado de trace.
- `docs/contratos/get-metrics.md` — Contrato detallado de métricas.
- `docs/contratos/post-pause.md`, `post-resume.md`, `post-shutdown.md` — Contratos de ciclo de vida.
- `docs/conectividad.md` — Topología de red y contratos downstream.
- `docs/decisiones.md` — ADRs (D1–D9).
- `README.md` — Visión general y guía de inicio rápido.
