# 06 — SQL Examples

Estos ejemplos sirven como few-shot para el system prompt. No son una librería obligatoria.

## 1. Ventas por marca

```sql
SELECT
    SUM(s.totalSaleValue) AS sales
FROM dbo.VW_SalesLast13Months s
JOIN dbo.VW_Products p ON p.productId = s.idProduct
JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
WHERE s.[date] >= '2026-08-01'
  AND s.[date] < '2026-09-01'
  AND p.brandName = 'COLGATE'
  AND st.cityName = 'BOGOTA';
```

## 2. Top productos por ventas

```sql
SELECT TOP 10
    p.productId,
    p.productName,
    p.barCode,
    SUM(s.totalSaleValue) AS sales
FROM dbo.VW_SalesLast13Months s
JOIN dbo.VW_Products p ON p.productId = s.idProduct
WHERE s.[date] >= '2026-08-01'
  AND s.[date] < '2026-09-01'
  AND p.categoryName = 'ARROZ'
GROUP BY p.productId, p.productName, p.barCode
ORDER BY sales DESC;
```

## 3. Share contra competidores explícitos y misma presentación

```sql
WITH market AS (
    SELECT
        p.brandName,
        SUM(s.totalSaleValue) AS sales
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Products p ON p.productId = s.idProduct
    JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
    WHERE s.[date] >= '2026-08-01'
      AND s.[date] < '2026-09-01'
      AND st.cityName = 'BOGOTA'
      AND p.netQuantityValue = 500
      AND p.unitMeasure = 'G'
      AND p.brandName IN ('FLORHUILA', 'ROA', 'DIANA')
    GROUP BY p.brandName
)
SELECT
    brandName,
    sales,
    sales / NULLIF(SUM(sales) OVER (), 0) AS sales_share
FROM market
ORDER BY sales DESC;
```

## 4. DN de una marca

```sql
WITH base AS (
    SELECT
        s.idStore,
        p.brandName,
        p.categoryName
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Products p ON p.productId = s.idProduct
    JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
    WHERE s.[date] >= '2026-08-01'
      AND s.[date] < '2026-09-01'
      AND st.cityName = 'BOGOTA'
      AND p.categoryName = 'ARROZ'
)
SELECT
    1.0 * COUNT(DISTINCT CASE WHEN brandName = 'FLORHUILA' THEN idStore END)
    / NULLIF(COUNT(DISTINCT idStore), 0) AS numeric_distribution
FROM base;
```

## 5. Penetración

```sql
WITH active_stores AS (
    SELECT DISTINCT s.idStore
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
    WHERE s.[date] >= '2026-08-01'
      AND s.[date] < '2026-09-01'
      AND st.cityName = 'BOGOTA'
),
selling_stores AS (
    SELECT DISTINCT s.idStore
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Products p ON p.productId = s.idProduct
    JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
    WHERE s.[date] >= '2026-08-01'
      AND s.[date] < '2026-09-01'
      AND st.cityName = 'BOGOTA'
      AND p.brandName = 'COLGATE'
)
SELECT
    1.0 * (SELECT COUNT(*) FROM selling_stores)
    / NULLIF((SELECT COUNT(*) FROM active_stores), 0) AS penetration;
```

## 6. MoM

```sql
WITH monthly AS (
    SELECT
        CASE
            WHEN s.[date] >= '2026-08-01' AND s.[date] < '2026-09-01' THEN 'current'
            WHEN s.[date] >= '2026-07-01' AND s.[date] < '2026-08-01' THEN 'previous'
        END AS period,
        SUM(s.totalSaleValue) AS sales
    FROM dbo.VW_SalesLast13Months s
    JOIN dbo.VW_Products p ON p.productId = s.idProduct
    WHERE s.[date] >= '2026-07-01'
      AND s.[date] < '2026-09-01'
      AND p.brandName = 'FLORHUILA'
    GROUP BY CASE
        WHEN s.[date] >= '2026-08-01' AND s.[date] < '2026-09-01' THEN 'current'
        WHEN s.[date] >= '2026-07-01' AND s.[date] < '2026-08-01' THEN 'previous'
    END
)
SELECT
    MAX(CASE WHEN period = 'current' THEN sales END)
    / NULLIF(MAX(CASE WHEN period = 'previous' THEN sales END), 0) - 1 AS mom_growth
FROM monthly;
```

## 7. Ventas por macrozona dentro de una ciudad

```sql
SELECT
    COALESCE(st.macrozone, 'Sin macrozona') AS macrozone,
    SUM(s.totalSaleValue) AS sales
FROM dbo.VW_SalesLast13Months s
JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
WHERE st.cityName = 'BOGOTA'
GROUP BY COALESCE(st.macrozone, 'Sin macrozona')
ORDER BY sales DESC;
```

## 8. Ventas por macrozona globales sin mezclar zonas homónimas

```sql
SELECT
    st.stateName,
    st.cityName,
    COALESCE(st.macrozone, 'Sin macrozona') AS macrozone,
    SUM(s.totalSaleValue) AS sales
FROM dbo.VW_SalesLast13Months s
JOIN dbo.VW_Stores st ON st.idPartner = s.idStore
GROUP BY
    st.stateName,
    st.cityName,
    COALESCE(st.macrozone, 'Sin macrozona')
ORDER BY st.stateName, st.cityName, macrozone;
```
