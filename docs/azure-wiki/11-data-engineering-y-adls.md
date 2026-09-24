# 11 - Data Engineering y ADLS

## Fuente analítica

El executor productivo usa DuckDB para leer Parquet remoto en ADLS Gen2. En cada ejecución crea únicamente estas vistas lógicas:

| Vista lógica | Ruta relativa |
| --- | --- |
| `dbo.VW_Stores` | `Stores/*.parquet` |
| `dbo.VW_Products` | `Products/*.parquet` |
| `dbo.VW_SalesLast13Months` | `Sales/**` |

La ruta final se forma con `ADLS_FILESYSTEM` + `ADLS_BASE_PATH` + la ruta relativa. Los valores reales de conexión permanecen fuera de la Wiki.

## Responsabilidad de Data Engineering

Data Engineering es responsable de:

- cargar todos los archivos Parquet requeridos;
- mantenerlos actualizados;
- preservar las rutas y los esquemas esperados;
- validar que todos los archivos de cada fuente sean compatibles;
- comprobar fechas, volúmenes y completitud del histórico;
- validar los resultados de las métricas BI sobre el histórico completo.

## Qué no hace la aplicación

La aplicación no ingiere datos, no programa refresh y no corrige Parquet. Lee lo que esté disponible en ADLS durante cada consulta. Si el executor detecta ausencia de archivos o drift de schema, la consulta debe fallar de forma explícita y el problema se escala a Data Engineering.

## Validación antes de promover

Antes del merge a `main`, comprobar:

1. presencia de `Stores/*.parquet`, `Products/*.parquet` y `Sales/**`;
2. compatibilidad de schema entre archivos de una misma fuente;
3. fecha mínima y máxima disponibles;
4. volúmenes esperados por período;
5. totales y métricas críticas contra la fuente de referencia;
6. casos de eval y smoke test sobre el histórico completo.

Hasta terminar esa validación, `migration/adls-gen2` continúa siendo la rama desplegada y no debe promoverse a `main`.
