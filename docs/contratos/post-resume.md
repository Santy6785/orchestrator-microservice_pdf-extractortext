# Contrato de Endpoint: Reanudar Servicio

## 1. Identificación
- **Método HTTP:** `POST`
- **Ruta:** `/resume`
- **Etiqueta:** `control`
- **Descripción:** Reanuda el procesamiento normal del microservicio orquestador tras haber estado en estado pausado.

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
  "status": "running",
  "message": "Servicio reanudado exitosamente. Se aceptan nuevas peticiones."
}
```

---

## 4. Códigos de Estado y Errores
| Código HTTP | Causa |
|---|---|
| **200 OK** | El estado se modificó exitosamente a activo (`running`). |

---

## 5. Efectos Colaterales
- **Ciclo de vida:** Modifica `is_paused = False`. Las peticiones a la API vuelven a ser procesadas normalmente.
- **Idempotencia:** Idempotente.
