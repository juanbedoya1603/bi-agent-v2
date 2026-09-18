# 08 — Implementation Plan

El proyecto debe construirse en pocas fases y con vertical slices.

## Estado actual de implementación

- El deployment productivo con Docker Compose está completado.
- La migración del executor analítico a DuckDB + Parquet en ADLS Gen2 está
  completada en la rama `migration/adls-gen2`.
- La rama `migration/adls-gen2` es la actualmente desplegada.
- Data Engineering es responsable de subir todos los archivos Parquet a ADLS
  Gen2 y mantenerlos actualizados.
- Sigue pendiente validar el histórico completo, incluyendo fechas, esquemas,
  volúmenes y resultados de métricas BI.
- No se debe hacer merge a `main` hasta completar esa validación.

## Fase 1 — Base funcional

Objetivo: una pregunta real llega al modelo, genera SQL, se valida, se ejecuta y vuelve una respuesta.

Entregar:

- monorepo `apps/api` + `apps/web`;
- FastAPI health;
- configuración `.env`;
- executor DuckDB sobre Parquet remoto en ADLS Gen2;
- `sqlglot` guard;
- tool `run_readonly_sql`;
- un `Agent` de Agents SDK;
- system prompt inicial;
- primer endpoint de chat (retirado en 4C al consolidar el flujo por conversación);
- tests del SQL guard.

Casos de aceptación:

- ventas Colgate Bogotá agosto 2026;
- top productos arroz por ventas;
- DML/DDL rechazado.

## Fase 2 — Calidad BI

Objetivo: cubrir las métricas que realmente usa el equipo.

Entregar:

- few-shot SQL examples;
- share;
- DN;
- penetración;
- rotación;
- MoM;
- resolución natural de productos;
- ambigüedades;
- “por qué” con factores observables;
- 20–30 evals con modelo real.

No crear nuevas tools por KPI salvo necesidad demostrada.

## Fase 3 — Chat usable

Objetivo: que BI pueda usarlo a diario.

Entregar:

- UI de chat;
- Sessions del Agents SDK;
- nuevo chat;
- contexto multi-turn;
- tabla de resultados;
- copiar respuesta/tabla;
- manejo amigable de errores;
- logs internos de SQL y duración.

La implementación actual usa `SQLiteSession` persistente para conservar el
contexto multi-turn.

## Fase 4 — Extras después de validar valor

### Fase 4A — Completada

- App DB SQL Server independiente;
- historial, búsqueda, renombrado y eliminación de conversaciones;
- auditoría de turnos e intentos SQL;
- exportación de las filas visibles a Excel;
- rollback coordinado del turno actual entre App DB y Session SQLite.

### Fase 4B — Completada

- autenticación local con Argon2id y cookie HttpOnly;
- sesiones revocables, cambio/reset de contraseña y lockout;
- administración básica de usuarios;
- ownership funcional y aislamiento por `user_id`.

### Fase 4C — Completada

- usage real de cada `Runner.run` tomado de `result.context_wrapper.usage`;
- duración, modelo, requests y tokens persistidos por respuesta;
- costo `Decimal` para modelos con precio registrado;
- relación uno-a-uno desde audit hacia `assistant_message_id`;
- metadata opcional en el historial y desplegable accesible por respuesta;
- logout real desde “Volver al login”;
- eliminación de `POST /api/v1/chat`; el único flujo oficial es
  `POST /api/v1/conversations/{conversation_id}/messages`.

Pendiente para fases posteriores: validación del histórico completo por Data
Engineering, Entra ID, dashboards/gráficas agregadas, presupuestos, billing y
migración de Sessions fuera de SQLite.

## Definition of Done del MVP

- puede responder tickets reales;
- no puede escribir en las fuentes analíticas ni en ADLS; la App DB sí recibe el
  estado de aplicación necesario para usuarios, conversaciones y auditoría;
- solo consulta tres views;
- conserva conversación básica;
- los evals críticos son satisfactorios;
- BI lo prueba y confirma que ahorra tiempo.
