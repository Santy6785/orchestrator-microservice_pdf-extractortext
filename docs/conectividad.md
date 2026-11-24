\# Conectividad e Integración entre Microservicios



> \*\*Repositorio:\*\* Orquestador (`orchestrator-microservice\_pdf-extractortext`)  

> \*\*Propósito:\*\* Documentar la topología de red, diagrama de flujo end-to-end, tabla de endpoints (públicos y downstream), matriz de errores y políticas de timeouts/reintentos entre los cuatro componentes del sistema (\*\*Frontend\*\*, \*\*Orquestador\*\*, \*\*Extractor\*\* y \*\*Persistencia\*\*).



\---



\## 1. Topología y Variables de Entorno



El sistema opera sobre una red interna de Docker Compose con enrutamiento externo a través de \*\*Traefik\*\* y descubrimiento por variables de entorno (ver \*\*D1 / ADR-001\*\* en `docs/decisiones.md`):



| Componente | Puerto interno | Variable de descubrimiento en Orquestador | Responsabilidad |

|------------|----------------|-------------------------------------------|-----------------|

| \*\*Frontend\*\* | `80` / `8080` | — (consumidor externo vía Traefik) | Interfaz web que envía PDFs y consulta documentos al Orquestador. |

| \*\*Orquestador\*\* | `8000` | — (`EXTRACTOR\_SERVICE\_URL`, `PERSISTENCE\_SERVICE\_URL`) | API Gateway / BFF stateless: valida PDF, calcula SHA-256, coordina flujo y ciclo de vida. |

| \*\*Extractor\*\* | `8001` | `EXTRACTOR\_SERVICE\_URL` (ej. `http://extractor:8001`) | Extracción de texto plano y conteo de páginas a partir de bytes PDF. |

| \*\*Persistencia\*\* | `8002` | `PERSISTENCE\_SERVICE\_URL` (ej. `http://persistence:8002`) | Almacenamiento WORM en MongoDB, unicidad por checksum SHA-256 y consultas CRUD. |



\---



\## 2. Diagrama de Flujo



\### 2.1. Arquitectura y Conectividad de Red



```mermaid

flowchart LR

&#x20;   Cliente\["Frontend / Cliente REST"] -->|"HTTP/REST + X-Request-ID"| Traefik\["Traefik Reverse Proxy"]

&#x20;   Traefik -->|":8000"| Orq\["Orquestador (FastAPI)"]

&#x20;   Orq -->|"POST /api/v1/extract\\n(multipart/form-data, timeout 30s)"| Ext\["Extractor (:8001)"]

&#x20;   Orq -->|"GET/POST/DELETE /api/v1/documents\*\\n(JSON, timeout 5s)"| Per\["Persistencia (:8002)"]

&#x20;   Per --> Mongo\[("MongoDB")]

