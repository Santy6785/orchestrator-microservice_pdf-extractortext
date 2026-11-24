# Registro de Decisiones de Arquitectura (ADR) - Orquestador

Este documento registra las decisiones de arquitectura (**D1–D9**) adoptadas para el microservicio **Orquestador** (`orchestrator-microservice_pdf-extractortext`).

## Resumen de Decisiones

| ID | ADR | Título | Estado |
|----|-----|--------|--------|
| **D1** | ADR-001 | Mecanismo de resolución y descubrimiento de microservicios | Aprobado |
| **D2** | ADR-002 | Delimitación de responsabilidades en Checksum y Duplicados (Fail-Fast) | Aprobado |
| **D3** | ADR-003 | Política de inmutabilidad WORM y diferimiento de `PUT /api/v1/documents/{id}` a v1.1 | Aprobado |
| **D4** | ADR-004 | Unificación de configuración en `app/core/config.py` sin credenciales de DB | Aprobado |
| **D5** | ADR-005 | Retiro del endpoint legacy `POST /api/v1/documents/` (`PlainTextResponse`) | Aprobado |
| **D6** | ADR-006 | Manejo de fallo de persistencia tras extracción exitosa (`HTTP 502 Bad Gateway`) | Aprobado |
| **D7** | ADR-007 | Clientes HTTP resilientes con timeouts, reintentos y propagación de `X-Request-ID` | Aprobado |
| **D8** | ADR-008 | Control de admisión (`PauseMiddleware`) y endpoints de ciclo de vida operativo | Aprobado |
| **D9** | ADR-009 | Formato uniforme de errores JSON (`ErrorResponse`) y configuración explícita de CORS | Aprobado |

---

## D1 (ADR-001): Mecanismo de resolución y descubrimiento de microservicios

- **Estado:** Aprobado
- **Fecha:** 2026-10-19
- **Contexto:**
  Existía una discrepancia entre el uso de HashiCorp Consul como service discovery dinámico y la configuración mediante URLs directas por variables de entorno. En el despliegue del sistema, Traefik actúa como proxy inverso y Docker Compose provee resolución DNS interna entre contenedores.
- **Alternativas consideradas:**
  1. *HashiCorp Consul:* Servicio centralizado de descubrimiento dinámico. Descartado por introducir complejidad operativa excesiva, dependencias adicionales y latencia de resolución innecesaria para un despliegue acotado de microservicios.
  2. *URLs directas por variables de entorno con DNS de Docker / Traefik:* El orquestador recibe `EXTRACTOR_SERVICE_URL` y `PERSISTENCE_SERVICE_URL` por entorno.
- **Decisión:**
  Se adopta la **Opción 2** (URLs directas por variables de entorno). Traefik y la red interna de Docker Compose gestionan el enrutamiento y la resolución de nombres.
- **Consecuencias:**
  - *Positivas:* Arquitectura simple, determinista, sin dependencias externas pesadas y alineada con el despliegue en contenedores.
  - *Negativas:* Cambios de topología fuera de Docker/Traefik requieren actualizar las variables de entorno del servicio.

---

## D2 (ADR-002): Delimitación de responsabilidades en Checksum y Duplicados (Fail-Fast)

- **Estado:** Aprobado
- **Fecha:** 2026-10-19
- **Contexto:**
  En el monolito original el checksum se calculaba durante la extracción y luego se consultaba duplicidad en base de datos. En una arquitectura distribuida, enviar un PDF grande al servicio Extractor antes de verificar si ya fue procesado desperdicia red, CPU y memoria.
- **Alternativas consideradas:**
  1. *Delegar checksum y validación al Extractor:* El orquestador envía siempre el PDF al extractor y luego intenta persistir. Descartado por alto costo de procesamiento en archivos duplicados.
  2. *Cálculo temprano en Orquestador + verificación con Persistencia (Fail-Fast):* El orquestador calcula el hash SHA-256 en memoria (~1 ms) y consulta a Persistencia (`GET /api/v1/documents/by-checksum/{checksum}`). Si ya existe, responde `409 Conflict` de inmediato sin invocar al Extractor.
