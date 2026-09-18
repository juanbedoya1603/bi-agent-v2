# 03 — Architecture

## Arquitectura productiva actual

```text
Usuario
  -> Next.js
  -> FastAPI
  -> OpenAI Agents SDK
  -> BI Agent
  -> run_readonly_sql(sql)
  -> SQL Guard sobre T-SQL
  -> sqlglot: T-SQL -> DuckDB SQL
  -> DuckDB
  -> views lógicas dbo.*
  -> Parquet remoto en ADLS Gen2
  -> resultados
  -> Agent
  -> respuesta + tabla
```

FastAPI mantiene dos dependencias de persistencia separadas:

- **App DB:** SQL Server independiente, conectado mediante SQLAlchemy/pyodbc,
  para usuarios, sesiones web, conversaciones, mensajes, auditoría y uso.
- **SQLiteSession:** archivo SQLite persistente para conservar el contexto
  multi-turn del Agents SDK por conversación.

La App DB no es una fuente de métricas y el agente no puede consultarla.
DuckDB solo crea las tres views lógicas autorizadas desde ADLS:

```text
dbo.VW_SalesLast13Months
dbo.VW_Stores
dbo.VW_Products
```

## Un solo agente

No usar multi-agent ni handoffs en el MVP.

El agente tiene un system prompt fuerte con:

- schema;
- joins;
- definiciones BI;
- reglas temporales;
- comportamiento ante ambigüedad;
- ejemplos SQL.

## Tool principal

```text
run_readonly_sql(sql: string)
```

Responsabilidades:

1. validar SQL;
2. transpilar el T-SQL validado a DuckDB SQL con `sqlglot`;
3. ejecutar en DuckDB sobre las views lógicas creadas desde ADLS;
4. devolver columnas, filas y metadata;
5. devolver errores SQL de forma segura para que el agente pueda corregir la consulta.

Respuesta conceptual:

```json
{
  "ok": true,
  "columns": ["brand", "sales"],
  "rows": [],
  "row_count": 10,
  "truncated": false
}
```

Error conceptual:

```json
{
  "ok": false,
  "error": {
    "type": "sql_error",
    "message": "Invalid column name ..."
  }
}
```

## Intentos

Máximo 3 ejecuciones SQL por turno.

El Agents SDK gestiona el loop del modelo. La aplicación solo controla el límite de llamadas a `run_readonly_sql`.

## Sesiones

- `SQLiteSession` del Agents SDK conserva el contexto multi-turn.
- Cada conversación tiene su propio identificador de sesión.
- El archivo SQLite se persiste en el volumen Docker de producción.
- “Nuevo chat” crea otra conversación y otro contexto de sesión.

El historial visible, el ownership, la auditoría y la telemetría se guardan en
la App DB SQL Server independiente. La sesión SQLite y la App DB se coordinan
durante el turno; perder el volumen SQLite elimina el contexto multi-turn, pero
no el historial persistido en App DB.

## Respuesta UI

Mostrar:

- respuesta natural;
- tabla si existe resultado tabular;
- filtros/período solo si son útiles;
- botón copiar;
- Excel puede agregarse después.

No mostrar SQL por defecto. Puede guardarse internamente para debugging.
