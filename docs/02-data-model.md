# 02 — Data Model

El agente solo conoce tres views.

## `dbo.VW_SalesLast13Months`

```text
idStore
idTicket
idProduct
year
month
day
tramo_horario
totalSaleValue
productQuantity
UnitValue
date
uniqueTicketPerStore
uniqueProductPerTicket
```

Notas:

- contiene aproximadamente los últimos 13 meses;
- `uniqueTicketPerStore` es el identificador oficial para tickets únicos;
- ventas = `totalSaleValue`;
- unidades = `productQuantity`.

## `dbo.VW_Stores`

```text
idPartner
economicActivity_fix
coordenadas
stateName
cityName
ZipCode
businessName
stratum
countryName
ImplementationDate
idDeal
```

Usar normalmente:

- `economicActivity_fix`: tipología/actividad del negocio;
- `stateName`;
- `cityName`;
- `stratum`;
- `countryName`;
- `ImplementationDate`.

Evitar usar coordenadas exactas salvo necesidad explícita.

## `dbo.VW_Products`

```text
productId
productName
barCode
manufacturerName
brandName
categoryName
subCategoryName
lineName
flavor
unitMeasure
netQuantityValue
```

Mapeo de negocio:

- manufacturerName = fabricante;
- brandName = marca;
- categoryName = categoría;
- subCategoryName = subcategoría;
- lineName = línea;
- flavor = sabor;
- unitMeasure = unidad, por ejemplo G/ML;
- netQuantityValue = cantidad neta.

## Joins oficiales

```sql
VW_SalesLast13Months.idStore = VW_Stores.idPartner
VW_SalesLast13Months.idProduct = VW_Products.productId
```

## Métricas oficiales

```text
Ventas = SUM(totalSaleValue)
Unidades = SUM(productQuantity)
Tickets = COUNT(DISTINCT uniqueTicketPerStore)
Precio medio = ventas / unidades
Ticket promedio = ventas / tickets
Rotación = unidades / tiendas distintas que venden la entidad
Penetración = tiendas que venden la entidad / tiendas activas en ventas bajo el mismo contexto
Share ventas = ventas entidad / ventas del universo comparado
Share unidades = unidades entidad / unidades del universo comparado
DN = tiendas que venden la entidad / tiendas que venden la categoría
Frecuencia = tickets / tiendas que venden la entidad
Unidades por ticket = unidades / tickets
MoM = valor mes actual / valor mes anterior - 1
```

## Fechas

Usar intervalos semiabiertos para evitar errores si `[date]` contiene hora:

```sql
s.[date] >= '2026-08-01'
AND s.[date] < '2026-09-01'
```
