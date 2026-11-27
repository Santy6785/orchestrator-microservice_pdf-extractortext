# Contrato de Endpoint: Apagado Seguro (Graceful Shutdown)

## 1. Identificación

- **Método HTTP:** `POST`
- **Ruta:** `/api/v1/control/shutdown`
- **Etiqueta:** `control`
- **Acceso:** Interno (no expuesto públicamente por Traefik). Solo accesible desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
- **Descripción:** Inicia la secuencia de finalización segura (graceful shutdown) del microservicio. Deja de aceptar nuevas peticiones (devuelve 503) y espera un periodo de gracia para que finalicen todas las peticiones que están en curso antes de detener el proceso del servidor mediante `SIGTERM`.

---

## 2. Petición (Entrada)

### 2.1. Headers

| Header | Tipo | Requerido | Descripción |
|---|---|---|---|
| `X-Request-ID` | `string` | No | Identificador de correlación. |
| `X-Internal-Token` | `string` | No | Token de acceso interno. |

### 2.2. Request Body

*No aplica.*

---

## 3. Respuestas (Salida)

### 3.1. Éxito: HTTP 200 OK

Confirma la orden de apagado y el número de peticiones activas que se esperan drenar.

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**

```json
{
  "status": "shutting_down",
  "active_requests": 3,
  "message": "Apagado seguro iniciado. Esperando finalización de peticiones en curso."
}
```

### 3.2. Error: HTTP 409 Conflict

Si el proceso de apagado ya está en progreso o el servicio está detenido.

**Payload JSON:**

```json
{
  "detail": "El proceso de apagado ya se encuentra en progreso o el servicio está detenido.",
  "code": "conflict",
  "request_id": "<uuid>"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa |
|---|---|
| **200 OK** | Señal de apagado aceptada y programada en segundo plano. |
| **403 Forbidden** | Acceso desde host no interno y sin `X-Internal-Token` válido. |
| **409 Conflict** | El proceso de apagado ya se encuentra en progreso o el servicio está detenido. |

---

## 5. Efectos Colaterales

- **Ciclo de vida:** Transición `RUNNING/PAUSED → SHUTTING_DOWN`. Luego `SHUTTING_DOWN → STOPPED` tras el drenado o vencimiento del periodo de gracia.
- **Middleware de control de tráfico:** Rechaza nuevas peticiones a rutas no-control con `503 Service Unavailable` durante el apagado.
- **Drenado de peticiones:** Espera hasta `GRACE_PERIOD_SECONDS` (15s) a que finalicen las peticiones activas antes de enviar `SIGTERM`.
- **Señal de parada:** `SIGTERM` (señal estándar de terminación ordenada). El manejador de señales del orquestador (`register_signal_handlers`) captura `SIGTERM`/`SIGINT` y ejecuta el drenado antes de `sys.exit()`.
- **Configuración Docker:** `STOPSIGNAL SIGTERM` y `stop_grace_period: 20s` en `docker-compose.yml`.

---

## 6. Requisitos No Funcionales (RNF)

- **Latencia de Respuesta:** `< 20 ms` (responde inmediatamente al cliente antes de ejecutar el drenado).
- **Periodo de Gracia:** Timeout máximo de espera de peticiones activas: `15s`.
- **Estado en memoria:** El estado de apagado vive en memoria por instancia de proceso.
