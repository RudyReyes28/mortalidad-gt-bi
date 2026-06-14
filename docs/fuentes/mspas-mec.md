# MSPAS — Enfermedades Crónicas (MEC) 2012–2024

## Descripción

El Ministerio de Salud Pública y Asistencia Social (MSPAS) publica a través de su portal de
datos abiertos los registros de morbilidad por enfermedades crónicas no transmisibles, desagregados
por municipio, grupo etario, sexo y causa de muerte codificada bajo el estándar CIE-10.

Estos datos provienen del Sistema de Información Gerencial de Salud (SIGSA) y cubren las
principales causas de mortalidad crónica en Guatemala, permitiendo el análisis comparativo
del período pre-COVID (2015–2019) frente al período post-COVID (2020 en adelante).

## Metadatos de la Fuente

| Campo | Detalle |
|---|---|
| **Institución** | Ministerio de Salud Pública y Asistencia Social — MSPAS Guatemala |
| **Sistema origen** | SIGSA — Sistema de Información Gerencial de Salud |
| **Dataset** | Enfermedades Crónicas por Departamento y Municipio |
| **URL** | [datosabiertos.mspas.gob.gt](https://datosabiertos.mspas.gob.gt/dataset/enfermedades-cronicas-2012-a-2024) |
| **Formato** | CSV (separador `;`) |
| **Cobertura temporal** | 2012 — 2024 (13 archivos, uno por año) |
| **Cobertura geográfica** | República de Guatemala (departamento y municipio) |
| **Total de registros** | 537,154 |
| **Codificación de causas** | CIE-10 |
| **Servicio de ingesta** | Google Drive (`mortalidad-gt-fuentes/mspas/mec/`) |
| **Tabla Sandbox** | `sandbox.sandbox_mspas_mec` |

## Archivos Disponibles

| Archivo | Registros | Observaciones |
|---|---|---|
| mec-2012-departamento-municipio.csv | 35,127 | Schema estándar |
| mec-2013-departamento-municipio.csv | 37,081 | Columna extra `Cantidad` entre `Diagnóstico` y `Grupo Etario` |
| mec-2014-departamento-municipio.csv | 37,077 | Schema estándar |
| mec-2015-departamento-municipio.csv | 37,301 | Schema estándar |
| mec-2016-departamento-municipio.csv | 35,762 | Schema estándar |
| mec-2017-departamento-municipio.csv | 38,194 | Schema estándar |
| mec-2018-departamento-municipio.csv | 40,969 | Schema estándar |
| mec-2019-departamento-municipio.csv | 42,921 | Columna `CIE 10` sin guión (variante de nombre) |
| mec-2020-departamento-municipio.csv | 38,650 | Columna `GrupoEtario` sin espacio (variante de nombre) |
| mec-2021-departamento-municipio.csv | 40,016 | Schema estándar |
| mec-2022-departamento-municipio.csv | 45,437 | Schema estándar |
| mec-2023-departamento-municipio.csv | 51,986 | Schema estándar |
| mec-2024-departamento-municipio.csv | 56,633 | Headers con `\n` embebido en nombres de columna |

## Columnas y Descripciones

| Columna | Tipo | Descripción |
|---|---|---|
| `Año` | Integer | Año de registro del caso |
| `Departamento` | String | Departamento de ocurrencia |
| `Municipio` | String | Municipio de ocurrencia |
| `CIE-10` | String | Código de causa de muerte bajo estándar CIE-10 |
| `Diagnóstico` | String | Descripción textual del diagnóstico |
| `Grupo Etario` | String | Rango de edad del paciente (ej. `25 a 29 años`, `70+`) |
| `Sexo` | String | Sexo del paciente (`F` = Femenino, `M` = Masculino) |
| `Casos` | Integer | Cantidad de casos registrados |

## Reglas de Limpieza Aplicadas en el ETL

Documentadas en `ingesta-fase1/extractors/extract_mspas_mec.py`:

| Año afectado | Anomalía detectada | Corrección aplicada |
|---|---|---|
| Todos | Headers con `\n` embebido en nombres de columna | `col.replace("\n", "").strip()` |
| 2013 | Columna extra `Cantidad` entre `Diagnóstico` y `Grupo Etario` | `df.drop(columns=["Cantidad"])` |
| 2019 | Columna `CIE 10` sin guión | `rename({"CIE 10": "CIE-10"})` |
| 2020 | Columna `GrupoEtario` sin espacio | `rename({"GrupoEtario": "Grupo Etario"})` |

## Consideraciones Éticas

Los datos están publicados de forma **agregada por municipio, grupo etario y causa** —
no contienen identificadores personales. Cumplen con los principios de anonimización
requeridos por el EU Data Act y las políticas de manejo ético de datos sensibles de salud.