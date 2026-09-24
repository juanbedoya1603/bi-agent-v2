# 01 - Objetivo y alcance

## Objetivo

BI Agent es un chat interno para que el equipo de BI consulte ventas, productos y tiendas sin escribir manualmente cada consulta SQL. La respuesta debe basarse en datos reales y en las tres vistas lógicas autorizadas.

## Usuarios y valor

El alcance inicial está orientado a un equipo interno pequeño con acceso analítico común. El producto busca:

- reducir consultas manuales repetitivas;
- responder preguntas de ventas, marcas, productos, ciudades y tiendas;
- conservar contexto básico entre turnos, por ejemplo “Ahora Medellín” o “¿Y por unidades?”;
- mostrar resultados tabulares cuando sea útil;
- corregir una consulta SQL fallida dentro del límite de intentos;
- impedir escrituras en las fuentes analíticas.

## Dentro del alcance

- Preguntas de negocio sobre las vistas de ventas, tiendas y productos.
- Métricas BI definidas en [04 - Métricas BI](04-metricas-bi.md).
- Conversaciones multi-turn y sesiones persistentes.
- Autenticación local, administración básica de usuarios, auditoría y uso.
- Despliegue con Docker Compose detrás del Caddy de Taxonomy Organizer.

## Fuera del alcance actual

- Un DSL semántico, compilador SQL propio o capa intermedia de intención.
- Multi-agent, handoffs o una tool específica por KPI.
- Permisos analíticos distintos por usuario.
- Ingesta, scheduling o refresh de Parquet.
- Explicaciones causales externas no observables en los datos.
- Merge a `main` antes de validar el histórico completo de ADLS.

## Criterio de confiabilidad

El agente nunca debe inventar cifras. Toda respuesta numérica requiere al menos una ejecución SQL exitosa y debe reconocer cuando no hay filas, cuando un agregado es `NULL`, cuando el resultado fue truncado o cuando las tres vistas no permiten responder.
