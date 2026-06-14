# Data Lineage y Trazabilidad (Fase 1)

El **Data Lineage** (o linaje de datos) es el proceso que nos permite rastrear el ciclo de vida de cada registro desde su origen hasta su destino final. En la Fase 1 (Ingesta) de la Plataforma Analítica de Mortalidad GT, el objetivo es garantizar la reproducibilidad, facilitar la auditoría y asegurar que los datos crudos aterricen en el Sandbox sin perder su contexto original.

## 1. Estrategia de Carga y Persistencia

Para mantener la integridad del Sandbox como una "fotografía exacta" de las fuentes originales, el pipeline implementa un patrón de extracción completa (**Truncate + Reload**). 

En el módulo `load_sandbox.py`, la inyección de datos utiliza el parámetro `if_exists="replace"`. Esto significa que cada ejecución del orquestador borra la tabla anterior y la vuelve a crear. 

!!! info "Beneficio de esta estrategia"
    Garantiza que el Sandbox no acumule duplicados históricos ni registros huérfanos generados por múltiples ejecuciones del pipeline a lo largo del tiempo, facilitando una base limpia para la Fase 2 (Stage/Data Warehouse).

---

## 2. Trazabilidad a Nivel de Fila (Metadatos Físicos)

Todo extractor, sin importar su origen de datos, ejecuta obligatoriamente la función interna `_agregar_trazabilidad()` antes de enviar el DataFrame al cargador. Esta función inyecta tres columnas estandarizadas al final de cada tabla en el Sandbox:

| Columna | Tipo PostgreSQL | Propósito de Auditoría | Ejemplo |
|---|---|---|---|
| `fuente_origen` | `TEXT` | Identifica la entidad o el sistema macro del que provienen los datos. Útil para segmentar o depurar por proveedor de datos. | `SHAREPOINT_SCRAPING_HYBRID`, `INE` |
| `archivo_origen` | `TEXT` | Rastrea el registro hasta su archivo físico o tabla exacta de extracción. Esencial para aislar errores de archivos corruptos. | `Morticd10_part2.parquet`, `defunciones-2024.xlsx` |
| `fecha_carga` | `TEXT` | *Timestamp* de la ejecución del pipeline en la instancia EC2. Permite vincular el registro con los *logs* operacionales. | `2026-06-09 19:14:55` |

---

## 3. Trazabilidad a Nivel de Proceso (Auditoría Operacional)

A nivel de sistema, la orquestación genera evidencia inmutable de cada ejecución. El módulo `main.py` genera un archivo JSON en el directorio `ingesta-fase1/reportes/` al finalizar (o fallar) la recolección.

Estos reportes conectan la `fecha_carga` de los registros con las métricas de la infraestructura, incluyendo:

* Volumen de filas leídas y cargadas por fuente.
* Duración en segundos de cada módulo (para detectar cuellos de botella).
* Alertas o excepciones generadas durante la conexión a las APIs o bases de datos (AWS, Google Drive, SharePoint).

!!! tip "Uso para el investigador"
    Si un investigador detecta una anomalía en un cruce de datos, puede buscar el archivo JSON correspondiente a la `fecha_carga` de esos registros para auditar las condiciones del entorno y las versiones de las librerías al momento de la extracción.

---

## 4. Matriz de Mapeo Origen-Destino (Source-to-Target Map)

El siguiente cuadro detalla el recorrido exacto de cada dataset, exponiendo de forma transparente las adaptaciones técnicas (no destructivas) que el pipeline aplica para permitir el almacenamiento relacional.

| Fuente Original | Método de Extracción | Transformaciones Estructurales (Fase 1) | Destino (Sandbox) |
|---|---|---|---|
| **INE Guatemala** <br> *(Google Drive)* | API Google Drive v3 + `openpyxl` | Imputación de `NULL` en columnas ausentes (ej. `Escodif` en 2024) para homologar el esquema. | `sandbox.sandbox_ine` |
| **MSPAS COVID-19** <br> *(Google Drive)* | API Google Drive v3 + `pandas` | Desnormalización de formato Ancho (Wide) a Largo (Long) vía `pd.melt`. Se omiten fechas sin fallecidos. | `sandbox.sandbox_mspas_covid` |
| **MSPAS MEC (Crónicas)** <br> *(Google Drive)* | API Google Drive v3 + `pandas` | Limpieza de caracteres de escape en encabezados (2024) y alineación de nombres de columnas heredadas. | `sandbox.sandbox_mspas_mec` |
| **Centroamérica** <br> *(AWS RDS)* | PostgreSQL vía SQLAlchemy + `psycopg2` | Consolidación de Costa Rica y Panamá. Imputación de `NULL` cruzados por variables demográficas no compartidas. | `sandbox.sandbox_centroamerica` |
| **World Mortality** <br> *(AWS S3)* | Boto3 (AWS SDK) + `io.BytesIO` | Descarga de flujo binario a memoria; imputación de `NULL` en columnas no mapeadas. | `sandbox.sandbox_world_mortality` |
| **OMS (ICD-10)** <br> *(SharePoint)* | Scraping Híbrido (Playwright) + `pyarrow` | Lectura de 6 fragmentos binarios Parquet. Casteo forzado a tipo numérico en años y totales de defunciones. | `sandbox.sandbox_oms` |