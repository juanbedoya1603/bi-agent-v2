# Despliegue Docker del BI Agent

El despliegue productivo usa la rama `migration/adls-gen2` y cuatro servicios
Docker Compose: `backend`, `frontend`, `gateway` y `cloudflared`.

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

Cloudflared crea un Quick Tunnel público sin dominio ni token persistente:

```powershell
docker compose logs -f cloudflared
```

El Quick Tunnel actual de `trycloudflare.com` es temporal: su URL puede cambiar
al reiniciar o recrear `cloudflared`, y no debe tratarse como una URL permanente.
Posteriormente se reemplazará por una URL permanente.

## Validación

```powershell
Invoke-WebRequest https://<url-trycloudflare>/health
```

Las llamadas del navegador al API son relativas (`/api/...`), por lo que
frontend y API permanecen same-origin bajo la URL pública.
