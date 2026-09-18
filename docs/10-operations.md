# 10 — Operaciones

## Referencias de producción

- URL: <https://bi-agent.132-196-100-163.sslip.io>
- VM: `C:\Aplicaciones\bi-agent-v2`
- Rama desplegada: `migration/adls-gen2`

La arquitectura de entrada es:

```text
Caddy principal de Taxonomy Organizer
  -> gateway BI
  -> Next.js / FastAPI
```

FastAPI conecta con OpenAI, la App DB y DuckDB. DuckDB lee los Parquet de ADLS.
El gateway enruta `/api/*` y `/health` al backend y el resto al frontend.

## Servicios esperados

`docker compose ps` debe mostrar estos servicios/contenedores:

- `backend`
- `frontend`
- `gateway`

El gateway depende de la red externa `onoff-taxonomy-organizer_default`, creada
por el despliegue de Taxonomy Organizer.

## Comandos básicos

Ejecutar desde `C:\Aplicaciones\bi-agent-v2`:

```powershell
docker compose ps
docker compose logs
docker compose up -d
docker compose up -d --build
docker compose restart backend
```

## Comprobación rápida

1. Abrir la URL productiva y confirmar que carga el frontend.
2. Comprobar el estado de la API:

   ```powershell
   Invoke-WebRequest https://bi-agent.132-196-100-163.sslip.io/health
   ```

   La respuesta `200` con `{"status":"ok"}` confirma que la App DB está
   disponible. Un `503` con `{"status":"degraded"}` indica un problema de
   App DB; este endpoint no valida por sí solo OpenAI ni ADLS.

3. Iniciar sesión con un usuario existente. El primer acceso después de crear o
   resetear un usuario exige cambiar la contraseña temporal.
4. Crear una conversación y ejecutar una pregunta BI que devuelva datos reales.
   Confirmar la respuesta y, cuando aplique, la tabla de resultados.

## Persistencia

Compose monta el volumen nombrado `bi_agent_data` en `/data` del backend. Allí
se conserva el archivo configurado por `SESSION_DB_PATH`, que en producción es
`/data/bi_agent_sessions.sqlite3`. Este archivo contiene las sesiones de
`SQLiteSession` y el contexto multi-turn por conversación. Si se pierde el
volumen, se pierde ese contexto; la App DB conserva por separado usuarios,
conversaciones, mensajes y auditoría.

## Variables de entorno

Configurar en `.env` los nombres siguientes. Este documento no contiene valores:

```text
APP_ENV
LOG_LEVEL
OPENAI_API_KEY
OPENAI_MODEL
OPENAI_TIMEOUT_SECONDS
OPENAI_MAX_RETRIES
OPENAI_AGENTS_DISABLE_TRACING
OPENAI_AGENTS_DONT_LOG_MODEL_DATA
OPENAI_AGENTS_DONT_LOG_TOOL_DATA
MAX_SQL_ATTEMPTS_PER_TURN
APP_DB_HOST
APP_DB_PORT
APP_DB_NAME
APP_DB_USER
APP_DB_PASSWORD
APP_DB_DRIVER
AZURE_STORAGE_CONNECTION_STRING
ADLS_FILESYSTEM
ADLS_BASE_PATH
QUERY_TIMEOUT_SECONDS
MAX_RESULT_ROWS
SESSION_DB_PATH
WEB_ORIGIN
BOOTSTRAP_ADMIN_USERNAME
BOOTSTRAP_ADMIN_PASSWORD
BOOTSTRAP_ADMIN_DISPLAY_NAME
```

Las variables `BOOTSTRAP_ADMIN_*` solo se necesitan para crear el primer
administrador cuando la tabla de usuarios está vacía. No guardar `.env` en Git,
en imágenes Docker ni en documentación.

## Dónde mirar si falla

- **Frontend:** `docker compose logs`, carga de la URL pública y build del
  contenedor `frontend`.
- **Backend:** `docker compose logs`, `/health`, configuración de App DB,
  OpenAI y sesiones.
- **ADLS:** `AZURE_STORAGE_CONNECTION_STRING`, `ADLS_FILESYSTEM`,
  `ADLS_BASE_PATH`, existencia de `Stores/*.parquet`, `Products/*.parquet` y
  `Sales/**`, además de consistencia de esquema entre archivos.
- **App DB:** conectividad, migraciones `001`, `002` y `003`, tabla de usuarios
  y disponibilidad observada por `/health`.
- **OpenAI:** `OPENAI_API_KEY`, modelo, timeout, límite de reintentos y
  disponibilidad de la API.
- **HTTPS/Caddy:** Caddy principal de Taxonomy Organizer, red externa,
  hostname público, alias `bi-agent-gateway` y el `gateway/Caddyfile` local.

## Dependencia de HTTPS

El HTTPS público no termina en el gateway de BI Agent. Entra mediante el Caddy
principal de Taxonomy Organizer, que publica el hostname y hace proxy hacia
`bi-agent-gateway:80`. Si Taxonomy Organizer, su red externa o su regla de
Caddy no están disponibles, BI Agent puede tener sus contenedores activos y aun
así no ser accesible públicamente.

Si cambia la IP pública de la VM, debe cambiar el hostname `sslip.io` y también
la configuración correspondiente del Caddy principal de Taxonomy Organizer.
