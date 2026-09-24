# 10 - Testing y evals

## Validación local

Desde la raíz del repositorio:

```powershell
python -m pytest
python -m ruff check .
git diff --check
```

Para frontend:

```powershell
Set-Location apps/web
npm run lint
npm run build
```

## Tests deterministas

El backend debe cubrir:

- aceptación de `SELECT`, CTE + `SELECT`, joins, agregaciones y subqueries entre las tres vistas;
- rechazo de DML/DDL, `EXEC`, `SELECT INTO`, múltiples sentencias, otras bases, tablas no permitidas y linked servers;
- columnas, filas, truncamiento a 200 filas y timeout;
- errores SQL sin secretos;
- máximo de 3 intentos por turno;
- tool calls, tool output, reintentos y respuesta final con `agents.testing.ScriptedModel`;
- autenticación, persistencia, ownership, auditoría, sesiones y App DB.

## Evals BI

Los casos versionados deben cubrir como mínimo:

1. ventas por marca, ciudad y mes;
2. unidades, tickets, precio medio y ticket promedio;
3. top productos;
4. aclaración de ranking y de mes sin año;
5. búsqueda por EAN y SKU ambiguo;
6. share de categoría y share contra competidores;
7. misma presentación para todas las marcas comparadas;
8. DN, penetración, rotación y MoM;
9. follow-ups como “Ahora Medellín” y “¿Y por unidades?”;
10. preguntas “por qué” con indicadores observables y sin causalidad externa.

Cada fallo debe conservar prompt, SQL generado, resultado SQL, respuesta final y motivo. El ciclo esperado es: caso falla -> entender causa -> mejorar prompt o ejemplo -> agregar regresión -> volver a ejecutar.

## Pruebas live

Los smoke tests y evals con modelo real requieren opt-in explícito mediante las variables documentadas en el repositorio. Pueden consumir tokens y consultar ADLS; no deben ejecutarse accidentalmente en CI.

## Gate de promoción

No promover `migration/adls-gen2` a `main` hasta que Data Engineering valide el histórico completo y los resultados BI críticos sobre las fechas, esquemas y volúmenes cargados.
