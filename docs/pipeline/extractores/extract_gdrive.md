# Extractor — Google Drive (INE)
**Fuente:** Google Drive — `mortalidad-gt-fuentes/ine/datos/`  
**Destino:** `sandbox.sandbox_ine`  
**Autor:** Rudy Reyes  

Extrae todos los archivos `.xlsx` de defunciones del INE almacenados en Google Drive. Detecta automáticamente los archivos disponibles sin necesidad de hardcodear nombres.

**Flujo interno:**

    ```
    1. Autenticación con Service Account (Google Cloud IAM)
    2. Navega: mortalidad-gt-fuentes/ → ine/ → datos/
    3. Lista todos los .xlsx disponibles (detección automática)
    4. Descarga y lee cada archivo en memoria
    5. Estandariza columnas al schema de referencia 2018-2023
    6. Imputa NULL en columnas faltantes (Escodif, Ciuodif en 2024)
    7. Agrega columnas de trazabilidad
    8. Concatena todos los años en un DataFrame consolidado
    ```

**Variables de entorno requeridas:**

```bash
    GDRIVE_CREDENTIALS_PATH=/ruta/al/mortalidad-gt.json
```

**Dependencias:**

```bash
    google-auth
    google-auth-httplib2
    google-api-python-client
    pandas
    openpyxl
```

!!! warning "Columnas faltantes en 2024"
        El archivo `defunciones-2024.xlsx` no incluye `Escodif` ni `Ciuodif`.
        El extractor detecta esto automáticamente y lanza un `WARNING` en el log,
        imputando `NULL` en dichas columnas.

!!! info "Resultado"
        674,064 filas consolidadas de 7 archivos (2018-2024).

## Variables de entorno requeridas

```bash
GDRIVE_CREDENTIALS_PATH=/ruta/al/mortalidad-gt.json
```

## Referencia del código

::: extractors.extract_gdrive
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []
          