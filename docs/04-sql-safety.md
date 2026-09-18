# 04 — SQL Safety

El proyecto es interno, pero una tool que ejecuta SQL necesita controles simples y fuertes.

## Ejecución analítica actual

El executor productivo no consulta un SQL Server/Fabric analítico. El flujo
actual recibe T-SQL, lo valida, lo transpila a DuckDB SQL con `sqlglot` y lo
ejecuta en DuckDB. DuckDB crea únicamente estas tres views lógicas desde
Parquet remoto en ADLS Gen2:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

La App DB SQL Server es independiente y se usa para autenticación, sesiones
web, conversaciones, auditoría y uso; la tool analítica no puede consultarla.

## Primera barrera: superficie de datos

La aplicación solo expone al modelo las tres views lógicas autorizadas:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

No confiar solo en el prompt: la whitelist del guard y la construcción controlada
de views en DuckDB deben mantenerse alineadas.

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

`MAX_RESULT_ROWS` limita lo que vuelve a la aplicación, no el número de filas que DuckDB puede agregar internamente.

Implementación actual: ejecutar normalmente y hacer `fetchmany(MAX_RESULT_ROWS + 1)` para detectar truncamiento.

Después de pasar el guard, `sqlglot` transpila la sentencia de T-SQL a DuckDB
SQL. La consulta resultante solo puede operar sobre las tres views lógicas
creadas por el executor a partir de ADLS.

## Errores

La tool puede devolver al agente errores SQL útiles, pero nunca:

- contraseña;
- connection string;
- stack trace completo;
- secretos.

## SQL generado

Guardar el SQL ejecutado en logs internos es útil para debugging y mejora del prompt. No mostrarlo al usuario final salvo que lo pida explícitamente.
