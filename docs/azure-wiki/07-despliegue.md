# 07 - Despliegue

## Estado productivo

- Rama desplegada: `migration/adls-gen2`.
- Ruta en VM: `C:\Aplicaciones\bi-agent-v2`.
- URL: [https://bi-agent.132-196-100-163.sslip.io](https://bi-agent.132-196-100-163.sslip.io).
- Health: [https://bi-agent.132-196-100-163.sslip.io/health](https://bi-agent.132-196-100-163.sslip.io/health).

El deployment productivo y la migración DuckDB + ADLS Gen2 están completados. Sigue pendiente la validación del histórico completo por Data Engineering.

## Servicios Docker Compose

| Servicio | Función |
| --- | --- |
| `backend` | FastAPI, agente, guard SQL, DuckDB, ADLS, App DB y sesiones. |
| `frontend` | Next.js y la interfaz de chat. |
| `gateway` | Caddy local que enruta backend y frontend. |

Backend y frontend no publican puertos en el host. El gateway necesita la red externa `onoff-taxonomy-organizer_default` y el alias `bi-agent-gateway`, creados como parte del despliegue de Taxonomy Organizer.

## Arranque y actualización

Ejecutar desde `C:\Aplicaciones\bi-agent-v2`:

```powershell
docker compose up -d
docker compose up -d --build
docker compose ps
```

La configuración sensible se carga desde `.env`, que no debe entrar en Git, imágenes Docker ni documentación. Documentar solo nombres de variables cuando sea necesario.

## Ruteo

El Caddy principal de Taxonomy Organizer termina HTTPS y hace proxy a `bi-agent-gateway:80`. El gateway local enruta:

- `/api/*` -> `backend:8000`;
- `/health` -> `backend:8000`;
- demás rutas -> `frontend:3000`.

No se usa `cloudflared` ni Quick Tunnel.

## Validación posterior

```powershell
docker compose ps
Invoke-WebRequest https://bi-agent.132-196-100-163.sslip.io/health
```

Se espera HTTP 200 con `{"status":"ok"}`. Un HTTP 503 con `{"status":"degraded"}` indica un problema de App DB; este endpoint no valida por sí solo OpenAI ni ADLS.

Las migraciones de App DB son manuales y deben aplicarse en orden:

1. `apps/api/migrations/001_phase4a_app_db.sql`
2. `apps/api/migrations/002_phase4b_local_auth.sql`
3. `apps/api/migrations/003_phase4c_usage.sql`
