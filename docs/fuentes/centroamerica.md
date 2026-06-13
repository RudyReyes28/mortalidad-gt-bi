# Centroamérica — Fuentes Regionales

## Descripción

Para situar a Guatemala en contexto regional, la plataforma integra datos de mortalidad de dos países de Centroamérica obtenidos de sus respectivos institutos nacionales de estadística: el Instituto Nacional de Estadística y Censo de Panamá (INEC Panamá) y el Instituto Nacional de Estadística y Censos de Costa Rica (INEC Costa Rica).

Estas fuentes permiten realizar comparaciones regionales de patrones de mortalidad pre-COVID (2015-2019) y post-COVID (2020 en adelante), enriqueciendo el análisis con perspectiva centroamericana.

Ambos datasets se almacenan en el RDS PostgreSQL como fuente heterogénea de tipo base de datos relacional, y son extraídos por el pipeline mediante `extract_centroamerica_rds.py`.

## Servicio de Ingesta

| Campo | Detalle |
|---|---|
| **Servicio** | AWS RDS PostgreSQL |
| **Base de datos** | `fuente_mortalidad_centroamerica` |
| **Schema** | `sandbox` |
| **Tabla Sandbox destino** | `sandbox.sandbox_centroamerica` |
| **Extractor** | `extract_centroamerica_rds.py` |

---

## Panamá — INEC

### Metadatos

| Campo | Detalle |
|---|---|
| **Institución** | Instituto Nacional de Estadística y Censo — INEC Panamá |
| **Dataset** | Defunciones y Tasas de Mortalidad en la República |
| **URL** | [inec.gob.pa](https://www.inec.gob.pa/publicaciones/Default3.aspx?ID_PUBLICACION=1309&ID_CATEGORIA=3&ID_SUBCATEGORIA=7) |
| **Formato original** | CSV (delimitado por punto y coma) |
| **Cobertura temporal** | 2000 — 2023 |
| **Cobertura geográfica** | República de Panamá |
| **Tabla RDS fuente** | `sandbox.sandbox_centroamerica_panama` |

### Columnas y Descripciones

| Columna | Descripción |
|---|---|
| `anio` | Año de registro de las defunciones |
| `defunciones_general` | Total de defunciones registradas en el año |
| `defunciones_infantil_menores_de_un_anio` | Defunciones en menores de 1 año |
| `defunciones_menores_de_5_anios` | Defunciones en menores de 5 años |
| `defunciones_materna` | Defunciones maternas |
| `defunciones_de_mujeres_en_edad_fertil` | Defunciones de mujeres en edad fértil |



## Costa Rica — INEC

### Metadatos

| Campo | Detalle |
|---|---|
| **Institución** | Instituto Nacional de Estadística y Censos — INEC Costa Rica |
| **Dataset** | Población y Defunciones 1950-2023 |
| **URL** | [admin.inec.cr](https://admin.inec.cr/sites/default/files/2024-06/sepoblacdefunf1950-2023-02.xls) |
| **Formato original** | XLS / CSV (delimitado por punto y coma) |
| **Cobertura temporal** | 1950 — 2023 |
| **Cobertura geográfica** | República de Costa Rica |
| **Tabla RDS fuente** | `sandbox.sandbox_centroamerica_costa_rica` |

### Columnas y Descripciones

| Columna | Descripción |
|---|---|
| `anio` | Año de registro |
| `poblacion_total_al_30_de_junio` | Población total estimada al 30 de junio |
| `defunciones` | Total de defunciones registradas en el año |
| `tasa_bruta_de_mortalidad_por_mil_habitantes` | Tasa bruta de mortalidad por cada 1,000 habitantes |
