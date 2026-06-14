# Diccionario de Datos - Sandbox

El Sandbox es la zona de aterrizaje del pipeline de ingesta. Almacena los datos en su estado original, sin transformaciones destructivas, preservando la materia prima para auditoría y reproceso. Toda regla de limpieza y transformación se aplica en capas posteriores (Stage y Data Warehouse) durante la Fase 2.

## Resumen de tablas

| Tabla | Fuente | Registros | Descripción |
|---|---|---|---|
| `sandbox.sandbox_ine` | INE Guatemala — Google Drive | 674,064 | Defunciones con codificación CIE-10 (2018-2024) |
| `sandbox.sandbox_centroamerica` | INEC Panamá + INEC Costa Rica — RDS | ~200 | Mortalidad agregada anual por país |
| `sandbox.sandbox_world_mortality` | World Mortality Dataset — AWS S3 | Variable | Mortalidad por todas las causas a nivel mundial (2015-2024) |
| `sandbox.sandbox_mspas_covid` | MSPAS — Google Drive | Variable | Defunciones diarias por COVID-19 por municipio (2020-2024) |
| `sandbox.sandbox_mspas_mec` | MSPAS (SIGSA) — Google Drive | ~537,154 | Morbilidad por enfermedades crónicas (MEC) codificadas en CIE-10 (2012-2024) |
| `sandbox.sandbox_oms` | OMS — SharePoint Institucional | Variable | Mortalidad mundial codificada en CIE-10 (Histórico) |

---

## sandbox.sandbox_ine

**Fuente:** Instituto Nacional de Estadística — Guatemala  
**Servicio de ingesta:** Google Drive -> `mortalidad-gt-fuentes/ine/datos/`  
**Extractor:** `extract_gdrive.py`  
**Cobertura:** 2018 — 2024  

### Columnas originales INE

| Columna | Tipo PostgreSQL | Descripción | Valores conocidos | Notas |
|---|---|---|---|---|
| `Depreg` | BIGINT | Código del departamento donde se registró la defunción | 1-22 | Catálogo geográfico INE |
| `Mupreg` | BIGINT | Código del municipio donde se registró la defunción | Código IGSN | Concatenado con Depreg |
| `Mesreg` | BIGINT | Mes en que se registró la defunción | 1-12 | |
| `Añoreg` | BIGINT | Año en que se registró la defunción | 2018-2024 | |
| `Depocu` | BIGINT | Código del departamento donde ocurrió la defunción | 1-22 | Puede diferir de Depreg |
| `Mupocu` | BIGINT | Código del municipio donde ocurrió la defunción | Código IGSN | |
| `Sexo` | BIGINT | Sexo del fallecido | 1=Masculino, 2=Femenino | |
| `Diaocu` | BIGINT | Día en que ocurrió la defunción | 1-31 | |
| `Mesocu` | BIGINT | Mes en que ocurrió la defunción | 1-12 | |
| `Añoocu` | BIGINT | Año en que ocurrió la defunción | 2018-2024 | Puede diferir de Añoreg |
| `Edadif` | BIGINT | Edad del fallecido | 0-999 | Interpretación depende de Perdif |
| `Perdif` | BIGINT | Unidad del período de edad | 1=Días, 2=Meses, 3=Años | Necesario para interpretar Edadif |
| `Puedif` | BIGINT | Pueblo de pertenencia del fallecido | Catálogo INE | 9=No especificado |
| `Ecidif` | BIGINT | Estado civil del fallecido | 1=Soltero, 2=Casado, 3=Unido, 4=Divorciado, 5=Viudo | |
| `Escodif` | BIGINT | Escolaridad del fallecido | Catálogo INE | **NULL en 2024** — columna ausente en el archivo fuente |
| `Ciuodif` | BIGINT | Ciudad de ocurrencia de la defunción | Catálogo INE | **NULL en 2024** — columna ausente en el archivo fuente |
| `Pnadif` | BIGINT | Código del país de nacimiento del fallecido | ISO numérico | 320=Guatemala |
| `Dnadif` | BIGINT | Código del departamento de nacimiento del fallecido | 1-22 | |
| `Mnadif` | BIGINT | Código del municipio de nacimiento del fallecido | Código IGSN | |
| `Nacdif` | BIGINT | Código de nacionalidad del fallecido | ISO numérico | 320=Guatemala |
| `Predif` | BIGINT | Código del país de residencia del fallecido | ISO numérico | 9999=No especificado |
| `Dredif` | BIGINT | Código del departamento de residencia del fallecido | 1-22 | 99=No especificado |
| `Mredif` | BIGINT | Código del municipio de residencia del fallecido | Código IGSN | 9999=No especificado |
| `Caudef` | TEXT | Causa de defunción codificada en CIE-10 | Ej: W349, X959, J189 | Estándar internacional CIE-10 |
| `Asist` | BIGINT | Tipo de asistencia médica recibida | 1=Médico, 2=Partera, 3=Otro, 4=Ninguna | |
| `Ocur` | BIGINT | Lugar donde ocurrió la defunción | 1=Hospital, 2=Hogar, 3=Vía pública, 9=Otro | |
| `Cerdef` | BIGINT | Tipo de certificación de la defunción | 1=Médico, 2=Sanitario, 9=Otro | |