- **Decisión:**
  Se adopta la **Opción 2**:
  - **Orquestador:** calcula el SHA-256 en memoria y coordina la verificación temprana.
  - **Persistencia:** expone la consulta por checksum y garantiza la unicidad estricta en base de datos mediante índice único.
  - **Extractor:** solo procesa documentos PDF previamente validados como no duplicados.
- **Consecuencias:**
  - *Positivas:* Ahorro significativo de CPU y ancho de banda ante envíos duplicados.
  - *Negativas:* Agrega una consulta HTTP liviana a Persistencia en el camino feliz (mitigada por la baja latencia de la red interna).

---

## D3 (ADR-003): Política de inmutabilidad WORM y diferimiento de `PUT /api/v1/documents/{id}` a v1.1

- **Estado:** Aprobado
- **Fecha:** 2026-10-19
- **Contexto:**
  Durante la definición de contratos REST entre el Orquestador y el servicio de Persistencia se evaluó exponer operaciones de actualización completa de documentos mediante `PUT /api/v1/documents/{id}`. Sin embargo, el modelo de almacenamiento de documentos extraídos responde a una política WORM (*Write Once, Read Many*) para preservar la integridad entre el archivo PDF original, su checksum SHA-256 y el texto extraído.
- **Alternativas consideradas:**
  1. *Exponer `PUT /api/v1/documents/{id}` en v1.0:* Permitiría mutar texto o metadatos posteriores a la ingesta, rompiendo la consistencia WORM y obligando a implementar versionado o re-cálculo de hashes en v1.0.
  2. *Aplicar política WORM en v1.0 y diferir la edición a v1.1:* Mantener los documentos inmutables tras su creación (admitiendo únicamente lectura y eliminación) y posponer la edición controlada a una iteración futura (`v1.1`).
- **Decisión:**
  Se adopta la **Opción 2**. Se establece la política **WORM (Write Once, Read Many)** para la versión v1.0 y se retira `PUT /api/v1/documents/{id}` del orquestador (documentado en `docs/contratos/put-document-by-id.md`), difiriendo la edición de documentos a la versión `v1.1`.
- **Consecuencias:**
  - *Positivas:* Garantiza inmutabilidad e integridad referencial entre checksum y texto extraído en v1.0; simplifica el contrato entre Orquestador y Persistencia.
  - *Negativas:* Los clientes que necesiten corregir un documento en v1.0 deben eliminarlo (`DELETE`) y volver a subirlo (`POST /upload`).

---

## D4 (ADR-004): Unificación de configuración en `app/core/config.py` sin credenciales de DB

- **Estado:** Aprobado
- **Fecha:** 2026-10-19
- **Contexto:**
  El monolito mantenía dos mecanismos solapados de configuración (`Settings` y el protocolo `ConfigService`) con variables acopladas directamente a MongoDB. En el nuevo diseño, el Orquestador es completamente stateless y no debe tener acceso ni conocimiento de la base de datos.
- **Alternativas consideradas:**
  1. *Mantener `ConfigService` y variables de MongoDB por compatibilidad:* Mantiene acoplamiento innecesario y código duplicado.
  2. *Centralizar en `app/core/config.py` con `pydantic-settings` (`SettingsConfigDict`):* Definir una única clase `Settings` con URLs de microservicios downstream (`EXTRACTOR_SERVICE_URL`, `PERSISTENCE_SERVICE_URL`), timeouts, reintentos, tamaño máximo de archivo y nivel de logging, eliminando toda referencia a bases de datos.
- **Decisión:**
  Se adopta la **Opción 2**. Se descarta `ConfigService` y se centraliza la configuración en `app/core/config.py` usando Pydantic V2.
