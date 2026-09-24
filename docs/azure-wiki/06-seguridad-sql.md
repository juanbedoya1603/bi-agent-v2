# 06 - Seguridad SQL

La seguridad del executor combina validación de aplicación con permisos mínimos del entorno. La tool analítica debe ser de solo lectura.

## Superficie permitida

Solo se permiten estas vistas:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

La whitelist del guard y la creación controlada de vistas en DuckDB deben permanecer alineadas.

## Sentencias aceptadas

- Una sola sentencia.
- `SELECT`.
- `WITH ... SELECT`.
- Joins, subqueries, CTEs, agregaciones y window functions de lectura.

La sentencia se analiza como AST T-SQL con `sqlglot`; no se confía en coincidencias de texto.

## Bloqueos obligatorios

- DDL: `CREATE`, `ALTER`, `DROP`, `TRUNCATE`.
- DML: `INSERT`, `UPDATE`, `DELETE`, `MERGE`.
- `EXEC` y `EXECUTE`.
- `SELECT INTO`.
- `USE`, transacciones y referencias a otras bases o schemas.
- Linked servers.
- Cualquier tabla o view fuera de la whitelist.

## Límites

| Control | Valor |
| --- | --- |
| Intentos SQL por turno | Máximo 3 |
| Timeout de consulta | Configurable; 600 segundos por defecto |
| Filas devueltas a la aplicación | Máximo 200 |
| Agregaciones internas | No se limitan por el tope de filas |

La aplicación ejecuta la consulta y usa `fetchmany(MAX_RESULT_ROWS + 1)` para detectar truncamiento. El resultado se devuelve con columnas, filas, `row_count` y `truncated`.

## Errores y secretos

Los errores que vuelven al agente pueden ser útiles para corregir SQL, pero nunca deben incluir passwords, connection strings, secretos ni stack traces completos. Las credenciales permanecen en el backend y se cargan mediante variables de entorno.

## Defensa en profundidad

El usuario de las fuentes analíticas debe tener permisos de lectura solamente. La validación de la aplicación no sustituye los permisos mínimos de SQL Server, ADLS ni Docker.
