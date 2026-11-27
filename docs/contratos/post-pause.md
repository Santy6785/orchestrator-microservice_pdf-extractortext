# Contrato de Endpoint: Pausar Servicio

## 1. Identificación

- **Método HTTP:** `POST`
- **Ruta:** `/api/v1/control/pause`
- **Etiqueta:** `control`
- **Acceso:** Interno (no expuesto públicamente por Traefik). Solo accesible desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
- **Descripción:** Pausa temporalmente el microservicio. Rechaza inmediatamente cualquier nueva petición entrante a rutas no-control con HTTP 503, permitiendo completar las peticiones que ya se encuentren en ejecución. Útil para ventanas de mantenimiento o drenado ante fallos.

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

**Response Headers:**
- `Content-Type: application/json`
- `X-Request-ID: <uuid>`

**Payload JSON:**

```json
{
  "message": "Service paused"
}
```

### 3.2. Error: HTTP 409 Conflict

Si el servicio ya está en proceso de apagado (`SHUTTING_DOWN` o `STOPPED`), la pausa es rechazada.

**Payload JSON:**

```json
{
  "detail": "No se puede pausar: el servicio está en proceso de apagado o detenido.",
  "code": "conflict",
  "request_id": "<uuid>"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa |
|---|---|
| **200 OK** | El estado se modificó exitosamente a pausado (o ya estaba pausado: idempotente). |
| **403 Forbidden** | Acceso desde host no interno y sin `X-Internal-Token` válido. |
| **409 Conflict** | El servicio está en proceso de apagado o detenido. |

---

## 5. Efectos Colaterales

- **Ciclo de vida:** Transición `RUNNING → PAUSED`. Si ya está `PAUSED`, la operación es idempotente (200).
- **Middleware de control de tráfico:** Intercepta peticiones posteriores a rutas no-control y devuelve `503 Service Unavailable` con contrato JSON uniforme (`detail`, `code`, `request_id`).
- **Health durante la pausa:** `/health`, `/health/live` y `/health/ready` siguen respondiendo (no son bloqueados por la pausa).
- **Idempotencia:** `POST /pause` sucesivos devuelven 200 confirmando el estado.

---

## 6. Requisitos No Funcionales (RNF)

- **Latencia de Respuesta:** `< 20 ms`.
- **Estado en memoria:** El flag de pausa vive en memoria por instancia de proceso.
