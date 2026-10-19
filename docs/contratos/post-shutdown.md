# Contrato de Endpoint: Apagado Seguro (Graceful Shutdown)

## 1. Identificación
- **Método HTTP:** `POST`
- **Ruta:** `/shutdown`
- **Etiqueta:** `control`
- **Descripción:** Inicia la secuencia de finalización segura (graceful shutdown) del microservicio. Deja de aceptar nuevas peticiones (devuelve 503) y espera un periodo de gracia para que finalicen todas las peticiones que están en curso antes de detener el proceso del servidor.

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

---

## 4. Códigos de Estado y Errores
| Código HTTP | Causa |
|---|---|
| **200 OK** | Señal de apagado aceptada y programada en segundo plano. |
| **409 Conflict** | El proceso de apagado ya se encuentra en progreso. |

---

## 5. Efectos Colaterales
- **Ciclo de vida:** Modifica el estado global a `is_shutting_down = True`. Programa una tarea asíncrona para enviar `SIGTERM`/detener el bucle de eventos tras drenar peticiones activas (máximo 15 segundos).

---

## 6. Requisitos No Funcionales (RNF)
- **Latencia de Respuesta:** `< 20 ms` (responde inmediatamente al cliente antes de ejecutar el drenado).
- **Periodo de Gracia:** Timeout máximo de espera de peticiones activas: `15s`.
