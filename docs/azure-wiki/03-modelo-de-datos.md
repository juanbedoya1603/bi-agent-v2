# 03 - Modelo de datos

El agente solo puede consultar estas vistas lógicas:

| Vista | Fuente ADLS | Propósito |
| --- | --- | --- |
| `dbo.VW_SalesLast13Months` | `Sales/**` | Hechos de venta; cobertura documentada aproximada de los últimos 13 meses. |
| `dbo.VW_Stores` | `Stores/*.parquet` | Dimensión de tiendas y contexto geográfico/comercial. |
| `dbo.VW_Products` | `Products/*.parquet` | Catálogo y atributos de producto. |

## `dbo.VW_SalesLast13Months`

Campos principales: `idStore`, `idTicket`, `idProduct`, `year`, `month`, `day`, `tramo_horario`, `totalSaleValue`, `productQuantity`, `UnitValue`, `date`, `uniqueTicketPerStore`, `uniqueProductPerTicket`.

- Ventas: `SUM(totalSaleValue)`.
- Unidades: `SUM(productQuantity)`.
- Tickets: `COUNT(DISTINCT uniqueTicketPerStore)`.
- `uniqueTicketPerStore` es el identificador oficial para tickets únicos.

## `dbo.VW_Stores`

Campos principales: `idPartner`, `economicActivity_fix`, `coordenadas`, `stateName`, `cityName`, `ZipCode`, `businessName`, `stratum`, `countryName`, `ImplementationDate`, `idDeal`, `macrozone`.

La jerarquía geográfica es `countryName -> stateName -> cityName -> macrozone`. `macrozone` se usa únicamente desde `st.macrozone`: no se infiere desde coordenadas, código postal o heurísticas. Un `NULL` significa “Sin macrozona”, no una macrozona real.

## `dbo.VW_Products`

Campos principales: `productId`, `productName`, `barCode`, `manufacturerName`, `brandName`, `categoryName`, `subCategoryName`, `lineName`, `flavor`, `unitMeasure`, `netQuantityValue`.

| Campo | Significado |
| --- | --- |
| `manufacturerName` | Fabricante |
| `brandName` | Marca |
| `categoryName` | Categoría |
| `subCategoryName` | Subcategoría |
| `lineName` | Línea |
| `flavor` | Sabor |
| `unitMeasure` | Unidad, por ejemplo `G` o `ML` |
| `netQuantityValue` | Cantidad neta |

## Joins oficiales

```sql
dbo.VW_SalesLast13Months.idStore = dbo.VW_Stores.idPartner
dbo.VW_SalesLast13Months.idProduct = dbo.VW_Products.productId
```

## Fechas

Usar intervalos semiabiertos para evitar errores si `date` contiene hora:

```sql
s.[date] >= '2026-08-01'
AND s.[date] < '2026-09-01'
```

Si se solicita un período potencialmente fuera de la cobertura disponible, comprobar primero `MIN([date])` y `MAX([date])` sin inventar disponibilidad.
