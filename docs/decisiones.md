# Registro de Decisiones de Arquitectura (ADR) - Orquestador

## ADR-001: Mecanismo de resolución y descubrimiento de microservicios

- **Estado:** Aceptado (Alineado con el usuario)
- **Fecha:** 2026-10-19
- **Contexto:**
  Existía un conflicto entre la mención de HashiCorp Consul en `microservicios.txt` y la especificación de URLs por variables de entorno. Traefik ya actúa como proxy inverso y balanceador de carga.
- **Alternativas consideradas:**
  1. *HashiCorp Consul:* Servicio centralizado de descubrimiento dinámico. Descartado por añadir sobrecarga operacional excesiva, complejidad innecesaria y latencia de resolución para un despliegue de 4 contenedores.
  2. *URLs directas por variables de entorno con DNS de Docker / Traefik:* El orquestador recibe `EXTRACTOR_SERVICE_URL` y `PERSISTENCE_SERVICE_URL`.
- **Decisión:**
  Se adopta la **Opción 2** (URLs directas por variables de entorno). Traefik y la red de Docker Compose gestionan el balanceo y la resolución interna.
- **Consecuencias:**
  - *Positivas:* Arquitectura simple, determinista, sin dependencias externas pesadas, compatible con `microservicios.txt` y el alcance acordado.
  - *Negativas:* Si las instancias cambian dinámicamente fuera de Docker/Traefik, requeriría actualización de configuración.

---

## ADR-002: Delimitación de responsabilidades en Checksum y Duplicados

- **Estado:** Aceptado
- **Fecha:** 2026-10-19
- **Contexto:**
  El monolito calculaba el checksum en el extractor y chequeaba duplicados a través del repositorio de persistencia.
- **Alternativas consideradas:**
  1. *Dejar todo al extractor:* El orquestador envía el PDF crudo al extractor; el extractor calcula checksum y extrae texto; luego el orquestador intenta guardar en persistencia. Si es duplicado, se desperdiciaron CPU y RAM de extracción.
  2. *Cálculo temprano en orquestador + verificación con persistencia (Fail-Fast):* El orquestador calcula el hash SHA-256 de los bytes del PDF en memoria (~1 ms para 10 MB) y consulta a persistencia (`GET /documents/checksum/{checksum}`). Si ya existe, responde 409 Conflict de inmediato sin invocar al extractor.
- **Decisión:**
  Se adopta la **Opción 2**:
  - Orquestador: calcula SHA-256 en memoria y coordina el flujo.
  - Persistencia: expone consulta de existencia por checksum y asegura unicidad estricta en MongoDB (índice único).
  - Extractor: solo procesa PDFs que ya han sido validados como únicos.
- **Consecuencias:**
  - *Positivas:* Ahorro drástico de recursos de CPU y red en archivos duplicados.
  - *Negativas:* Una llamada HTTP adicional a persistencia en archivos válidos (mitigada por la baja latencia de red interna).

---

## ADR-003: Unificación de Configuración en `app/core/config.py`

- **Estado:** Aceptado
- **Fecha:** 2026-10-19
- **Contexto:**
  El monolito tenía dos módulos de configuración solapados: `Settings` en `app/config/settings.py` y el protocolo `ConfigService` en `app/application/config_service.py`, usados de forma inconsistente.
- **Decisión:**
  Unificar en `app/core/config.py` con una clase `Settings` basada en `pydantic-settings` (usando `SettingsConfigDict` de Pydantic V2). Descartar `ConfigService` en el orquestador.
- **Consecuencias:**
  - *Positivas:* Código limpio, idiomático en FastAPI, testing desacoplado mediante `app.dependency_overrides[get_settings]`.
  - *Negativas:* Ninguna.

---

## ADR-004: Retiro del endpoint legacy `POST /api/v1/documents/` (PlainTextResponse)

- **Estado:** Aceptado
- **Fecha:** 2026-10-19
- **Contexto:**
  El monolito exponía `POST /api/v1/documents/` devolviendo un archivo `.txt` descargable (`PlainTextResponse`), con comentarios que afirmaban falsamente que `frontend/index.html` lo consumía. La inspección del código real del frontend demostró que consume `POST /api/v1/documents/upload` esperando JSON. Además, `microservicios.txt` exige estrictamente *"comunicación por JSON mediante HTTP REST"*.
- **Alternativas consideradas:**
  1. *Mantener `POST /api/v1/documents/` en el orquestador:* Contradice el estándar JSON de microservicios y mantiene código muerto que ningún cliente consume.
  2. *Retirar `POST /api/v1/documents/` y canalizar toda subida por `POST /api/v1/documents/upload`:* Mantiene la uniformidad JSON y preserva el contrato real con el frontend.
- **Decisión:**
  Se adopta la **Opción 2**. El endpoint legacy de texto plano queda descartado en la migración a microservicios.
- **Consecuencias:**
  - *Positivas:* 100% de comunicación JSON uniforme en el orquestador, eliminación de código muerto.
  - *Negativas:* Clientes hipotéticos de terceros (no presentes en el repositorio) que dependan de `.txt` requerirían actualizar su URL a `/upload` y leer JSON.

