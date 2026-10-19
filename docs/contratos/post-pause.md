# Contrato de Endpoint: Pausar Servicio

## 1. Identificación
- **Método HTTP:** `POST`
- **Ruta:** `/pause`
- **Etiqueta:** `control`
- **Descripción:** Pausa temporalmente el microservicio. Rechaza inmediatamente cualquier nueva petición entrante a la API con HTTP 503, permitiendo completar las peticiones que ya se encuentren en ejecución. Útil para ventanas de mantenimiento o drenado ante fallos.

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
- `X-Request-ID: <uuid>`

**Payload JSON:**
```json
{
  "status": "paused",
  "message": "Servicio pausado. Nuevas peticiones serán rechazadas con HTTP 503."
}
```

---

## 4. Códigos de Estado y Errores
| Código HTTP | Causa |
|---|---|
| **200 OK** | El estado se modificó exitosamente a pausado. |

---

## 5. Efectos Colaterales
- **Ciclo de vida:** El middleware de control de tráfico intercepta peticiones posteriores y devuelve `503 Service Unavailable`.
- **Idempotencia:** Idempotente (`POST /pause` sucesivos devuelven 200 confirmando el estado).
