# 04 — SQL Safety

El proyecto es interno, pero una tool que ejecuta SQL necesita controles simples y fuertes.

## Primera barrera: permisos de base de datos

El usuario utilizado por la aplicación debe tener únicamente `SELECT` sobre:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

No confiar solo en el prompt.

## Segunda barrera: AST validator

Usar `sqlglot` con dialecto T-SQL.

Aceptar:

- una sola sentencia;
- `SELECT`;
- `WITH ... SELECT`;
- joins, subqueries, CTEs, agregaciones y window functions de lectura.

Rechazar:

- INSERT;
- UPDATE;
- DELETE;
- MERGE;
- DROP;
- ALTER;
- CREATE;
- TRUNCATE;
- EXEC / EXECUTE;
- SELECT INTO;
- USE;
- transacciones;
- linked servers;
- referencias a otras bases/schemas no permitidos;
- cualquier tabla/view fuera de la whitelist.

## Whitelist

Normalizar referencias y permitir únicamente:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

Permitir aliases.

## Límites

- `MAX_SQL_ATTEMPTS_PER_TURN=3`
- `QUERY_TIMEOUT_SECONDS=600`
- `MAX_RESULT_ROWS=200`

`MAX_RESULT_ROWS` limita lo que vuelve a la aplicación, no el número de filas que SQL Server puede agregar internamente.

Implementación recomendada: ejecutar normalmente y hacer `fetchmany(MAX_RESULT_ROWS + 1)` para detectar truncamiento.

## Errores

La tool puede devolver al agente errores SQL útiles, pero nunca:

- contraseña;
- connection string;
- stack trace completo;
- secretos.

## SQL generado

Guardar el SQL ejecutado en logs internos es útil para debugging y mejora del prompt. No mostrarlo al usuario final salvo que lo pida explícitamente.