- **Consecuencias:**
  - *Positivas:* Código limpio e idiomático en FastAPI, aislamiento total respecto de la capa de datos y inyección de dependencias sencilla en tests mediante `dependency_overrides`.
  - *Negativas:* Ninguna.

---

## D5 (ADR-005): Retiro del endpoint legacy `POST /api/v1/documents/` (`PlainTextResponse`)

- **Estado:** Aprobado
- **Fecha:** 2026-10-19
- **Contexto:**
  El monolito exponía `POST /api/v1/documents/` devolviendo texto plano (`PlainTextResponse`) además de `POST /api/v1/documents/upload` con respuesta JSON. El análisis del frontend confirmó que únicamente consume `/upload` esperando JSON, y la especificación de microservicios exige comunicación uniforme por JSON sobre HTTP REST.
- **Alternativas consideradas:**
  1. *Mantener ambos endpoints:* Conserva código muerto y rompe la uniformidad de contratos JSON del orquestador.
  2. *Retirar `POST /api/v1/documents/` y unificar la ingesta en `POST /api/v1/documents/upload`:* Estandariza las respuestas en formato JSON (`DocumentResponse`).
- **Decisión:**
  Se adopta la **Opción 2**. El endpoint legacy de texto plano queda retirado definitivamente en el microservicio Orquestador.
- **Consecuencias:**
  - *Positivas:* 100% de comunicación JSON uniforme en la API pública del orquestador y eliminación de código muerto.
  - *Negativas:* Cualquier consumidor externo hipotético que esperara `.txt` directo debe consumir `/api/v1/documents/upload` y leer el campo `extracted_text` del JSON.

---

## D6 (ADR-006): Manejo de fallo de persistencia tras extracción exitosa (`HTTP 502 Bad Gateway`)

- **Estado:** Aprobado
- **Fecha:** 2026-11-21
- **Contexto:**
  El orquestador coordina primero la extracción de texto mediante Extractor y luego el almacenamiento mediante Persistencia. Si Extractor responde exitosamente pero Persistencia falla al guardar el registro, el cliente no debe recibir una confirmación exitosa de un documento que no quedó persistido.
- **Alternativas consideradas:**
  1. *Propagar el código de estado crudo de Persistencia o guardar estado local temporal:* Rompe la uniformidad del contrato de errores downstream del orquestador o viola su naturaleza stateless.
  2. *Responder `HTTP 502 Bad Gateway` con `ErrorResponse` sin estado local ni rollback:* Considerar exitoso el flujo únicamente cuando Persistencia confirma el alta; ante fallo downstream tras agotar reintentos, registrar el error y devolver `502 Bad Gateway`.
- **Decisión:**
  Se adopta la **Opción 2**. El orquestador devuelve `HTTP 502 Bad Gateway` siguiendo el esquema estándar `ErrorResponse` (`code` y `message` dentro de `detail`), sin almacenar estado local ni ejecutar mecanismos de compensación sobre Extractor.
- **Consecuencias:**
  - *Positivas:* Evita falsos positivos de creación ante el cliente y mantiene estrictamente la separación de responsabilidades entre servicios.
  - *Negativas:* El procesamiento realizado por Extractor en ese intento no se revierte y el cliente debe reintentar la operación.

---

## D7 (ADR-007): Clientes HTTP resilientes con timeouts, reintentos y propagación de `X-Request-ID`

- **Estado:** Aprobado
- **Fecha:** 2026-10-25
- **Contexto:**
  La comunicación entre el Orquestador, Extractor y Persistencia ocurre sobre red HTTP. Sin timeouts acotados ni reintentos ante fallos transitorios, una demora o caída momentánea de un servicio downstream puede bloquear workers o provocar errores evitables, además de dificultar la trazabilidad distribuida entre logs de distintos contenedores.
