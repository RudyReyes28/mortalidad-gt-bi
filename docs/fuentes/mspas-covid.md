# MSPAS — Fallecidos COVID-19 por Municipio (2020–2024)

## Descripción

El Ministerio de Salud Pública y Asistencia Social (MSPAS) publica el registro de fallecidos
confirmados por COVID-19 a través de su tablero de vigilancia epidemiológica. El dataset
contiene el conteo diario de fallecidos desagregado por municipio, cubriendo desde el primer
fallecido registrado en Guatemala (marzo 2020) hasta noviembre 2024.

Esta fuente es clave para el análisis post-COVID del proyecto, ya que permite comparar
el exceso de mortalidad específico por COVID-19 frente a las causas crónicas del período
pre-COVID (2015–2019).

## Metadatos de la Fuente

| Campo | Detalle |
|---|---|
| **Institución** | Ministerio de Salud Pública y Asistencia Social — MSPAS Guatemala |
| **Dataset** | Fallecidos por municipio, fecha de fallecimiento |
| **URL** | [tableros.mspas.gob.gt/covid](https://tableros.mspas.gob.gt/covid/) |
| **Formato** | CSV (separador `,`) |
| **Cobertura temporal** | 2020-02-13 — 2024-11-08 |
| **Cobertura geográfica** | República de Guatemala (333 municipios) |
| **Formato original** | Ancho (wide): 1 columna por fecha de fallecimiento |
| **Formato en Sandbox** | Largo (long/tidy): 1 fila por municipio × fecha |
| **Servicio de ingesta** | Google Drive (`mortalidad-gt-fuentes/mspas/covid/`) |
| **Tabla Sandbox** | `sandbox.sandbox_mspas_covid` |

## Estructura del Archivo Original (Formato Ancho)

El CSV descargado del MSPAS tiene **1,063 columnas**: 5 columnas de identificación del
municipio y 1,058 columnas de fechas (una por cada día con fallecidos registrados).

| Columnas de identificación | Columnas de fechas |
|---|---|
| `departamento`, `codigo_departamento`, `municipio`, `codigo_municipio`, `poblacion` | `2020-03-15`, `2020-03-21`, ... , `2024-11-08` |

## Transformación Aplicada en el ETL (Wide → Long)

El extractor convierte el formato ancho a formato largo mediante `pd.melt()` antes de
cargar al Sandbox, normalizando el dato para consultas por fecha:

**Antes (wide):**

| municipio | poblacion | 2020-03-15 | 2020-03-21 |
|---|---|---|---|
| GUATEMALA | 1205668 | 2 | 1 |

**Después (long):**

| municipio | poblacion | fecha_fallecimiento | fallecidos |
|---|---|---|---|
| GUATEMALA | 1205668 | 2020-03-15 | 2 |
| GUATEMALA | 1205668 | 2020-03-21 | 1 |

Solo se conservan filas con `fallecidos > 0`. Las filas con valor 0 se omiten
(representan fechas sin fallecidos en ese municipio).

## Columnas en Sandbox (Formato Largo)

| Columna | Tipo | Descripción |
|---|---|---|
| `departamento` | String | Nombre del departamento |
| `codigo_departamento` | Integer | Código numérico del departamento |
| `municipio` | String | Nombre del municipio |
| `codigo_municipio` | Integer | Código numérico del municipio |
| `poblacion` | Integer | Población del municipio |
| `fecha_fallecimiento` | Date | Fecha del fallecimiento (YYYY-MM-DD) |
| `fallecidos` | Integer | Cantidad de fallecidos por COVID-19 en esa fecha y municipio |

## Consideraciones Éticas

Los datos están publicados de forma **agregada por municipio y fecha** — no contienen
identificadores personales ni datos clínicos individuales. Cumplen con los principios
de anonimización requeridos por el EU Data Act.