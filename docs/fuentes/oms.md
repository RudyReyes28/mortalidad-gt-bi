# OMS — WHO Mortality Database 2002–2021

## Descripción

La Organización Mundial de la Salud (OMS / WHO) centraliza y publica las estadísticas de mortalidad global notificadas por los sistemas nacionales de registro civil de cada país. Este conjunto de datos masivo permite el análisis de tendencias de mortalidad por causas específicas a nivel internacional, codificadas bajo la Clasificación Internacional de Enfermedades (CIE-10).

A diferencia de las fuentes locales, este dataset se consolidó a partir de una infraestructura híbrida institucional para analizar el impacto demográfico global pre-pandemia y durante el cierre del año 2021.

## Metadatos de la Fuente

| Campo | Detalle |
|---|---|
| **Institución** | World Health Organization (WHO) — Organización Mundial de la Salud |
| **Sistema origen** | WHO Mortality Database |
| **Dataset** | Underlying Cause of Death (ICD-10) Data Files |
| **URL** | [who.int/data/data-collection-tools/who-mortality-database](https://www.who.int/data/data-collection-tools/who-mortality-database) |
| **Formato de ingesta** | Apache Parquet (Procesamiento columnar binario) |
| **Cobertura temporal** | 2002 — 2021 |
| **Cobertura geográfica** | Mundial (Múltiples países y territorios notificados) |
| **Total de registros** | 5,500,112 filas consolidadas |
| **Codificación de causas** | CIE-10 (ICD-10) |
| **Servicio de ingesta** | SharePoint Online Corporativo (`/sites/OMS_RAW/`) |
| **Tabla Sandbox** | `sandbox.sandbox_oms` |

## Archivos Disponibles

El dataset original fue pre-procesado, optimizado y segmentado en formato columnar para agilizar la transferencia HTTP desde la nube institucional (Sharepoint: CUNOC) hacia el servidor local:

| Archivo | Formato | Observaciones |
|---|---|---|
| `Morticd10_part1.parquet` | Parquet | Schema estándar binario (Compresión interna) |
| `Morticd10_part2.parquet` | Parquet | Schema estándar binario (Compresión interna) |
| `Morticd10_part3.parquet` | Parquet | Schema estándar binario (Compresión interna) |
| `Morticd10_part4.parquet` | Parquet | Schema estándar binario (Compresión interna) |
| `Morticd10_part5.parquet` | Parquet | Schema estándar binario (Compresión interna) |
| `Morticd10_part6.parquet` | Parquet | Schema estándar binario (Compresión interna) |

## Columnas y Descripciones (Esquema Destino)

El proceso de extracción filtra las tablas masivas de hechos originales y moldea las siguientes 5 columnas principales requeridas por el área de Business Intelligence para la construcción del Sandbox final:

| Columna | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `iso3c` | String | Código de país original de la OMS (Clave natural del registro) | `1400` |
| `country_name` | String | Código de país replicado (Destinado a homologación con catálogos ISO-Alpha-3 en Fase 2) | `1400` |
| `year` | Integer | Año de ocurrencia del deceso | `2001` |
| `time` | String | Desagregación demográfica por Sexo según el catálogo OMS | `1` |
| `time_unit` | String | Lista o variante epidemiológica bajo la cual se reportó el caso | `101` |
| `deaths` | Integer | Cantidad total de defunciones registradas para esa partición | `332` |

>  **Nota sobre Trazabilidad:** Adicionalmente, el pipeline añade en caliente las columnas de auditoría `fuente_origen` (`SHAREPOINT_SCRAPING_HYBRID`), `archivo_origen` y `fecha_carga` al momento de persistir la data en PostgreSQL.

## Reglas de Limpieza y Automatización Aplicadas (El ETL)

Documentadas e implementadas en el módulo `ingesta-fase1/extractors/extract_sharepoint.py`:

* **Bypass de Autenticación Corporativa (MFA):** Extracción automatizada en segundo plano (*Headless=True*) de cookies y tokens válidos de Microsoft 365 mediante **Playwright**. Implementa persistencia de estado a través de un archivo local `sharepoint_session.json` para evadir solicitudes recurrentes de MFA tras el primer login exitoso.
* **Consumo Eficiente de Memoria RAM:** Descarga de fragmentos masivos mediante peticiones binarias con `requests.get()` mapeadas directamente a memoria con un flujo `io.BytesIO()`. Evita la escritura en disco duro de archivos temporales e intermedios.
* **Procesamiento de Alto Rendimiento:** Migración estructural de lectura de archivos planos planos (`.csv`) hacia almacenamiento columnar de alto rendimiento con **Apache Parquet** (`read_parquet` soportado por el motor `pyarrow`). Esto disminuye los tiempos de transferencia de la red y el uso de CPU.
* **Homologación Preventiva de Claves:** Replicación directa del código numérico del país (`iso3c`) en la columna `country_name`. Esto preserva la clave primaria íntegra para facilitar transformaciones (`LEFT JOIN`) mediante herramientas de modelado de datos en la Fase 2 del Data Warehouse.