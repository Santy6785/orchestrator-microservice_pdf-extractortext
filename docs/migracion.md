# Mapa de Migración del Monolito a Microservicios (Fase 1)

> **Origen:** Monolito `pdf-extractortext`  
> **Destino:** Arquitectura en 4 microservicios (`frontend`, `orquestador`, `extractor`, `persistencia`).  
> **Ámbito de este encargo:** Implementación exclusiva del microservicio **Orquestador**, preservando los contratos y la compatibilidad con el frontend.

---

## 1. Principios de la Migración

1. **El Orquestador no accede a MongoDB:** Ningún driver de base de datos (`motor`, `pymongo`) ni variables de entorno de conexión (`MONGODB_URL`, `MONGODB_DB_NAME`) forman parte del orquestador. La persistencia es delegada vía HTTP REST al microservicio de persistencia.
2. **La extracción de PDF pertenece al Extractor:** Las librerías de manipulación de archivos (`pypdf`, `pymupdf`) se trasladan al microservicio extractor. El orquestador solo maneja los bytes del archivo en memoria para reenviarlos.
3. **Preservación total de contratos para el Frontend:** Todos los endpoints y rutas originales (`/api/v1/documents/*`) se mantienen con los mismos métodos, parámetros de consulta (`skip`, `limit`), esquemas de respuesta JSON y códigos de estado HTTP (200, 204, 400, 404, 409, 422). El frontend no sufre cambios.
4. **Resiliencia y Observabilidad en el Orquestador:** Clientes HTTP con reintentos (retry) y backoff exponencial, timeouts configurables, propagación de `X-Request-ID`, endpoints de ciclo de vida seguro (`/shutdown`, `/pause`, `/resume`), salud de dependencias (`/health`) y métricas (`/metrics`).

---

## 2. Mapa Detallado Módulo por Módulo

