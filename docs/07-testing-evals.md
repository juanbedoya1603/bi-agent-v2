# 07 — Testing & Evals

El proyecto debe probar dos cosas diferentes:

1. seguridad/ejecución del backend;
2. calidad del razonamiento text-to-SQL del modelo.

## Tests deterministas

### SQL guard

Probar que acepta:

- SELECT simple;
- CTE + SELECT;
- joins entre las tres views;
- agregaciones y subqueries.

Probar que rechaza:

- INSERT/UPDATE/DELETE/MERGE;
- DROP/ALTER/CREATE/TRUNCATE;
- EXEC;
- SELECT INTO;
- dos sentencias;
- tablas no permitidas;
- otra base de datos;
- linked server.

### Tool

Probar:

- query válida devuelve columnas/filas;
- timeout controlado;
- truncamiento a 200 filas;
- error SQL vuelve al agente sin secretos;
- máximo 3 intentos por turno.

### Agent SDK

Usar `agents.testing.ScriptedModel` para validar:

- tool call;
- tool output;
- reintento tras error;
- respuesta final;
- multi-turn básico.

## Evals con modelo real

Mantener un dataset pequeño, inicialmente 20–30 preguntas reales.

Casos mínimos:

1. ventas marca/ciudad/mes;
2. unidades;
3. tickets;
4. precio medio;
5. ticket promedio;
6. top productos;
7. ranking ambiguo -> aclaración;
8. mes sin año -> aclaración;
9. producto por EAN;
10. producto ambiguo -> aclaración;
11. share dentro de categoría;
12. share contra competidores explícitos;
13. misma presentación 500 g para todos los competidores;
14. DN;
15. penetración;
16. rotación por ciudad;
17. MoM;
18. “Ahora Medellín” conserva resto del contexto;
19. “¿Y por unidades?” cambia la métrica;
20. “¿Por qué cayó?” usa varios indicadores y evita causalidad externa.

## Qué evaluar

No hace falta un evaluador sofisticado al inicio.

Para cada caso revisar:

- ¿preguntó aclaración cuando debía?;
- ¿consultó las views correctas?;
- ¿joins correctos?;
- ¿período correcto?;
- ¿filtros correctos?;
- ¿fórmula correcta?;
- ¿respuesta coincide con el resultado SQL?;

Guardar para cada fallo:

```text
prompt
SQL generado
resultado SQL
respuesta final
motivo del fallo
```

## Ciclo de mejora

```text
caso falla
-> entender por qué
-> mejorar system prompt o ejemplo
-> agregar test/eval de regresión
-> volver a ejecutar
```

No construir una nueva capa de software para un fallo que puede corregirse claramente con prompt/examples, salvo que el error sea recurrente y peligroso.
