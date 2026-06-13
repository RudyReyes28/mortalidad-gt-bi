# World Mortality Dataset

## Descripción

El World Mortality Dataset es el dataset para el seguimiento del exceso de mortalidad a nivel mundial durante la pandemia de COVID-19. Compilado por Ariel Karlinsky y Dmitry Kobak, consolida datos de mortalidad por todas las causas a nivel país, abarcando el período 2015-2024. Actualmente, tiene datos para 127 países y territorios.


## Metadatos de la Fuente

| Campo | Detalle |
|---|---|
| **Autores** | Ariel Karlinsky & Dmitry Kobak |
| **Dataset** | World Mortality Dataset |
| **URL** | [github.com/akarlinsky/world_mortality](https://github.com/akarlinsky/world_mortality/blob/main/world_mortality.csv) |
| **Formato de ingesta** | JSON  |
| **Cobertura temporal** | 2015 — 2024 |
| **Cobertura geográfica** | Mundial (múltiples países) |
| **Total de registros** | 34,387 |
| **Frecuencia** | Mensual y semanal según país |
| **Servicio de ingesta** | AWS S3 |
| **Prefijo S3** | `raw/world-mortality/` |
| **Tabla Sandbox** | `sandbox.sandbox_world_mortality` |

## Columnas y Descripciones

| Columna | Descripción |
|---|---|
| `iso3c` | Código ISO 3166-1 alpha-3 del país |
| `country_name` | Nombre del país en inglés |
| `year` | Año de registro | INTEGER | 2021 |
| `time` | Período dentro del año (semana o mes según `time_unit`) |
| `time_unit` | Unidad de tiempo del período (`weekly` o `monthly`) |
| `deaths` | Total de defunciones registradas en el período |