| Módulo Monolito | Destino | Justificación y Rol en la Nueva Arquitectura |
|---|---|---|
| **`app/main.py`** | **Orquestador** (adaptado) | Se convierte en el punto de entrada FastAPI del orquestador. Configura middlewares (`CORSMiddleware`, `RequestIDMiddleware`, `ServerLifecycleMiddleware`), manejadores globales de excepciones JSON, lifespan y registro de rutas. |
| **`app/api/routes.py`** | **Orquestador** (`app/api/v1/`) | Controladores HTTP del orquestador. Expone los endpoints consumidos por el frontend (`/upload`, CRUD `/documents/`, etc.). Valida parámetros HTTP y delega la ejecución a `OrchestrationService` y `DocumentManagementService`. |
| **`app/api/dependencies.py`** | **Orquestador** (`app/api/dependencies.py`) | Inyección de dependencias de FastAPI (`Depends`). En el orquestador inyecta los clientes HTTP (`ExtractorClient`, `PersistenceClient`), configuración (`Settings`) y servicios de orquestación. |
| **`app/services/pdf_service.py`** | **ELIMINADO** | Código huérfano/duplicado previo a la arquitectura limpia. No es utilizado en producción por ningún componente. |
| **`app/infrastructure/pdf/pdf_service.py`** | **ELIMINADO** | Wrapper incompleto y redundante que no implementa el método `process_pdf` del protocolo. Solo figuraba en un test unitario aislado. |
| **`app/application/pdf/pdf_extractor.py`** | **Extractor** | Protocolo/puerto (`PdfExtractor`) y dataclass de resultado (`PdfProcessingResult`). Define el contrato de dominio del microservicio extractor. |
| **`app/infrastructure/pdf/pypdf_extractor.py`** | **Extractor** | Implementación concreta de extracción de texto y dimensiones usando `pypdf`. Pasa a ser el núcleo del microservicio extractor. |
| **`app/config/settings.py`** | **Orquestador / Extractor / Persistencia** (específico por servicio) | En el orquestador se convierte en `app/core/config.py` con `pydantic-settings`, conteniendo URLs de dependencias (`EXTRACTOR_SERVICE_URL`, `PERSISTENCE_SERVICE_URL`), timeouts, retries y nivel de log. Sin variables de DB. |
| **`app/application/config_service.py`** | **ELIMINADO** | Sobre-abstracción innecesaria que envolvía a `Settings`. Se reemplaza por inyección directa de `Settings` con `Depends(get_settings)`, estándar en FastAPI. |
| **`app/application/services/checksum_service.py`** | **Dividido entre Orquestador y Persistencia** | - **Cálculo (Orquestador):** Se ejecuta en `app/services/orchestrator_service.py` en memoria para validación fail-fast (409 inmediato sin saturar la red).<br>- **Unicidad (Persistencia):** Verificación de existencia en base de datos e índice único en colección MongoDB. |
| **`app/application/services/document_ingestion_service.py`** | **Orquestador** (`app/services/ingestion_orchestrator.py`) | Lógica de orquestación de subida: recibe archivo -> calcula SHA-256 -> verifica existencia con Persistencia -> si no existe, invoca Extractor -> envía texto y metadatos a Persistencia -> retorna JSON al cliente. |
| **`app/application/services/document_service.py`** | **Dividido (Orquestador y Persistencia)** | - **En Orquestador:** Servicio fachada que delega operaciones CRUD (`get_all`, `get_by_id`, `update`, `delete`) al cliente HTTP de persistencia.<br>- **En Persistencia:** Lógica de negocio CRUD sobre la base de datos MongoDB. |
| **`app/application/dto/document_dto.py`** | **Orquestador** (`app/schemas/document.py`) | Se migra a esquemas Pydantic V2 (`DocumentResponse`, `DocumentListResponse`, `DocumentUpdate`, `IngestionResult`) para validación y serialización de peticiones/respuestas. |
| **`app/domain/models/document.py`** | **Persistencia** | Entidad de dominio con mapeo BSON/MongoDB (`_id`, `checksum`, `extracted_text`, `created_at`). El orquestador no gestiona entidades de base de datos directamente, solo DTOs/esquemas. |
| **`app/domain/repositories/document_repository.py`** | **Persistencia** | Puerto de persistencia (`DocumentRepositoryPort`). |
| **`app/infrastructure/persistence/database.py`** | **Persistencia** | Gestión de conexión con Motor/MongoDB y Singleton `Database`. |
| **`app/infrastructure/persistence/mongo_repository.py`** | **Persistencia** | Repositorio concreto de MongoDB (`MongoDocumentRepository`). |
| **`app/domain/exceptions.py`** | **Orquestador y Persistencia** | Excepciones de dominio (`DocumentNotFoundError`, `ServiceUnavailableError`, `DownstreamServiceError`). |
| **`frontend/index.html`** | **Frontend** | Interfaz web del usuario servida por Nginx. Se mantiene 100% idéntica, apuntando al Orquestador a través de Traefik. |
| **`tests/conftest.py`** | **Orquestador** (`tests/conftest.py`) | Fixtures de testing adaptados: `TestClient`, mocks de clientes HTTP con `respx` o `httpx.MockTransport`. |
| **`tests/integration/test_upload_pdf.py`** | **Orquestador** (`tests/integration/`) | Test de validación y subida de PDF preservado para asegurar compatibilidad de contratos. |
| **`tests/integration/test_routes_error_mapping.py`** | **Orquestador** (`tests/integration/`) | Mapeo de errores HTTP 400, 404, 409 y 422 preservado estrictamente. |
| **`tests/unit/test_pagination_default.py`** | **Orquestador** (`tests/unit/`) | Verificación de paginación y valor por defecto de `default_page_size`. |
| **`tests/integration/test_documents_crud_http.py`** | **Orquestador** (`tests/integration/`) | Verificación de rutas CRUD HTTP desacopladas de MongoDB mediante cliente HTTP mockeado. |
| **`tests/unit/test_mongo_repository.py`** | **Persistencia** | Tests del repositorio MongoDB. |
| **`tests/unit/test_pdf_extractor.py`** | **Extractor** | Tests de extracción de texto y dimensiones PDF. |

---

## 3. Estado de los Endpoints de la API

