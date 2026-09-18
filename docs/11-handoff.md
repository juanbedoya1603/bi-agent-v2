# 11 — Handoff técnico

## Objetivo

BI Agent es un asistente interno de BI. Recibe preguntas en lenguaje natural,
genera consultas T-SQL de solo lectura, las valida y usa los datos disponibles
para devolver una respuesta de negocio con tabla cuando corresponde.

## Estado actual

- El MVP funcional está desplegado con Docker Compose.
- La rama actualmente desplegada es `migration/adls-gen2`.
- Hay tres servicios: `backend`, `frontend` y `gateway`.
- Hay autenticación local, administración de usuarios, conversaciones,
  auditoría de turnos e intentos SQL, telemetría de uso y exportación a Excel.
- El executor analítico actual transpila el T-SQL validado a DuckDB y lee
  Parquet desde ADLS.

## Rama y regla de promoción

No se debe hacer merge a `main` todavía. `migration/adls-gen2` es la rama
actualmente desplegada. El merge a `main` debe hacerse después de que Data
Engineering haya cargado el histórico completo en ADLS y se haya validado el
resultado completo de las consultas BI sobre ese histórico.

## Arquitectura y URL

```text
Caddy principal de taxonomy-organizer
  -> gateway BI
  -> Next.js / FastAPI

FastAPI
  -> OpenAI
  -> App DB SQL Server
  -> DuckDB
       -> ADLS Gen2 / Parquet
```

URL productiva: <https://bi-agent.132-196-100-163.sslip.io>

El Caddy principal de `taxonomy-organizer` termina HTTPS y hace proxy al
gateway de BI. El gateway enruta `/api/*` y `/health` a FastAPI y el resto al
frontend. La red externa Compose `onoff-taxonomy-organizer_default` y el alias
`bi-agent-gateway` son parte de esa integración.

## Fuentes de datos

DuckDB crea las tres views autorizadas a partir de Parquet en ADLS, bajo
`ADLS_FILESYSTEM` y `ADLS_BASE_PATH`:

- `Stores/*.parquet` → `dbo.VW_Stores`.
- `Products/*.parquet` → `dbo.VW_Products`.
- `Sales/**` → `dbo.VW_SalesLast13Months`.

La App DB SQL Server es independiente y almacena usuarios, sesiones web,
conversaciones, mensajes, auditoría y uso. No es la fuente de las métricas BI.

## Métricas disponibles

Las métricas definidas por el prompt y el modelo actual son:

- ventas;
- unidades;
- tickets;
- precio medio;
- ticket promedio;
- rotación;
- penetración;
- share de ventas y de unidades;
- DN;
- frecuencia;
- unidades por ticket;
- MoM.

La view de ventas se describe actualmente como cobertura aproximada de los
últimos 13 meses. La disponibilidad real depende de los Parquet cargados en
ADLS y debe comprobarse antes de afirmar cobertura histórica.

## Seguridad

- Solo se permiten `SELECT` o `WITH ... SELECT` en una única sentencia.
- El guard AST de `sqlglot` limita el acceso a
  `dbo.VW_SalesLast13Months`, `dbo.VW_Stores` y `dbo.VW_Products`.
- Se bloquean DDL, DML, `EXEC`, `SELECT INTO`, otras bases y linked servers.
- Hay un máximo de 3 intentos SQL por turno y 200 filas devueltas a la
  aplicación; las agregaciones internas no se limitan por ese tope.
- El timeout de consulta es configurable y su valor por defecto en el código es
  600 segundos.
- Las credenciales permanecen en el backend y se cargan por variables de
  entorno. El tracing del Agents SDK y la captura de datos sensibles están
  deshabilitados.
- Las sesiones web usan cookies `HttpOnly`; en producción la cookie es
  `Secure` y `SameSite=Lax`.
- Las contraseñas se almacenan con Argon2id, los tokens de sesión se guardan en
  la App DB como hash SHA-256 y las conversaciones/auditoría se aíslan por
  `user_id`.

La validación de aplicación no sustituye permisos mínimos en App DB, ADLS ni la
configuración segura del entorno.

## Administración de usuarios

El primer administrador se crea mediante `BOOTSTRAP_ADMIN_USERNAME`,
`BOOTSTRAP_ADMIN_PASSWORD` y `BOOTSTRAP_ADMIN_DISPLAY_NAME` cuando la tabla de
usuarios está vacía. Después, un administrador puede crear, editar, activar,
desactivar y resetear usuarios desde la interfaz de administración o sus rutas
API. Las contraseñas temporales requieren al menos 10 caracteres y deben
cambiarse en el primer acceso o después de un reset.

La administración distingue usuarios administradores, pero el repo no define
permisos analíticos diferentes por usuario: el acceso a las métricas es común
para los usuarios activos.

## Despliegue

La instalación productiva vive en `C:\Aplicaciones\bi-agent-v2`. Desde esa
ruta, el procedimiento operativo está en
[`docs/09-deployment.md`](09-deployment.md) y los comandos de operación en
[`docs/10-operations.md`](10-operations.md). El arranque habitual es:

```powershell
docker compose up -d --build
docker compose ps
```

Las migraciones de App DB son manuales y deben aplicarse en orden:

1. `apps/api/migrations/001_phase4a_app_db.sql`
2. `apps/api/migrations/002_phase4b_local_auth.sql`
3. `apps/api/migrations/003_phase4c_usage.sql`

El volumen nombrado `bi_agent_data` conserva
`/data/bi_agent_sessions.sqlite3`, usado por `SQLiteSession` para el contexto
multi-turn. El historial y la auditoría se almacenan aparte en la App DB.

## Dependencia con taxonomy-organizer

BI Agent no administra el Caddy principal ni el endpoint HTTPS público. Depende
de que `taxonomy-organizer` mantenga disponible su Caddy, la red externa
`onoff-taxonomy-organizer_default`, el hostname `sslip.io` y el proxy hacia
`bi-agent-gateway:80`. Un cambio de IP pública exige cambiar el hostname
`sslip.io` y la configuración de Caddy.

## Rol de Rich / Data Engineering

Rich / Data Engineering debe cargar y refrescar los Parquet de ADLS que consume
BI Agent, incluyendo ventas, tiendas y productos. Debe preservar las rutas y
los esquemas esperados por DuckDB y validar que todos los archivos de cada
fuente sean compatibles. También debe comprobar fechas, volumen y completitud
del histórico antes de declarar lista la migración.

La aplicación no contiene un proceso de ingesta ni un scheduler de refresh: lee
lo que esté disponible en ADLS durante cada consulta.

## Limitaciones actuales

- La cobertura documentada de ventas es aproximadamente de 13 meses hasta que
  Data Engineering valide el histórico completo cargado.
- Solo están disponibles las tres views autorizadas; no hay acceso analítico
  arbitrario ni escritura sobre los datos.
- Las explicaciones de "por qué" se limitan a factores observables en esas
  views; no prueban causalidad externa como campañas, clima o competencia.
- La autenticación es local. No hay SSO ni permisos analíticos diferenciados
  por usuario.
- `SQLiteSession` depende del volumen persistente de Docker; el repo no aporta
  un procedimiento automatizado de backup y restore para ese archivo.
- La disponibilidad pública depende de Caddy y de la red de
  `taxonomy-organizer`, que están fuera de este repo.

## Tareas futuras recomendadas

1. Cargar y validar el histórico completo en ADLS con Data Engineering; ejecutar
   las pruebas BI sobre fechas, totales y métricas críticas.
2. Documentar y probar backup/restore de la App DB y del volumen de sesiones.
3. Añadir monitoreo y alertas para los tres contenedores, ADLS, App DB, OpenAI
   y la ruta HTTPS de Taxonomy Organizer.
4. Revisar SSO, roles y permisos analíticos por usuario si el alcance deja de
   ser un equipo interno con acceso común.
5. Medir rendimiento y costo con el histórico completo antes de promover la
   rama a `main`.