- **Alternativas consideradas:**
  1. *Llamadas `httpx` directas en cada cliente sin capa común:* Genera duplicación de manejo de errores, ausencia de backoff y pérdida de correlación de peticiones.
  2. *Clase base `BaseClient` (`app/clients/base.py`) sobre `httpx.AsyncClient`:* Centraliza timeouts configurables, reintentos con backoff exponencial para errores de red/5xx y propagación automática de la cabecera `X-Request-ID` desde el contexto de la petición.
- **Decisión:**
  Se adopta la **Opción 2**. Tanto `ExtractorClient` como `PersistenceClient` heredan de `BaseClient`, unificando la política de resiliencia y trazabilidad.
- **Consecuencias:**
  - *Positivas:* Mayor tolerancia a fallos transitorios de red, prevención de bloqueos indefinidos y correlación de logs end-to-end mediante `X-Request-ID`.
  - *Negativas:* Incrementa ligeramente la latencia máxima en escenarios donde se agotan todos los reintentos configurados.

---

## D8 (ADR-008): Control de admisión (`PauseMiddleware`) y endpoints de ciclo de vida operativo

- **Estado:** Aprobado
- **Fecha:** 2026-10-25
- **Contexto:**
  La especificación operativa del sistema requiere controlar el ciclo de vida del microservicio en entornos orquestados (pausar tráfico entrante sin matar procesos activos, reanudar servicio, iniciar apagado controlado y verificar salud real de dependencias).
- **Alternativas consideradas:**
  1. *Depender únicamente de señales de proceso del contenedor (`SIGTERM`):* No permite pausar admisión temporalmente manteniendo activos los endpoints de control ni exponer estado de salud compuesto.
  2. *Middleware de estado (`PauseMiddleware`) + endpoints `/api/v1/health`, `/pause`, `/resume`, `/shutdown` y `/metrics`:* Intercepta peticiones entrantes cuando el flag de pausa/apagado está activo devolviendo `503 Service Unavailable` (excepto rutas de control), mientras `/health` verifica la conectividad real hacia Extractor y Persistencia.
- **Decisión:**
  Se adopta la **Opción 2**. Se implementa el middleware de control de admisión junto con los endpoints operativos en `app/api/v1/control.py`.
- **Consecuencias:**
  - *Positivas:* Permite mantenimiento y drenado seguro de peticiones sin pérdida de tráfico en vuelo y brinda visibilidad real del estado de dependencias a Traefik/Docker.
  - *Negativas:* Requiere mantener estado en memoria del flag de pausa por instancia de proceso.

---

## D9 (ADR-009): Formato uniforme de errores JSON (`ErrorResponse`) y configuración explícita de CORS

- **Estado:** Aprobado
- **Fecha:** 2026-10-25
- **Contexto:**
  En el monolito coexistían respuestas de error heterogéneas (excepciones HTTP de FastAPI, errores de validación de Pydantic y trazas no estructuradas) junto con políticas CORS permisivas. Los consumidores del orquestador (frontend y clientes REST) requieren un contrato de error predecible y orígenes CORS controlados por configuración.
- **Alternativas consideradas:**
  1. *Mantener el manejo de excepciones por defecto de FastAPI:* Produce formatos distintos según el tipo de fallo (`422` vs `500` vs `HTTPException`) y omite contexto de trazabilidad.
  2. *Manejadores globales de excepciones hacia `ErrorResponse` + CORS parametrizado en `Settings`:* Estandariza todas las respuestas de error en un esquema JSON consistente (`code`, `message`, `request_id`) y configura `CORSMiddleware` a partir de variables de entorno.
- **Decisión:**
  Se adopta la **Opción 2**. Todas las excepciones de dominio, downstream, HTTP y validación se traducen al formato uniforme `ErrorResponse` y los orígenes CORS se definen explícitamente vía configuración.
- **Consecuencias:**
  - *Positivas:* Contrato de errores consistente y fácil de consumir por el frontend; mejora en seguridad y observabilidad al incluir `request_id` en cada error.
  - *Negativas:* Ninguna.