### Columnas de trazabilidad

| Columna | Tipo PostgreSQL | Descripción | Ejemplo |
|---|---|---|---|
| `fuente_origen` | TEXT | Identificador de la fuente de datos | `INE` |
| `archivo_origen` | TEXT | Nombre del archivo xlsx de origen | `defunciones-2024.xlsx` |
| `fecha_carga` | TEXT | Timestamp de ejecución del pipeline | `2026-06-09 19:14:55` |

### Notas de calidad

!!! warning "Columnas ausentes en 2024"
    Las columnas `Escodif` y `Ciuodif` no están presentes en el archivo `defunciones-2024.xlsx` (99,593 registros). El pipeline detecta esta diferencia automáticamente e imputa `NULL`. Posible causa: cambio en el formulario de registro del INE a partir de 2024.

!!! info "Diferencia entre registro y ocurrencia"
    Las columnas `Depreg/Mupreg/Mesreg/Añoreg` indican cuándo y dónde se **registró** la defunción. Las columnas `Depocu/Mupocu/Diaocu/Mesocu/Añoocu` indican cuándo y dónde **ocurrió**. Pueden diferir cuando el registro se hace con retraso o en un lugar distinto al de ocurrencia.

---

## sandbox.sandbox_centroamerica

**Fuente:** INEC Panamá + INEC Costa Rica  
**Servicio de ingesta:** AWS RDS PostgreSQL  
**Extractor:** `extract_centroamerica_rds.py`  
**Cobertura:** Panamá 2000-2023 · Costa Rica 1950-2023  

### Columnas

| Columna | Tipo PostgreSQL | Descripción | Panamá | Costa Rica | Notas |
|---|---|---|---|---|---|
| `pais` | TEXT | Nombre del país de origen del registro | `Panama` | `Costa Rica` | Agregado por el pipeline |
| `anio` | BIGINT | Año de registro de las defunciones | ✓ | ✓ | |
| `defunciones_general` | BIGINT | Total de defunciones registradas en el año | ✓ | ✓ | En Costa Rica viene de columna `defunciones` |
| `defunciones_infantil_menores_de_un_anio` | BIGINT | Defunciones en menores de 1 año | ✓ | NULL | No disponible en fuente Costa Rica |
| `defunciones_menores_de_5_anios` | BIGINT | Defunciones en menores de 5 años | ✓ | NULL | No disponible en fuente Costa Rica |
| `defunciones_materna` | BIGINT | Defunciones maternas | ✓ | NULL | No disponible en fuente Costa Rica |
| `defunciones_de_mujeres_en_edad_fertil` | BIGINT | Defunciones de mujeres en edad fértil | ✓ | NULL | No disponible en fuente Costa Rica |
| `poblacion_total` | BIGINT | Población total estimada al 30 de junio | NULL | ✓ | No disponible en fuente Panamá |
| `tasa_bruta_mortalidad_por_mil` | DOUBLE PRECISION | Tasa bruta de mortalidad por cada 1,000 habitantes | NULL | ✓ | No disponible en fuente Panamá |
| `fuente_origen` | TEXT | Identificador de la fuente | `CONTRALORIA_PANAMA` | `INEC_COSTA_RICA` | |
| `archivo_origen` | TEXT | Nombre del archivo cargado al RDS | `panama_defunciones.csv` | `costa_rica_defunciones.csv` | |
| `fecha_carga` | TEXT | Timestamp de ejecución del pipeline | `2026-06-09 21:00:00` | `2026-06-09 21:00:00` | |

### Notas de calidad

!!! warning "NULLs estructurales"
    Los valores NULL en esta tabla son **intencionales** — reflejan que cada país publica distintos indicadores. No son errores de ingesta sino diferencias entre las fuentes originales. La imputación o consolidación se realizará en Stage (Fase 2).

!!! info "Cobertura temporal extendida"
    Panamá tiene datos desde 2000 y Costa Rica desde 1950. El Sandbox conserva todos los registros históricos. El filtro al período de análisis del proyecto (2015 en adelante) se aplica en Stage durante la Fase 2.

