# 12 - Handoff y pendientes

## Estado entregado

- MVP funcional desplegado con Docker Compose.
- Rama productiva: `migration/adls-gen2`.
- Migración del executor a DuckDB + Parquet en ADLS Gen2 completada.
- Servicios productivos: `backend`, `frontend` y `gateway`.
- Autenticación local, usuarios, conversaciones, auditoría, telemetría y exportación Excel implementadas.
- La URL pública depende del Caddy y la red de Taxonomy Organizer.

## Regla de promoción

No hacer merge a `main` todavía. Data Engineering debe validar primero el histórico completo cargado en ADLS, incluyendo fechas, esquemas, volúmenes y resultados de métricas. La aprobación de esa validación es el gate para promover la rama.

## Responsables de handoff

| Área | Responsabilidad |
| --- | --- |
| Data Engineering | Carga, actualización, schema, fechas, volúmenes y validación histórica de Parquet. |
| Backend/BI Agent | Prompt, guard SQL, executor, App DB, sesiones y corrección de regresiones. |
| Frontend | Chat, tablas, exportación y experiencia de usuario. |
| Operación | Docker Compose, VM, red externa, gateway, Caddy y health. |

## Pendientes conocidos

1. Validar y aprobar el histórico completo de ADLS.
2. Medir rendimiento y costo con el histórico completo.
3. Documentar y probar backup/restore de App DB y del volumen de sesiones.
4. Añadir monitoreo y alertas para contenedores, ADLS, App DB, OpenAI y HTTPS.
5. Evaluar SSO, roles y permisos analíticos diferenciados si cambia el alcance.
6. Evaluar migración de sesiones fuera de SQLite.

## Limitaciones actuales

- La cobertura documentada de ventas es aproximadamente de 13 meses hasta validar el histórico real.
- Solo están disponibles las tres vistas autorizadas.
- Las preguntas “por qué” solo pueden usar factores observables en esas vistas.
- La autenticación es local y no hay permisos analíticos diferenciados.
- La disponibilidad pública depende de infraestructura de Taxonomy Organizer fuera de este repositorio.

## Regla de mantenimiento

Actualizar esta Wiki cuando cambien la rama desplegada, el flujo de entrada, las tres vistas, las métricas oficiales, el procedimiento operativo o el gate de promoción. No copiar secretos ni contenido de archivos `.env`.
