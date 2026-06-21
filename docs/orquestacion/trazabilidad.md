# Trazabilidad, Idempotencia y Logging

Un requisito indispensable para un pipeline de datos de nivel productivo es la capacidad de ser ejecutado de forma repetitiva sin alterar la integridad de la información ni duplicar métricas. El diseño de este repositorio analítico implementa mecanismos avanzados de control para asegurar la consistencia en cada ejecución.

## Principio de Idempotencia Aplicado

La idempotencia garantiza que si un Job se ejecuta una, dos o cien veces, el resultado final en el Data Warehouse será exactamente el mismo, previniendo la corrupción de la metadata o la duplicidad de registros. Esto se logró mediante dos estrategias diferenciadas según el tipo de tabla:

### 1. Para las Tablas de Dimensiones (`SCD Tipo 1 / Upsert`)
En lugar de vaciar las dimensiones (lo que rompería las llaves foráneas y la integridad referencial de las tablas de hechos ya cargadas), los scripts de carga utilizan tablas temporales y una instrucción de conflicto nativa de PostgreSQL:

```sql
INSERT INTO dw.dim_geografia_gt (nombre_departamento, nombre_municipio, region, pais, iso3c, fecha_inicio_vigencia, fecha_fin_vigencia, es_version_actual, version)
SELECT nombre_departamento, nombre_municipio, region, pais, iso3c, fecha_inicio_vigencia, fecha_fin_vigencia, es_version_actual, version 
FROM dw.temp_dim_geografia_gt
ON CONFLICT (nombre_departamento, nombre_municipio) DO NOTHING;
```

Si el registro de negocio ya existía de una ejecución anterior, la base de datos ignora la inserción de forma segura y mantiene las llaves primarias (`Primary Keys`) originales intactas.

### 2. Para las Tablas de Hechos (`Full Load / Truncate`)
Para evitar la duplicación de métricas cuantitativas (por ejemplo, duplicar el conteo de decesos de un mismo mes al relanzar el flujo), el pipeline ejecuta un comando de vaciado previo en el Data Warehouse antes de inyectar los datos limpios provenientes del Stage. El uso de cargas completas controladas garantiza un reflejo exacto, fresco y limpio de la historia analítica.

---

## Sistema de Logging y Auditoría

Cada evento y transformación crítica dentro del pipeline es enviado al flujo de salida estándar (`sys.stdout.flush()`). Esto permite que el entorno de ejecución capture las trazas en tiempo real y las centralice de forma automática en los servicios de monitoreo correspondientes.

Los mensajes de log están estandarizados bajo la siguiente estructura cronológica:
`[HH:MM:SS] INFO: <Mensaje de control y auditoría>`

Este diseño permite auditar con precisión:
* El volumen de filas crudas leídas desde la capa Sandbox.
* El comportamiento y éxito de las funciones de limpieza, conversión de fechas y expresiones regulares.
* La cantidad exacta de registros mensuales consolidados en el Stage.
* Los tiempos de respuesta en la apertura y cierre de conexiones hacia los endpoints de las bases de datos.

---

## Evidencias de Trazabilidad en CloudWatch

El flujo completo de auditoría y los estados de éxito de los Jobs pueden ser validados directamente a través de las herramientas de monitoreo en la nube.

![Trazas de ejecución exitosa en CloudWatch](../img/captura_cloudwatch_logs.png)
*Fotografía: Consola de CloudWatch Logs detallando la inicialización del motor SQLAlchemy, el conteo de filas leídas en Stage y el éxito del Upsert dimensional sin duplicación de llaves.*