---

## sandbox.sandbox_world_mortality

**Fuente:** World Mortality Dataset — Karlinsky & Kobak  
**Servicio de ingesta:** AWS S3 -> `mortalidad-gt-fuentes/raw/world-mortality/`  
**Extractor:** `extract_world_mortality_s3.py`  
**Cobertura:** 2015 — 2024 · Mundial  

### Columnas

| Columna | Tipo PostgreSQL | Descripción | Valores conocidos | Notas |
|---|---|---|---|---|
| `iso3c` | TEXT | Código ISO 3166-1 alpha-3 del país | `GTM`, `HND`, `CRI`, `PAN`... | Estándar internacional |
| `country_name` | TEXT | Nombre del país en inglés | `Guatemala`, `Honduras`... | |
| `year` | BIGINT | Año de registro | 2015-2024 | |
| `time` | BIGINT | Período dentro del año | 1-52 (semanal) · 1-12 (mensual) | Interpretación depende de `time_unit` |
| `time_unit` | TEXT | Unidad del período | `weekly`, `monthly` | Guatemala reporta `monthly` |
| `deaths` | DOUBLE PRECISION | Total de defunciones en el período | Numérico positivo | Puede ser decimal por estimación estadística |
| `fuente_origen` | TEXT | Identificador de la fuente | `WORLD_MORTALITY` | |
| `archivo_origen` | TEXT | Nombre del archivo descargado desde S3 | `world_mortality.json` | |
| `fecha_carga` | TEXT | Timestamp de ejecución del pipeline | `2026-06-09 20:00:00` | |

### Notas de calidad

!!! warning "Heterogeneidad en time_unit"
    Algunos países reportan datos semanales (`weekly`) y otros mensuales (`monthly`). Guatemala reporta en frecuencia mensual. Para comparar países con distinta frecuencia se debe normalizar en Stage (Fase 2) convirtiendo semanas a meses o usando totales anuales.

!!! info "Referencia académica"
    Karlinsky, A., & Kobak, D. (2021). Tracking excess mortality across countries during the COVID-19 pandemic with the World Mortality Dataset. *eLife*, 10, e69336.

---

---

## sandbox.sandbox_mspas_covid

**Fuente:** Ministerio de Salud Pública y Asistencia Social (MSPAS)  
**Servicio de ingesta:** Google Drive -> `mortalidad-gt-fuentes/mspas/covid/`  
**Extractor:** `extract_mspas_covid.py`  
**Cobertura:** 2020-02-13 — 2024-11-08  

### Columnas

| Columna | Tipo PostgreSQL | Descripción | Notas |
|---|---|---|---|
| `departamento` | TEXT | Nombre del departamento | |
| `codigo_departamento` | BIGINT | Código numérico del departamento | |
| `municipio` | TEXT | Nombre del municipio | |
| `codigo_municipio` | BIGINT | Código numérico del municipio | |
| `poblacion` | BIGINT | Población proyectada del municipio | |
| `fecha_fallecimiento` | TIMESTAMP | Fecha en la que ocurrió el fallecimiento | Formato YYYY-MM-DD |
| `fallecidos` | BIGINT | Cantidad de fallecidos confirmados | Solo se almacenan registros > 0 |
| `fuente_origen` | TEXT | Identificador de la fuente | `MSPAS_COVID` |
| `archivo_origen` | TEXT | Nombre del archivo descargado | |
| `fecha_carga` | TEXT | Timestamp de ejecución del pipeline | |

### Notas de calidad

!!! info "Transformación estructural (Wide a Long)"
    El archivo original del MSPAS se publica en formato ancho (1,063 columnas, con una columna por cada día). El extractor de la Fase 1 aplica un proceso de desnormalización (`pd.melt()`) para convertirlo a formato largo (una fila por municipio y fecha), optimizando el almacenamiento y las consultas SQL. Las fechas sin fallecidos (valor 0) son omitidas del Sandbox.

---

## sandbox.sandbox_mspas_mec

**Fuente:** Ministerio de Salud Pública y Asistencia Social (SIGSA)  
**Servicio de ingesta:** Google Drive -> `mortalidad-gt-fuentes/mspas/mec/`  
**Extractor:** `extract_mspas_mec.py`  
**Cobertura:** 2012 — 2024  

### Columnas

