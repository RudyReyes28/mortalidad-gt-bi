# Extractor — World Mortality Dataset (S3)

**Fuente:** AWS S3 — `s3://mortalidad-gt-fuentes/raw/world-mortality/`  
**Destino:** `sandbox.sandbox_centroamerica`  
**Autor:** Rudy Reyes  

Extrae los archivos crudos (CSV y JSON) del World Mortality Dataset directamente desde un bucket de Amazon S3. El pipeline lee el flujo binario hacia la memoria RAM sin guardar copias locales en el servidor, optimizando la velocidad de I/O.

**Flujo interno:**

    1. Autenticación segura mediante Boto3 y credenciales de AWS IAM.
    2. Explora el prefijo S3 especificado y lista objetos, ignorando carpetas estructurales.
    3. Identifica la extensión del archivo (.csv o .json) y descarga su flujo binario en memoria usando `io.BytesIO`.
    4. Verifica que existan las columnas del schema global de World Mortality.
    5. Imputa `NULL` en columnas faltantes para evitar errores de base de datos.
    6. Agrega columnas de trazabilidad (fuente, archivo original, timestamp).
    7. Concatena los registros de todos los archivos en un único DataFrame consolidado.

!!! info "Nota sobre alcance geográfico"
    El extractor descarga la totalidad de los países disponibles en el dataset para almacenarlos íntegros en el Sandbox. El filtro exclusivo para la región centroamericana se aplicará posteriormente en la fase de Stage (Transformación).

## Variables de entorno requeridas

Para ejecutar este módulo, el archivo `.env` debe contener:

```bash
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_REGION=us-east-1
S3_BUCKET_NAME=mortalidad-gt-fuentes
S3_PREFIX=raw/world-mortality/
```

## Dependencias

```bash
boto3
botocore
pandas
```

## Referencia del código
::: extractors.extract_world_mortality_s3
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []