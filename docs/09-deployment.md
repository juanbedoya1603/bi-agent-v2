# Despliegue Docker del BI Agent

El despliegue productivo usa la rama `migration/adls-gen2` y tres servicios
Docker Compose: `backend`, `frontend` y `gateway`.

La URL productiva es:

```text
https://bi-agent.132-196-100-163.sslip.io
```

## Arquitectura actual

El Caddy principal de Taxonomy Organizer termina HTTPS y publica la URL
productiva. Su regla para `bi-agent.132-196-100-163.sslip.io` hace proxy a
`bi-agent-gateway:80`.

El servicio `gateway` de BI Agent pertenece a la red Compose local y tambien a
la red externa `onoff-taxonomy-organizer_default`, con el alias
`bi-agent-gateway`. Esa red debe existir antes de iniciar BI Agent y la crea
el despliegue de Taxonomy Organizer.

Dentro del gateway de BI Agent:

- `/api/*` y `/health` se enrutan al backend.
- El resto de las rutas se enruta al frontend.
- Backend y frontend no publican puertos en el host.

No se usa `cloudflared` ni Quick Tunnel en el despliegue productivo actual.

## Configuración

Crear un archivo `.env` local a partir de `.env.example`. El archivo `.env`
contiene secretos y no debe entrar en Git ni en las imágenes Docker. Debe
proporcionar las variables de OpenAI, App DB, almacenamiento ADLS y, si se
usa el bootstrap inicial, las credenciales del administrador.

El backend usa:

- `APP_ENV=production`.
- `SESSION_DB_PATH=/data/bi_agent_sessions.sqlite3`.
- `ADLS_FILESYSTEM` y `ADLS_BASE_PATH` para las rutas Parquet.
- DuckDB con `azure_transport_option_type='curl'` para leer ADLS.

## Arranque

Desde la raíz del repositorio:

```powershell
docker compose up -d --build
docker compose ps
```

El backend y el frontend no publican puertos en el host. Caddy solo enruta
internamente `/api/*` y `/health` al backend, y el resto al frontend.

## Validación

```powershell
Invoke-WebRequest https://bi-agent.132-196-100-163.sslip.io/health
```

La respuesta esperada es HTTP 200 con `{"status":"ok"}`. Las llamadas del
navegador al API son relativas (`/api/...`), por lo que frontend y API
permanecen same-origin bajo la URL pública.