| Columna | Tipo PostgreSQL | Descripción | Notas |
|---|---|---|---|
| `Año` | BIGINT | Año de registro del caso | |
| `Departamento` | TEXT | Departamento de ocurrencia | |
| `Municipio` | TEXT | Municipio de ocurrencia | |
| `CIE-10` | TEXT | Código de causa de muerte | Estándar internacional CIE-10 |
| `Diagnóstico` | TEXT | Descripción textual del diagnóstico médico | |
| `Grupo Etario` | TEXT | Rango de edad del paciente | Ej: `25 a 29 años`, `70+` |
| `Sexo` | TEXT | Sexo del paciente | `F` = Femenino, `M` = Masculino |
| `Casos` | BIGINT | Cantidad de casos registrados para ese cruce de variables | |
| `fuente_origen` | TEXT | Identificador de la fuente | `MSPAS_MEC` |
| `archivo_origen` | TEXT | Nombre del archivo CSV original | Ej: `mec-2024-departamento-municipio.csv` |
| `fecha_carga` | TEXT | Timestamp de ejecución del pipeline | |

### Notas de calidad

!!! warning "Homologación de esquemas anuales"
    Los 13 archivos CSV originales presentan anomalías estructurales dependiendo del año de publicación. El extractor aplica reglas de limpieza dinámicas antes de la carga al Sandbox, incluyendo: corrección de saltos de línea ocultos en los encabezados (2024), eliminación de columnas redundantes (2013) y estandarización de nombres de columnas como `CIE 10` a `CIE-10` (2019) y `GrupoEtario` a `Grupo Etario` (2020).


---

## sandbox.sandbox_oms

**Fuente:** Organización Mundial de la Salud (OMS) — Base de datos de mortalidad ICD-10  
**Servicio de ingesta:** SharePoint Institucional -> `OMS_RAW/Shared Documents/Mortalidad_OMS_Parquet/`  
**Extractor:** `extract_sharepoint.py` (Scraping Híbrido)  
**Cobertura:** Histórico global (Múltiples partes)  

### Columnas y Mapeo desde la Fuente

| Columna | Tipo PostgreSQL | Mapeo Original (OMS) | Descripción | Notas |
|---|---|---|---|---|
| `iso3c` | TEXT | `Country` | Código numérico o ISO del país reportado | La OMS suele usar códigos internos numéricos en la tabla cruda. |
| `country_name` | TEXT | *Derivado de iso3c* | Nombre del país | Si la columna original no está presente, el pipeline replica el valor de `iso3c` para posterior cruce de catálogos en Stage. |
| `year` | BIGINT | `Year` | Año de registro de las defunciones | Forzado a numérico entero (`0` en caso de error/nulo). |
| `time` | TEXT | `Sex` | Categorización demográfica temporal o por sexo | |
| `time_unit` | TEXT | `List` | Formato o lista de reporte | |
| `deaths` | BIGINT | `Deaths1` | Total de defunciones | Forzado a numérico entero (`0` en caso de error/nulo). |
| `fuente_origen` | TEXT | N/A | Identificador de la fuente | Valor estático: `SHAREPOINT_SCRAPING_HYBRID`. |
| `archivo_origen` | TEXT | N/A | Nombre del fragmento procesado | Ej: `Morticd10_part1.parquet` |
| `fecha_carga` | TEXT | N/A | Timestamp de ejecución | |

### Notas de calidad

!!! warning "Estructura Particionada (Parquet)"
    Dado el inmenso volumen de datos de mortalidad mundial de la OMS, los archivos en SharePoint están divididos en 6 fragmentos binarios `.parquet` (`Morticd10_part1` a `part6`). El extractor descarga los flujos binarios uno a uno utilizando la sesión inyectada por Playwright y los consolida en memoria RAM mediante la librería `pyarrow` antes de la carga final.

!!! info "Casteo Seguro de Tipos de Datos (Type Casting)"
    Para garantizar que la base de datos PostgreSQL no rechace la inserción masiva debido a registros anómalos o *strings* vacíos en la data de la OMS, el pipeline aplica un casteo forzado (`pd.to_numeric(..., errors="coerce").fillna(0)`) en las columnas `year` y `deaths`.

## Columnas de trazabilidad — estándar del pipeline

Las seis tablas comparten las mismas columnas de control agregadas automáticamente por el pipeline:

| Columna | Tipo | Descripción | Propósito |
|---|---|---|---|
| `fuente_origen` | TEXT | Identificador único de la fuente | Identifica el origen del dato en el data lineage |
| `archivo_origen` | TEXT | Nombre del archivo o tabla de origen | Permite rastrear el dato hasta el archivo exacto |
| `fecha_carga` | TEXT | Timestamp de la ejecución del pipeline | Permite saber cuándo fue cargado cada lote de datos |

!!! info "Anti-duplicados"
    Cada ejecución del pipeline aplica `if_exists='replace'` — la tabla se trunca y recarga completamente. La columna `fecha_carga` refleja la última ejecución exitosa.