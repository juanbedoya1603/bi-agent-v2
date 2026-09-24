# 09 - Usuarios y seguridad

## Autenticación actual

El proyecto usa autenticación local. Las sesiones web se mantienen con cookies `HttpOnly`; en producción se usan `Secure` y `SameSite=Lax`. Las contraseñas se protegen con Argon2id y el token de sesión se guarda en App DB como hash SHA-256.

## Administración

Un administrador puede crear, editar, activar, desactivar y resetear usuarios desde la interfaz o las rutas administrativas. El primer administrador se crea solo cuando la tabla de usuarios está vacía, usando los nombres de variables:

```text
BOOTSTRAP_ADMIN_USERNAME
BOOTSTRAP_ADMIN_PASSWORD
BOOTSTRAP_ADMIN_DISPLAY_NAME
```

Después de un bootstrap o reset, la contraseña temporal debe cambiarse en el primer acceso. No documentar ni compartir los valores.

## Aislamiento

- Conversaciones, mensajes, ownership y auditoría se aíslan por `user_id`.
- Las rutas administrativas requieren usuario administrador.
- La App DB almacena estado de aplicación; no es la fuente de métricas.
- El repo no define permisos analíticos diferentes por usuario: los usuarios activos comparten el acceso a las métricas disponibles.

## Secretos que nunca se publican

No incluir en la Wiki, commits, logs, imágenes ni capturas:

- API keys;
- passwords;
- connection strings;
- PAT y tokens;
- contenido de `.env` o `.env.local`;
- credenciales de usuarios;
- valores reales de `APP_DB_*`, `AZURE_STORAGE_CONNECTION_STRING` u otras variables sensibles.

Solo se documentan nombres de variables y rutas sin valores.

## Responsabilidad operativa

La seguridad de la aplicación complementa los permisos mínimos del usuario de App DB, ADLS y cualquier red Docker. El usuario de las fuentes analíticas debe ser de lectura solamente; la aplicación no debe disponer de permisos de escritura sobre los datos analíticos.