| Método | Ruta | Estado | Consumidor | Manejo en Orquestador |
|---|---|---|---|---|
| `POST` | `/api/v1/documents/upload` | **Conservado sin cambios** | `frontend/index.html` | Orquesta cálculo de hash, verificación en persistencia, extracción en extractor y guardado en persistencia. Retorna JSON. |
| `GET` | `/api/v1/documents/` | **Conservado sin cambios** | Frontend / Clientes REST | Consulta documentos con paginación (`skip`, `limit`) delegando en persistencia. Retorna `List[DocumentListResponse]`. |
| `GET` | `/api/v1/documents/{id}` | **Conservado sin cambios** | Frontend / Clientes REST | Obtiene documento por ID delegando en persistencia. Retorna `DocumentResponse` o 404. |
| `PUT` | `/api/v1/documents/{id}` | **Conservado sin cambios** | Frontend / Clientes REST | Actualiza texto extraído delegando en persistencia. Retorna `DocumentResponse` o 404. |
| `DELETE` | `/api/v1/documents/{id}` | **Conservado sin cambios** | Frontend / Clientes REST | Elimina documento por ID delegando en persistencia. Retorna 204 No Content o 404. |
| `GET` | `/api/v1/health` y `/health` | **Conservado y enriquecido** | Traefik / Orquestador | En el monolito solo chequeaba MongoDB. En el orquestador verifica la conectividad y salud de `extractor` y `persistencia`. |
| `POST` | `/api/v1/documents/` | **DEPRECADO / ELIMINADO** | Ninguno (código muerto) | El endpoint legacy retornaba `text/plain` descargable. El frontend no lo utiliza (usa `/upload`). Para cumplir con la restricción de *"comunicación por JSON"* de la arquitectura, se descarta del orquestador activo. |
| `POST` | `/shutdown` | **Nuevo (Requerido por spec)** | Administración / Docker | Apagado seguro con drenado de peticiones en curso (graceful shutdown). |
| `POST` | `/pause` | **Nuevo (Requerido por spec)** | Administración / Traefik | Pausa el microservicio; rechaza nuevas peticiones entrantes con 503 mientras drena peticiones activas. |
| `POST` | `/resume` | **Nuevo (Requerido por spec)** | Administración / Traefik | Reanuda el procesamiento normal de peticiones. |
| `GET` | `/metrics` | **Nuevo (Requerido por spec)** | Observabilidad | Métricas básicas de peticiones totales, fallidas, activas y latencia promedio. |

---

## 4. Estructura de Capas del Orquestador

Para cumplir con la arquitectura en 3 capas (MVC) solicitada:

```
orchestrator-microservice_pdf-extractortext/
├── app/
│   ├── api/                 # Capa de Presentación / Controladores
│   │   ├── dependencies.py  # Inyección de dependencias
│   │   └── v1/
│   │       ├── documents.py # Endpoints de documentos (/api/v1/documents)
│   │       └── control.py   # Endpoints de ciclo de vida (/health, /shutdown, /pause, /resume, /metrics)
│   ├── services/            # Capa de Aplicación / Servicios de Orquestación
│   │   ├── ingestion_orchestrator.py # Flujo de subida (hash -> check -> extract -> persist)
│   │   └── document_service.py       # Coordinación de consultas y CRUD
│   ├── clients/             # Capa de Clientes HTTP hacia otros Microservicios
│   │   ├── base.py          # Cliente base HTTP con retry, backoff, timeouts y X-Request-ID
│   │   ├── extractor_client.py   # Cliente hacia el microservicio extractor
│   │   └── persistence_client.py # Cliente hacia el microservicio persistencia
│   ├── core/                # Configuración, Logging y Estado
│   │   ├── config.py        # Settings con Pydantic V2 (URLs, timeouts, log levels)
│   │   ├── logging.py       # Logger estructurado configurable (input, error, debug, warn)
│   │   ├── lifecycle.py     # Gestor de estado (active requests, pause/resume, shutdown)
│   │   └── middleware.py    # Middlewares de Request-ID y control de pausa
│   ├── schemas/             # Modelos de transferencia de datos (Pydantic DTOs)
│   │   ├── document.py      # Schemas para petición y respuesta de documentos
│   │   └── common.py        # Schemas para errores, salud y métricas
│   └── main.py              # Application Factory y Composition Root
├── docs/
│   ├── analisis/
│   │   └── orquestador-analisis.md
│   ├── contratos/           # Contratos de la Fase 2
│   ├── migracion.md         # Este documento
│   └── decisiones.md        # Registro de ADRs
├── tests/
│   ├── unit/                # Tests unitarios con mocks
│   ├── integration/         # Tests de rutas con clientes simulados
│   └── system/              # Tests end-to-end con app levantada y dobles
├── pyproject.toml           # Configuración de dependencias con uv (hatchling)
├── Dockerfile               # Contenedor con uv
├── docker-compose.yml       # Definición con Traefik
└── build.sh                 # Script de validación (lint + test + docker build)
```
