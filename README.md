# BI Agent — Simple Architecture

Este paquete define un nuevo proyecto desde cero para un asistente interno de BI.

La meta no es construir una plataforma analítica genérica. La meta es ahorrar tiempo al equipo de BI permitiendo que 5 usuarios internos hagan preguntas en lenguaje natural sobre tres views SQL Server ya preparadas.

## Idea central

```text
Usuario
  -> OpenAI Agents SDK
  -> system prompt con schema + reglas BI
  -> tool run_readonly_sql(sql)
  -> validador SQL read-only
  -> SQL Server
  -> resultado
  -> mismo agente interpreta
  -> respuesta al usuario
```

El modelo puede escribir SQL. La seguridad real está en:

- usuario SQL de solo lectura;
- whitelist de tres views;
- validación AST del SQL;
- una sola sentencia SELECT/CTE;
- timeout;
- máximo de filas retornadas.

## Fases 4A, 4B y 4C implementadas

La API vive en `apps/api` y requiere Python 3.11. El chat usable vive en `apps/web`.
El historial visible y la auditoría usan una App DB SQL Server independiente; las
Sessions SQLite del Agents SDK siguen manteniendo el contexto multi-turn.
La autenticación local aísla conversaciones y auditoría por usuario. Cada respuesta
del agente persiste además la duración, el modelo, el uso real reportado por Agents SDK
y el costo estimado cuando el modelo tiene un precio registrado.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn bi_agent_api.main:app --reload
```

Endpoints:

- `GET /health`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/change-password`
- `POST /api/v1/conversations`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations?search=texto`
- `PATCH /api/v1/conversations/{conversation_id}`
- `DELETE /api/v1/conversations/{conversation_id}`
- `GET /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/conversations/{conversation_id}/messages`
- `POST /api/v1/exports/excel`

La respuesta contiene el texto final del agente y, cuando la última ejecución fue
exitosa, `data` con columnas, filas, conteo y bandera de truncamiento.
Los mensajes assistant incluyen `metadata` opcional con duración, modelo, requests,
tokens de entrada/caché/salida/razonamiento/totales y costo. Los mensajes históricos
sin telemetría y los mensajes user devuelven `metadata: null`.

Para iniciar el frontend:

```powershell
Set-Location apps/web
Copy-Item .env.local.example .env.local
npm install
npm run dev
```

## Seguridad de SQL Server

Las credenciales `ANALYTICS_DB_*` deben corresponder a una identidad dedicada que
tenga `SELECT` únicamente sobre:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

No se debe asignar a esa identidad ningún rol de escritura o DDL. La conexión marca
`ApplicationIntent=ReadOnly`; esto complementa, pero no reemplaza, los permisos
reales de SQL Server ni el guard AST de la aplicación.

## App DB

Configura `APP_DB_HOST`, `APP_DB_PORT`, `APP_DB_NAME`, `APP_DB_USER`,
`APP_DB_PASSWORD` y `APP_DB_DRIVER` con una identidad SQL de lectura/escritura que no
se reutilice para la base analítica. El esquema reproducible está en
`apps/api/migrations/001_phase4a_app_db.sql`. La aplicación usa siempre el schema fijo
`biAgent`, sin depender del schema predeterminado del usuario SQL. Las migraciones se
aplican manualmente, en orden:

- `001_phase4a_app_db.sql`: conversaciones, mensajes y auditoría;
- `002_phase4b_local_auth.sql`: usuarios, sesiones y ownership;
- `003_phase4c_usage.sql`: vínculo audit/message y telemetría de uso/costo.

Las tablas principales son:

- `biAgent.app_conversations`;
- `biAgent.app_messages`;
- `biAgent.app_audit_turns`;
- `biAgent.app_audit_sql_attempts`.

La auditoría guarda tiempos, intentos y resultados SQL operativos. No guarda claves,
contraseñas, cadenas de conexión ni tokens. El endpoint de Excel recibe exclusivamente
las columnas y hasta 200 filas ya visibles, genera una sola hoja en memoria y no llama
al agente ni a la base analítica.

`app_conversations.user_id` y `app_audit_turns.user_id` permanecen nullable en el
esquema físico por compatibilidad; la aplicación exige ownership en todas las rutas.
El costo se calcula con `Decimal` para `gpt-5-mini`: input no cacheado a US$0.25/M,
input cacheado a US$0.025/M y output a US$2.00/M. Los tokens de razonamiento ya están
incluidos en output y no se cobran de nuevo. Modelos sin precio registrado conservan
su usage con `estimated_cost_usd = NULL`.

El tracing del Agents SDK está desactivado por cada ejecución y el `.env.example`
también desactiva tracing y logging de datos de modelo/tool.

## Verificación

```powershell
python -m pytest
python -m ruff check .
git diff --check
```

## Qué NO vamos a construir

- DSL analítico propio;
- `AnalyticalRequest`;
- `FilterPolicy`;
- `SqlCompiler`;
- `target/context` como contrato de software;
- motor propio de denominadores;
- `metric_reference` / grounding numérico complejo;
- multi-agent;
- LangChain/LangGraph;
- Entra ID para el MVP;
- migración de Sessions del SDK fuera de SQLite;

## Orden de lectura para Codex

1. `AGENTS.md`
2. `docs/01-product-goal.md`
3. `docs/02-data-model.md`
4. `docs/03-architecture.md`
5. `docs/04-sql-safety.md`
6. `docs/05-system-prompt.md`
7. `docs/06-sql-examples.md`
8. `docs/07-testing-evals.md`
9. `docs/08-implementation-plan.md`
10. `CODEX_START_PROMPT.md`
