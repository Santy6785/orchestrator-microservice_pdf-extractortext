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