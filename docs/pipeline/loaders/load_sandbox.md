# Cargador — Load Sandbox

**Función principal:** Inserción de DataFrames a PostgreSQL  
**Destino:** Esquema `sandbox.*` en RDS PostgreSQL  
**Autor:** Rudy Reyes  

El módulo `load_sandbox.py` funciona como el embudo final de la Fase 1. Sin importar de qué fuente provengan los datos (Drive, S3, SharePoint o RDS), todos los DataFrames pasan por esta función para aterrizar en su tabla definitiva. 

**Estrategia de Carga:**
El pipeline utiliza una estrategia de *Truncate + Reload* (`if_exists="replace"` en Pandas). Esto garantiza que, ante múltiples ejecuciones, el Sandbox siempre sea un reflejo idéntico y actualizado de la fuente origen, evitando la duplicidad accidental de registros históricos.

**Flujo interno:**

    1. Recibe el DataFrame consolidado y la clave de la fuente (ej. `oms`).
    2. Valida contra un diccionario estricto (`TABLAS_PERMITIDAS`) para asegurar que la tabla destino sea correcta.
    3. Inicializa la conexión a PostgreSQL validando el pool de conexiones.
    4. Verifica la existencia del esquema `sandbox` y lo crea si es un despliegue nuevo.
    5. Inserta los registros en bloques de 5,000 filas (`chunksize`) optimizando la memoria RAM.
    6. Genera un diccionario estructurado con el reporte de ejecución para el orquestador general.
    7. Destruye limpiamente el motor de conexión (`engine.dispose()`).

## Variables de entorno requeridas

```bash
SANDBOX_DB_URL=postgresql://usuario:password@host:5432/mortalidad_sandbox
```

## Dependencias

```bash
pandas
SQLAlchemy
psycopg2-binary
```

## Referencia del código
::: loaders.load_sandbox
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []