# 08 - Operación y troubleshooting

## Comandos básicos

Ejecutar desde `C:\Aplicaciones\bi-agent-v2`:

```powershell
docker compose ps
docker compose logs
docker compose up -d
docker compose up -d --build
docker compose restart backend
```

Para acotar logs, usar el nombre del servicio, por ejemplo `docker compose logs backend`.

## Comprobación rápida

1. Abrir la URL productiva y confirmar que carga el frontend.
2. Ejecutar `GET /health` y comprobar el estado de App DB.
3. Iniciar sesión con un usuario existente.
4. Crear una conversación.
5. Ejecutar una pregunta BI que devuelva datos reales y verificar respuesta y tabla.

## Dónde mirar

| Área | Revisar |
| --- | --- |
| Frontend | URL pública, `docker compose logs frontend`, carga de assets y build del contenedor. |
| Backend | `docker compose logs backend`, `/health`, App DB, OpenAI, `SQLiteSession` y errores de la tool. |
| OpenAI | Disponibilidad de API, modelo, timeout, reintentos y nombres de variables de entorno; nunca registrar la API key. |
| App DB | Host, base, usuario, migraciones `001`-`003`, tabla de usuarios y estado observado por `/health`. |
| ADLS | `Stores/*.parquet`, `Products/*.parquet`, `Sales/**`, esquemas compatibles, fechas y volúmenes. |
| Caddy | Caddy principal de Taxonomy Organizer, hostname, regla de proxy, red externa y alias `bi-agent-gateway`. |
| Red Docker | Existencia de `onoff-taxonomy-organizer_default`, conexión del gateway a backend/frontend y resolución del alias. |

## Diagnóstico por síntoma

### La URL no carga

Revisar `docker compose ps`, logs de `gateway` y la disponibilidad del Caddy principal y de la red externa. Que los contenedores estén activos no garantiza que el HTTPS público esté disponible.

### `/health` devuelve 503

Revisar conectividad de App DB, variables `APP_DB_*`, migraciones y credenciales del usuario de lectura/escritura de aplicación. El endpoint no prueba OpenAI ni ADLS.

### La aplicación carga pero una pregunta falla

Revisar logs de `backend`, el modelo configurado, la disponibilidad de OpenAI y si el error es de SQL, schema o cobertura de ADLS. El agente puede corregir y reintentar como máximo tres veces.

### No hay datos o el schema no coincide

Escalar a Data Engineering. Validar que estén cargados todos los Parquet esperados, que mantengan el mismo esquema y que la ventana temporal solicitada exista.

### Se perdió el contexto multi-turn

Revisar el volumen `bi_agent_data` y `SESSION_DB_PATH`. La pérdida de `SQLiteSession` afecta el contexto del agente, pero no elimina el historial persistido en App DB.

## Dependencia externa

BI Agent no administra el Caddy principal. Un cambio de IP pública requiere actualizar el hostname `sslip.io` y la regla correspondiente del Caddy de Taxonomy Organizer.
