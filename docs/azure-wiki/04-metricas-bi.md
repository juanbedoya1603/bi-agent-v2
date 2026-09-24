# 04 - Métricas BI

Estas son las definiciones oficiales usadas por el system prompt y por los ejemplos SQL del proyecto.

| Métrica | Definición |
| --- | --- |
| Ventas | `SUM(totalSaleValue)` |
| Unidades | `SUM(productQuantity)` |
| Tickets | `COUNT(DISTINCT uniqueTicketPerStore)` |
| Precio medio | Ventas / unidades |
| Ticket promedio | Ventas / tickets |
| Rotación | Unidades / tiendas distintas que venden la entidad |
| Penetración | Tiendas que venden la entidad / tiendas activas en ventas bajo el mismo contexto |
| Share ventas | Ventas de la entidad / ventas del universo comparado |
| Share unidades | Unidades de la entidad / unidades del universo comparado |
| DN | Tiendas que venden la entidad / tiendas que venden la categoría |
| Frecuencia | Tickets / tiendas que venden la entidad |
| Unidades por ticket | Unidades / tickets |
| MoM | Valor del mes actual / valor del mes anterior - 1 |

Usar `NULLIF` en divisiones para evitar división por cero.

## Universos y denominadores

- En share de marca, el universo normal es la categoría de la marca.
- Si el usuario indica competidores explícitos, el universo contiene únicamente esas marcas.
- Los filtros comparables, incluida una presentación como `netQuantityValue = 500` y `unitMeasure = 'G'`, deben aplicarse a todo el universo.
- En DN se conserva período, geografía y contexto comercial, pero el denominador elimina el filtro de marca o producto objetivo y cuenta tiendas que venden la categoría.
- En penetración, el denominador cuenta cualquier tienda con venta en el mismo período y contexto; no se filtra por producto, marca ni categoría.
- En share, DN, penetración, rotación y métricas relacionadas, los filtros de `stateName`, `cityName` y `macrozone` se aplican consistentemente a numerador y universo.

## Reglas geográficas

Una macrozona no es una geografía global independiente. Valores como `Centro` pueden repetirse entre ciudades. En un desglose global se agrupa por estado, ciudad y macrozona; en un desglose completo se muestra `COALESCE(st.macrozone, 'Sin macrozona')`.

## Ejemplos de referencia

Los ejemplos completos y versionados están en el repositorio, en `docs/06-sql-examples.md`. La Wiki documenta aquí las definiciones, no una librería alternativa de consultas.
