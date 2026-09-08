# 03 — Architecture

## Arquitectura objetivo

```text
Next.js
  -> FastAPI
  -> OpenAI Agents SDK
  -> BI Agent
  -> run_readonly_sql(sql)
  -> SQL guard
  -> SQL Server
  -> filas
  -> Agent
  -> respuesta + tabla
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
2. ejecutar con usuario read-only;
3. devolver columnas, filas y metadata;
4. devolver errores SQL de forma segura para que el agente pueda corregir la consulta.

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

MVP:

- usar Sessions del Agents SDK;
- preferir SQLite si se quiere persistencia simple;
- cada conversación tiene un `session_id` UUID;
- “Nuevo chat” crea otro session ID.

No construir App DB enterprise en la primera versión.

## Respuesta UI

Mostrar:

- respuesta natural;
- tabla si existe resultado tabular;
- filtros/período solo si son útiles;
- botón copiar;
- Excel puede agregarse después.

No mostrar SQL por defecto. Puede guardarse internamente para debugging.
