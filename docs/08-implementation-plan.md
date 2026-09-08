# 08 — Implementation Plan

El proyecto debe construirse en pocas fases y con vertical slices.

## Fase 1 — Base funcional

Objetivo: una pregunta real llega al modelo, genera SQL, se valida, se ejecuta y vuelve una respuesta.

Entregar:

- monorepo `apps/api` + `apps/web`;
- FastAPI health;
- configuración `.env`;
- conexión SQL Server read-only;
- `sqlglot` guard;
- tool `run_readonly_sql`;
- un `Agent` de Agents SDK;
- system prompt inicial;
- endpoint `POST /api/v1/chat`;
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

MVP puede usar SQLite para sesiones.

## Fase 4 — Extras después de validar valor

Solo si el equipo ya lo está usando:

- exportar Excel;
- historial/listado de chats más completo;
- Entra ID;
- App DB SQL Server;
- métricas de uso/costos;
- deployment endurecido;
- más controles por usuario.

## Definition of Done del MVP

- puede responder tickets reales;
- no puede escribir en SQL Server;
- solo consulta tres views;
- conserva conversación básica;
- los evals críticos son satisfactorios;
- BI lo prueba y confirma que ahorra tiempo.
