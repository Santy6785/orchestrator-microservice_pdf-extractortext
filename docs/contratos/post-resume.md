# Contrato de Endpoint: Reanudar Servicio

## 1. Identificación

- **Método HTTP:** `POST`
- **Ruta:** `/api/v1/control/resume`
- **Etiqueta:** `control`
- **Acceso:** Interno (no expuesto públicamente por Traefik). Solo accesible desde hosts internos (loopback) o presentando el header `X-Internal-Token` con el valor configurado en `INTERNAL_CONTROL_TOKEN`.
- **Descripción:** Reanuda el procesamiento normal del microservicio orquestador tras haber estado en estado pausado.

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
  "message": "Service resumed"
}
```

### 3.2. Error: HTTP 409 Conflict

Si el servicio está en proceso de apagado (`SHUTTING_DOWN` o `STOPPED`), la reanudación es rechazada.

**Payload JSON:**

```json
{
  "detail": "No se puede reanudar: servicio en apagado o detenido.",
  "code": "conflict",
  "request_id": "<uuid>"
}
```

---

## 4. Códigos de Estado y Errores

| Código HTTP | Causa |
|---|---|
| **200 OK** | El estado se modificó exitosamente a activo (o ya estaba activo: idempotente). |
| **403 Forbidden** | Acceso desde host no interno y sin `X-Internal-Token` válido. |
| **409 Conflict** | El servicio está en proceso de apagado o detenido. |

---

## 5. Efectos Colaterales

- **Ciclo de vida:** Transición `PAUSED → RUNNING`. Si ya está `RUNNING`, la operación es idempotente (200).
- **Middleware de control de tráfico:** Las peticiones a rutas no-control vuelven a ser procesadas normalmente (se dejan de rechazar con 503).
- **Idempotencia:** `POST /resume` sucesivos devuelven 200.

---

## 6. Requisitos No Funcionales (RNF)

- **Latencia de Respuesta:** `< 20 ms`.
- **Estado en memoria:** El flag de pausa vive en memoria por instancia de proceso.
