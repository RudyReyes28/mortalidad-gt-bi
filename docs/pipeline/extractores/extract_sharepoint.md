# Extractor — SharePoint Online (OMS)

**Fuente:** SharePoint Online — `/sites/OMS_RAW/`  
**Destino:** `sandbox.sandbox_oms`  
**Autor:** [Tu Nombre / Iniciales]  

Extrae los fragmentos particionados del dataset de mortalidad de la OMS directamente desde una carpeta institucional en SharePoint Online. El pipeline gestiona un bypass automatizado para evadir solicitudes de autenticación multifactor (MFA) y procesa el flujo binario de archivos Apache Parquet directamente en la memoria RAM, optimizando el uso de almacenamiento y CPU del servidor.

**Flujo interno:**

    1. Simulación y bypass web mediante Playwright para extraer e interceptar cookies activas de Microsoft 365.
    2. Persistencia local de estados web en `sharepoint_session.json` para agilizar ejecuciones secundarias.
    3. Construcción dinámica de URLs institucionales con parámetros de descarga (`?download=1`).
    4. Iteración secuencial sobre la lista estática de fragmentos `.parquet` esperados de la OMS.
    5. Descarga por bloques binarios directo a memoria RAM utilizando `io.BytesIO` para mitigar el I/O en disco.
    6. Mapeo y renombrado estructural del layout original ICD-10 crudo hacia el esquema unificado del Sandbox.
    7. Inyección de metadatos de auditoría y linaje de datos (fuente, archivo de origen, timestamp).
    8. Unificación y consolidación de las particiones cargadas mediante concatenación limpia en un único DataFrame.

!!! warning "Validación de Seguridad de Microsoft"
    El extractor analiza los primeros bytes de la respuesta del servidor antes de parsear el archivo. Si detecta etiquetas HTML (como `<!DOCTYPE` o `<html>`), identifica de forma preventiva que Microsoft rechazó las credenciales redirigiendo a una página de login, saltando el archivo de forma segura y evitando corrupciones en el motor PyArrow.

!!! info "Resultado"
    5,500,112 filas totales consolidadas a partir de las 6 particiones binarias (`Morticd10_part1.parquet` a `part6.parquet`).

## Variables de entorno requeridas

Para la correcta ejecución del orquestador, el archivo `.env` del proyecto debe definir los siguientes parámetros de acceso:

```bash
SHAREPOINT_URL=https://cunocxela.sharepoint.com/sites/OMS_RAW
SHAREPOINT_USER=williammiranda201930967@cunoc.edu.gt
SHAREPOINT_PASSWORD=0fab0283*
SHAREPOINT_FOLDER=/sites/OMS_RAW/Shared Documents/Mortalidad_OMS_Parquet
```

## Dependencias

```bash
playwright
requests
pandas
pyarrow
```

## Referencia del código
::: extractors.extract_sharepoint
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []        