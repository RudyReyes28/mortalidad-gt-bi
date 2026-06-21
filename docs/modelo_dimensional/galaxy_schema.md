# Modelo Dimensional - Galaxy Schema
## Capa Oro (Gold) - Data Warehouse

---

## 1. Fundamento teórico

### Familias de estrellas (Families of Stars)

Según Ponniah (*Data Warehousing Fundamentals: A Comprehensive Guide for IT Professionals*), un Data Warehouse rara vez se compone de un único esquema Estrella aislado. 

> *"Almost all data warehouses contain multiple STAR schema structures. Each STAR serves a specific purpose to track the measures stored in the fact table. When you have a collection of related STAR schemas, you may call the collection a family of STARS."*

Ponniah identifica que las familias de estrellas comparten dimensiones entre sí — típicamente la dimensión de tiempo es compartida por la mayoría de las tablas de hechos del grupo:

> *"The fact tables of the STARS in a family share dimension tables. Usually, the time dimension is shared by most of the fact tables in the group."*

Este patrón —múltiples tablas de hechos relacionadas que comparten un conjunto de dimensiones comunes— es lo que en la literatura de modelado dimensional se conoce como **Galaxy Schema** o **Fact Constellation**, y es la arquitectura que se adoptó para este Data Warehouse.

### Por qué este proyecto requiere una familia de estrellas y no una sola estrella

El criterio determinante para decidir entre una única tabla de hechos o una familia de tablas de hechos es el **grano** — el nivel de detalle que representa una fila individual en la tabla de hechos. Cuando las fuentes de datos del proyecto tienen grano heterogéneo entre sí, forzarlas dentro de una sola tabla de hechos rompe la aditividad de las métricas, un error fundamental de diseño dimensional.

En este proyecto se identificaron 5 procesos de negocio con grano distinto, derivados de las 5 tablas de la capa Stage:

| Tabla Stage | Proceso de negocio | Grano (nivel de detalle de una fila) |
|---|---|---|
| `stage_defunciones_gt` | Mortalidad general Guatemala (INE) | Una defunción individual |
| `stage_mspas_covid` | Mortalidad COVID Guatemala (MSPAS) | Fallecidos por día y municipio |
| `stage_mspas_mec` | Morbimortalidad por causa (MSPAS MEC) | Casos agregados por año/departamento/causa/grupo etario/sexo |
| `stage_mortalidad_mundial` | Mortalidad internacional (World Mortality + Centroamérica) | Defunciones agregadas por mes/país |
| `stage_covid_mundial` | COVID internacional (OMS) | Casos y muertes agregadas por mes/país |

Siguiendo el principio de Ponniah, se construyó **una tabla de hechos por cada proceso de negocio identificado**, y se diseñó un conjunto de **dimensiones conformadas** que se comparten entre las tablas de hechos cuyo grano lo permite — exactamente el mecanismo de "familia de estrellas" descrito en la teoría.

---

## 2. Arquitectura Galaxy Schema del proyecto

### Tabla de relación dimensión <-> tabla de hechos

La siguiente matriz documenta explícitamente qué dimensión es compartida por qué tabla de hechos, formalizando el concepto de dimensión conformada de Ponniah:

| Dimensión | fact_defunciones_gt | fact_mortalidad_covid_gt | fact_morbimortalidad_mec | fact_mortalidad_mundial | fact_covid_mundial |
|---|:---:|:---:|:---:|:---:|:---:|
| `dim_tiempo` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `dim_sexo` | ✓ | — | ✓ | — | — |
| `dim_grupo_etario` | ✓ | — | ✓ | — | — |
| `dim_causa_cie10` | ✓ | — | ✓ | — | — |
| `dim_geografia_gt` | ✓ | ✓ | ✓ | — | — |
| `dim_geografia_mundial` | — | — | — | ✓ | ✓ |
| `dim_fuente` | ✓ | ✓ | ✓ | ✓ | ✓ |

`dim_tiempo` y `dim_fuente` son compartidas por las 5 tablas de hechos — el caso que Ponniah describe explícitamente como el más común dentro de una familia de estrellas. `dim_geografia_gt` y `dim_geografia_mundial` se mantienen como dos dimensiones separadas en lugar de una sola, porque tienen grano geográfico distinto (municipio vs país); forzarlas en una única dimensión generaría jerarquías inconsistentes y valores nulos estructurales.

---

## 3. Dimensiones del modelo

El detalle completo de columnas, tipos de dato y reglas de cada dimensión se documenta en [`diccionario/data_warehouse.md`](../diccionario/data_warehouse.md). A continuación se describe el propósito y las decisiones de diseño de cada una.

### 3.1 `dim_tiempo`

Dimensión calendario que captura año, mes, trimestre y la clasificación de período (pre-COVID / COVID / post-COVID) que estructura todo el análisis comparativo del proyecto. Es la dimensión más compartida del modelo — presente en las 5 tablas de hechos, consistente con el patrón que describe Ponniah como el caso más común dentro de una familia de estrellas.


### 3.2 `dim_sexo`

Dimensión simple de dos valores (Masculino/Femenino) más la categoría de control "No especificado" para registros sin dato. Compartida entre `fact_defunciones_gt` y `fact_morbimortalidad_mec`, las dos únicas fuentes que registran sexo a nivel de detalle individual o desagregado.


### 3.3 `dim_grupo_etario`

Clasifica las edades en rangos quinquenales (0-4, 5-9, 10-14... hasta 70+). Se adoptó la granularidad del MSPAS MEC —más fina que la del INE— y se mapeó el INE a este mismo esquema durante la carga, para no perder detalle disponible en ninguna de las dos fuentes.

### 3.4 `dim_causa_cie10`

Cataloga los códigos de causa de defunción bajo el estándar CIE-10, junto con su descripción y capítulo correspondiente. Se desnormalizó intencionalmente en una sola tabla en lugar de separar capítulo/categoría/código en esquema Copo de Nieve (ver sección 6).


### 3.5 `dim_geografia_gt` 

Captura la jerarquía departamento/municipio de Guatemala. Se mantiene como dimensión separada de `dim_geografia_mundial` porque tiene grano geográfico distinto —municipio vs país— y combinarlas generaría jerarquías inconsistentes. Es compartida por las 3 tablas de hechos que contienen datos geográficos a nivel de Guatemala (INE, MSPAS COVID y MSPAS MEC).


### 3.6 `dim_geografia_mundial`

Captura país (código ISO3 y nombre) y región (Centroamérica, Europa, América del Sur, etc.) para las fuentes de cobertura internacional. Se mantiene separada de `dim_geografia_gt` porque ambas tienen grano geográfico distinto —país vs municipio— y combinarlas generaría jerarquías inconsistentes.


### 3.7 `dim_fuente`

Dimensión de trazabilidad que identifica la procedencia de cada registro (INE, MSPAS_COVID, MSPAS_MEC, WORLD_MORTALITY, OMS), su tipo (institucional, internacional, académico) y nivel de cobertura (nacional, regional, mundial). Permite filtrar o agrupar análisis por fuente directamente desde el DW sin volver a consultar la capa Stage.


---

## 4. Tablas de hechos del modelo

El detalle completo de columnas y claves foráneas de cada tabla de hechos se documenta en [`diccionario/data_warehouse.md`](../diccionario/data_warehouse.md). A continuación se describe el grano y propósito analítico de cada una.

### 4.1 `fact_defunciones_gt`

**Grano:** una fila por defunción individual registrada en Guatemala (fuente INE). Es la tabla de hechos más granular del modelo — cada fila representa una persona fallecida con su sexo, edad, causa CIE-10 y geografía asociada. Soporta el análisis más detallado del proyecto: comparación de mortalidad por causa específica, geografía y demografía entre los períodos pre y post COVID.

### 4.2 `fact_mortalidad_covid_gt`

**Grano:** una fila por combinación día/municipio con fallecidos COVID registrados (fuente MSPAS COVID). Incluye población del municipio para permitir el cálculo de tasas de mortalidad por 100,000 habitantes, facilitando comparaciones entre municipios de distinto tamaño.

### 4.3 `fact_morbimortalidad_mec`

**Grano:** una fila por combinación año/departamento/causa/grupo etario/sexo (fuente MSPAS MEC). Complementa a `fact_defunciones_gt` desde la perspectiva institucional del MSPAS, permitiendo validar de forma cruzada los patrones de causa de muerte observados en el INE.

### 4.4 `fact_mortalidad_mundial`

**Grano:** una fila por combinación mes/país, consolidando el World Mortality Dataset y los datos de Centroamérica (INEC Panamá y Costa Rica). Es la tabla que habilita la comparación de Guatemala frente a sus vecinos centroamericanos y países de referencia en Europa, América y Asia.

### 4.5 `fact_covid_mundial`

**Grano:** una fila por combinación mes/país (fuente OMS). Aporta la serie de casos y muertes COVID a nivel mundial, complementando `fact_mortalidad_mundial` con el detalle específico de la pandemia para los mismos países seleccionados.

---

## 5. Diagrama ERD del Galaxy Schema
El siguiente diagrama representa gráficamente la arquitectura del Galaxy Schema diseñada para este proyecto, mostrando las tablas de hechos, dimensiones y sus relaciones:

![Diagrama ERD Data Warehouse](img/ERD_Data_Warehouse.png)

---

## 6. Justificación de no usar esquema Copo de Nieve

Cada dimensión se mantiene desnormalizada (esquema Estrella) en lugar de normalizar jerarquías internas (ej. separar `dim_causa_cie10` en capítulo -> categoría -> código en tablas distintas). Esta decisión se documenta en detalle en `decisiones_diseño_dw.md`; en síntesis: el volumen de datos del proyecto no justifica el costo de mantenimiento adicional de un esquema Copo de Nieve, y el esquema Estrella ofrece mejor rendimiento de consulta para las herramientas de BI de Fase 3.

---

## 7. Referencia bibliográfica

Ponniah, P. (2001). *Data Warehousing Fundamentals: A Comprehensive Guide for IT Professionals*. John Wiley & Sons. Capítulo 11 — "Families of Stars."

---

