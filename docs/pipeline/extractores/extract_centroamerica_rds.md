# Extractor — Centroamérica (RDS PostgreSQL)

**Fuente:** AWS RDS PostgreSQL — Tablas `sandbox_centroamerica_panama` y `sandbox_centroamerica_costa_rica`  
**Destino:** `sandbox.sandbox_centroamerica`  
**Autor:** Rudy Reyes  

Extrae registros históricos de mortalidad de países centroamericanos pre-cargados en bases de datos de RDS. Como cada país reporta con estructuras y niveles de detalle diferentes, este módulo se encarga de aplicar un mapeo específico por país para homogeneizar los datos en un solo esquema regional.

**Flujo interno:**

    1. Establece conexión segura con el motor RDS vía SQLAlchemy (`pool_pre_ping`).
    2. Ejecuta módulos de extracción dedicados por país.
    3. Para **Panamá**: Se mapean los desgloses de defunciones específicas, imputando como nulos los datos poblacionales ausentes.
    4. Para **Costa Rica**: Se mapean datos de población y tasa bruta, imputando como nulos los desgloses de defunciones infantiles y maternas ausentes.
    5. Cierra la conexión al motor (`engine.dispose()`) de forma limpia.
    6. Concatena los DataFrames y fuerza el orden estricto de `COLUMNAS_SALIDA`.

## Variables de entorno requeridas

El pipeline espera una cadena de conexión estándar de PostgreSQL:

```bash
RDS_SOURCE_URL=postgresql://usuario:password@host.rds.amazonaws.com:5432/base_de_datos
```

## Dependencias

```bash
pandas
SQLAlchemy
psycopg2-binary
```

## Referencia del código
::: extractors.extract_centroamerica_rds
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []