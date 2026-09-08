# 01 — Product Goal

## Usuario

Equipo interno de BI, inicialmente unas 5 personas con el mismo nivel de acceso.

## Problema

El equipo recibe preguntas repetitivas sobre ventas, marcas, productos, ciudades y tiendas. Resolverlas manualmente consume tiempo en consultas SQL y tickets.

## Producto

Un chat interno donde el usuario pregunta en lenguaje natural y recibe una respuesta basada en los datos reales de SQL Server.

Ejemplos:

- ¿Cuánto vendió Colgate en Bogotá en agosto de 2026?
- Top 10 productos de arroz por ventas.
- Share de Florhuila contra Roa y Diana solo en 500 g.
- ¿En qué ciudad cayó más el share de una marca?
- ¿Por qué bajaron las ventas frente al mes anterior?

## MVP exitoso

El MVP es exitoso si:

1. responde correctamente la mayoría de tickets repetitivos;
2. reduce consultas manuales del equipo;
3. conserva contexto básico: “Ahora Medellín”, “¿Y por unidades?”;
4. permite inspeccionar resultados en tabla;
5. nunca modifica datos;
6. puede corregir una consulta SQL fallida y volver a intentar.

## No objetivo del MVP

- seguridad enterprise completa;
- permisos diferentes por usuario;
- gobierno semántico formal;
- cobertura de todos los análisis imaginables;
- explicaciones causales externas;
- plataforma multi-agent.

Primero debe ser útil. Luego se endurece donde haga falta.
