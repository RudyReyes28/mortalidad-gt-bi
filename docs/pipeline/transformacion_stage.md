# Catálogo de Reglas de Transformación (TR)


## 1. ¿Qué significa transformar datos en este proyecto?

En este proyecto, los datos pasan principalmente por dos capas:

| Capa | Explicación |
|---|---|
| **Sandbox** | Es la capa donde los datos llegan casi como vienen de la fuente original. Aquí pueden venir con códigos, espacios extra, fechas inválidas, datos vacíos, registros repetidos o nombres escritos de formas distintas. |
| **Stage** | Es la capa donde los datos ya se dejan más limpios, ordenados y entendibles. Esta capa sirve como base para el Data Warehouse, reportes, dashboards y análisis. |

Una **regla de transformación** es una instrucción que indica cómo limpiar, corregir, convertir, clasificar o enriquecer un dato.

Ejemplo general:

| Dato en Sandbox | Regla aplicada | Dato en Stage |
|---|---|---|
| `GUATEMALA ` | Quitar espacios y dejar formato de título | `Guatemala` |
| `2020` | Clasificar período | `COVID` |
| `F` | Traducir código de sexo | `Femenino` |
| `6 meses` | Convertir edad a años | `0.50 años` |

---

## 2. Convenciones usadas 

Las convenciones sí se pueden usar en este tipo de documento. No son obligatorias, pero son recomendables porque ayudan a que todas las reglas se lean con el mismo criterio.  
En esta versión se evitan símbolos poco comunes y se usan palabras sencillas.

| Convención usada en el documento | Qué significa | Ejemplo sencillo |
|---|---|---|
| **Valor vacío** | El dato no viene informado, está en blanco o no se pudo interpretar. En base de datos también puede aparecer como `NULL`. | Si la edad viene vacía, se registra como valor vacío. |
| **Se transforma en** | Indica que un dato original cambia a otro valor más limpio, claro o útil. | `GUATEMALA ` se transforma en `Guatemala`. |
| **Se descarta el registro** | La fila no pasa a Stage porque le falta un dato obligatorio o tiene un valor inválido. | Si una defunción no tiene causa CIE-10, se descarta el registro. |
| **TR-001, TR-002, etc.** | Identificador único de cada regla de transformación. Sirve para referenciarla en documentación o en el STM. | TR-002 corresponde a la conversión de edad a años. |
| **Campo origen** | Dato que viene desde Sandbox o desde la fuente original. | `Edadif`, `Perdif`, `Caudef`. |
| **Campo destino** | Dato ya transformado que queda en Stage. | `edad_anios`, `grupo_etario`, `codigo_cie10`. |
| **Campo crítico** | Campo obligatorio para que el registro sea útil para análisis. Si falta, normalmente se elimina la fila. | Fecha de fallecimiento, causa de muerte, año o cantidad de casos. |
| **Campo derivado** | Campo nuevo que se calcula a partir de otro dato. | De `fecha_fallecimiento` se obtiene `anio` y `mes`. |
| **Catálogo o diccionario** | Tabla de apoyo usada para traducir códigos a nombres entendibles. | Código de departamento se traduce a nombre de departamento. |
| **CIE-10** | Clasificación médica internacional usada para identificar enfermedades o causas de muerte. | `J18` puede representar una causa relacionada con enfermedades respiratorias. |

## 3. REGLAS DE TRANSFORMACION 

# TR-001: Clasificación de período: pre-COVID, COVID y post-COVID

**Aplica a:** todas las fuentes.  
**Campos origen:** `Añoocu`, `year`, `anio`, `Date_reported` u otro campo que permita obtener el año.  
**Campo destino:** `periodo`.  
**Tipo:** cálculo derivado / clasificación temporal.

## Explicación

Esta regla toma el año del registro y lo clasifica en una etapa histórica:

| Año | Período asignado |
|---:|---|
| Menor que 2020 | `pre-COVID` |
| 2020 o 2021 | `COVID` |
| Mayor que 2021 | `post-COVID` |

Esto permite comparar los datos antes, durante y después de los años más fuertes de la pandemia.

## Código Python relacionado

Fragmento usado en varias fuentes:

```python
def _clasificar_periodo(anio) -> str:
    try:
        anio = int(float(anio))
        if anio < 2020:
            return "pre-COVID"
        elif anio <= 2021:
            return "COVID"
        else:
            return "post-COVID"
    except:
        return "Ignorado"
```

## Ejemplos

| Año original | Resultado en `periodo` | Explicación |
|---:|---|---|
| 2018 | `pre-COVID` | El año es anterior a 2020. |
| 2020 | `COVID` | Pertenece al período de pandemia. |
| 2021 | `COVID` | Todavía se considera período COVID. |
| 2023 | `post-COVID` | Es posterior a 2021. |
| `abc` | `Ignorado` | El valor no se puede convertir a año. |



# TR-002: Conversión de edad a años decimales

**Aplica a:** INE (`sandbox_ine`).  
**Campos origen:** `Edadif` y `Perdif`.  
**Campo destino:** `edad_anios`.  
**Tipo:** cálculo derivado / conversión de unidades.

## Explicación

En los datos del INE, la edad no siempre viene expresada en años. A veces viene en días, meses o años. Esta regla convierte todo a una sola medida: **años**.

Por ejemplo:

- 30 días se convierte aproximadamente en 0.08 años.
- 6 meses se convierte en 0.50 años.
- 25 años se mantiene como 25 años.

Esto sirve para que todas las edades se puedan comparar bajo una misma unidad.

## Código Python relacionado

```python
def _calcular_edad_anios(edadif, perdif) -> float:
    try:
        e = float(edadif)
        p = float(perdif)
        if p == 1:
            return round(e / 365, 2)     # Dias
        elif p == 2:
            return round(e / 12, 2)      # Meses
        elif p == 3:
            return e                     # Años
        else:
            return None
    except:
        return None
```

## Es decir:

| `Perdif` | Significado | Cálculo |
|---:|---|---|
| 1 | Edad en días | `Edadif / 365` |
| 2 | Edad en meses | `Edadif / 12` |
| 3 | Edad en años | `Edadif` |
| Otro valor | Unidad desconocida | `Valor vacío` |
| Valor vacío | No se puede calcular | `Valor vacío` |

## Ejemplos

| `Edadif` | `Perdif` | Interpretación original | Resultado `edad_anios` |
|---:|---:|---|---:|
| 15 | 1 | 15 días | 0.04 |
| 6 | 2 | 6 meses | 0.50 |
| 45 | 3 | 45 años | 45.00 |
| 10 | 9 | Unidad desconocida | `Valor vacío` |
| vacío | 3 | Edad ausente | `Valor vacío` |



# TR-003: Clasificación de grupo etario

**Aplica a:** INE (`sandbox_ine`).  
**Campo origen:** `edad_anios`, calculado por TR-002.  
**Campo destino:** `grupo_etario`.  
**Tipo:** cálculo derivado / categorización.

## Explicación

Esta regla agrupa la edad en rangos. En lugar de analizar edad por edad, el sistema clasifica a cada persona en un grupo como:

- Menor de 1 año.
- 1 a 4 años.
- 5 a 14 años.
- 15 a 29 años.
- 30 a 44 años.
- 45 a 59 años.
- 60 años o más.

Esto facilita el análisis por etapas de vida.

## Código Python relacionado

```python
def _clasificar_grupo_etario(edad_anios) -> str:
    if pd.isna(edad_anios):
        return "No especificado"
    elif edad_anios < 1:
        return "< 1 año"
    elif edad_anios < 5:
        return "1-4"
    elif edad_anios < 15:
        return "5-14"
    elif edad_anios < 30:
        return "15-29"
    elif edad_anios < 45:
        return "30-44"
    elif edad_anios < 60:
        return "45-59"
    else:
        return "60+"
```

## Ejemplos

| `edad_anios` | `grupo_etario` | Explicación |
|---:|---|---|
| 0.50 | `< 1 año` | Es menor de un año. |
| 3 | `1-4` | Está entre 1 y 4 años. |
| 10 | `5-14` | Está entre 5 y 14 años. |
| 27 | `15-29` | Está entre 15 y 29 años. |
| 38 | `30-44` | Está entre 30 y 44 años. |
| 50 | `45-59` | Está entre 45 y 59 años. |
| 71 | `60+` | Tiene 60 años o más. |
| `Valor vacío` | `No especificado` | No se pudo calcular la edad. |


# TR-004: Resolución de códigos mediante diccionario INE

**Aplica a:** INE (`sandbox_ine` + `sandbox_ine_diccionario`).  
**Campos origen:** `Depreg`, `Mupreg`, `Depocu`, `Mupocu`, `Sexo`, `Asist`, `Ocur`, `Puedif`.  
**Campos destino:** nombres legibles de departamento, municipio, sexo, asistencia médica, lugar de ocurrencia y pueblo de pertenencia.  
**Tipo:** traducción de catálogo.

## Explicación

Los datos del INE traen muchos campos como códigos numéricos. Para una persona, un código como `1`, `2` o `101` no dice mucho. Esta regla busca esos códigos en un diccionario y los reemplaza por textos entendibles.

Por ejemplo:

| Código | Resultado legible |
|---|---|
| `1` en sexo | `Masculino` o la etiqueta que indique el catálogo del INE |
| Código de departamento | Nombre del departamento |
| Código de municipio | Nombre del municipio |

## Código Python relacionado

Se define qué columna del archivo original corresponde a qué variable del diccionario:

```python
MAPEO_VARIABLES = {
    "Depreg": "Departamento de registro",
    "Mupreg": "Municipio de registro",
    "Depocu": "Departamento de ocurrencia",
    "Mupocu": "Municipio de ocurrencia",
    "Sexo":   "Sexo del difunto(a)",
    "Asist":  "Asistencia recibida",
    "Ocur":   "Sitio de ocurrencia",
    "Puedif": "Pueblo de pertenencia del difunto(a)"
}
```


## Ejemplos

| Campo original | Valor original | Qué hace la regla | Resultado posible |
|---|---:|---|---|
| `Depocu` | 9 | Busca el código en el catálogo de departamentos | `Quetzaltenango` |
| `Sexo` | 1 | Busca el código en el catálogo de sexo | `Masculino` |
| `Asist` | 2 | Busca el tipo de asistencia recibida | `Con asistencia médica` |
| `Puedif` | vacío | No hay dato para traducir | `Ignorado / No especificado` |
| `Mupocu` | 9999 | No existe en el catálogo | `Código no encontrado: 9999` |


# TR-005: Normalización y validación de código CIE-10

**Aplica a:** INE y MSPAS MEC.  
**Campos origen:** `Caudef` en INE y `CIE-10` en MSPAS MEC.  
**Campos destino:** `codigo_cie10`, `descripcion_causa`, `capitulo_cie10`.  
**Tipo:** limpieza, validación y enriquecimiento médico.

## Explicación

Los códigos CIE-10 identifican causas de enfermedad o muerte. Esta regla revisa que el código tenga un formato válido, lo limpia y, cuando es posible, le agrega una descripción o capítulo médico.

Por ejemplo:

| Código original | Código limpio |
|---|---|
| ` j18 ` | `J18` |
| `u07:1` | `U071` |
| vacío | `Valor vacío` o registro descartado, según la fuente |

Extracto del catálogo usado para clasificar capítulos:

```python
CAPITULOS_CIE10 = {
    "A": "Enfermedades infecciosas y parasitarias",
    "B": "Enfermedades infecciosas y parasitarias",
    "C": "Tumores / Neoplasias",
    "E": "Enfermedades endocrinas y metabólicas",
    "I": "Enfermedades del sistema circulatorio",
    "J": "Enfermedades del sistema respiratorio",
    "U": "Códigos especiales (COVID-19)",
    "V": "Causas externas"
}
```

## Ejemplos

| Fuente | Código original | Resultado | Explicación |
|---|---|---|---|
| INE | `j18` | `J18` | Se convierte a mayúsculas. |
| INE | vacío | Registro descartado | La causa de muerte es obligatoria. |
| MSPAS MEC | `u07:1` | `U071` | Se elimina `:` y se convierte a mayúsculas. |
| MSPAS MEC | `I10` | Capítulo circulatorio | La letra `I` indica sistema circulatorio. |
| MSPAS MEC | `J45` | Capítulo respiratorio | La letra `J` indica sistema respiratorio. |


# TR-006: Extracción y filtrado de fechas / años

**Aplica a:** MSPAS COVID, MSPAS MEC, COVID Mundial y Mortalidad Mundial.  
**Campos origen:** `fecha_fallecimiento`, `Año`, `Date_reported`, `year`, `anio`.  
**Campos destino:** `anio`, `mes` y filtros de rango.  
**Tipo:** conversión de fechas y control de rangos válidos.

## Explicación

Esta regla revisa que las fechas o años sean válidos y estén dentro del rango que interesa analizar. También extrae el año y el mes cuando la fuente trae una fecha completa.

Por ejemplo, de una fecha como `2021-05-14`, se obtienen:

| Fecha | Año | Mes |
|---|---:|---:|
| `2021-05-14` | 2021 | 5 |


## Resumen por fuente

| Fuente | Campo usado | Regla aplicada |
|---|---|---|
| MSPAS COVID | `fecha_fallecimiento` | Convertir a fecha, eliminar inválidas y conservar 2020-2024. |
| MSPAS MEC | `Año` | Convertir a número y conservar 2012-2024. |
| COVID Mundial | `Date_reported` | Convertir a fecha, eliminar inválidas y extraer año/mes. |
| Mortalidad Mundial | `year` | Conservar años desde 2015. |

## Ejemplos

| Valor original | Fuente | Resultado |
|---|---|---|
| `2020-08-10` | MSPAS COVID | `anio = 2020`, `mes = 8` |
| `2010` | MSPAS MEC | Se descarta porque está fuera de 2012-2024. |
| `fecha inválida` | COVID Mundial | Se descarta porque no puede convertirse a fecha. |
| `2014` | Mortalidad Mundial | Se descarta porque es menor a 2015. |



# TR-007: Metadatos de trazabilidad y auditoría

**Aplica a:** todas las fuentes.  
**Campos destino:** `fuente_origen` y `fecha_carga`.  
**Tipo:** inyección de metadatos.

## Explicación

Esta regla agrega información de control a cada registro para saber:

1. De dónde viene el dato.
2. Cuándo fue cargado o transformado.

Esto es útil para auditoría, revisión y depuración del proceso.

## Código Python relacionado

Ejemplo en INE:

```python
df_stage = pd.DataFrame({
    # campos transformados...
    "fuente_origen": "INE_STAGE",
    "fecha_carga": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
})
```

## Ejemplo

| Registro | `fuente_origen` | `fecha_carga` |
|---|---|---|
| Defunción INE | `INE_STAGE` | `2026-06-20 18:30:15` |
| Fallecimiento MSPAS COVID | `MSPAS_COVID_STAGE` | `2026-06-20 18:30:15` |



# TR-008: Descarte de registros con campos críticos nulos o inválidos

**Aplica a:** todas las fuentes.  
**Tipo:** control de calidad / eliminación de registros no útiles.

## Explicación

No todos los datos que llegan al Sandbox sirven para análisis. Si falta un dato indispensable, la fila se elimina antes de llegar a Stage.

Por ejemplo, si un registro de muerte no tiene causa de defunción, ese registro no sirve para analizar mortalidad por causa.

## Código Python relacionado

INE descarta registros sin causa CIE-10 válida:

```python
df = df[df["Caudef"].notna()]
df = df[df["Caudef"].astype(str).apply(_es_cie10_valido)]
```

## Ejemplos

| Fuente | Dato faltante o inválido | Acción |
|---|---|---|
| INE | `Caudef` vacío | Se descarta el registro. |
| MSPAS COVID | `fallecidos = 0` | Se descarta el registro. |
| MSPAS MEC | `Casos` vacío | Se descarta el registro. |
| COVID Mundial | `Date_reported` inválida | Se descarta el registro. |
| Centroamérica | `defunciones_general` vacío | Se descarta el registro. |



# TR-009: Normalización de texto

**Aplica a:** MSPAS COVID y MSPAS MEC.  
**Campos origen:** `departamento`, `municipio`, `Departamento`, `Municipio`, `Diagnóstico`.  
**Tipo:** limpieza de texto.

## Explicación

Los textos pueden venir escritos con mayúsculas, minúsculas, espacios extra o formatos distintos. Esta regla los deja con un formato más limpio y uniforme.

Por ejemplo:

| Texto original | Texto normalizado |
|---|---|
| `GUATEMALA ` | `Guatemala` |
| ` san marcos` | `San Marcos` |
| `QUETZALTENANGO` | `Quetzaltenango` |

## Código Python relacionado

```python
def _normalizar_texto(valor) -> str:
    if pd.isna(valor) or str(valor).strip() == "":
        return None
    return str(valor).strip().title()
```

Aplicación en MSPAS COVID:

```python
df["departamento_norm"] = df["departamento"].apply(_normalizar_texto)
df["municipio_norm"] = df["municipio"].apply(_normalizar_texto)
```

## Ejemplos

| Campo | Valor original | Resultado |
|---|---|---|
| Departamento | `GUATEMALA ` | `Guatemala` |
| Municipio | `san pedro sacatepequez` | `San Pedro Sacatepequez` |
| Diagnóstico | `DIABETES MELLITUS` | `Diabetes Mellitus` |
| Municipio | vacío | `Valor vacío` |



# TR-010: Deduplicación de registros

**Aplica a:** MSPAS COVID y MSPAS MEC.  
**Tipo:** control de calidad / eliminación de duplicados.

## Explicación

Esta regla elimina registros repetidos. Si dos filas representan el mismo hecho según una combinación de campos clave, se conserva solo la primera.

## Código Python relacionado

MSPAS COVID considera duplicado si coincide el municipio, cantidad fallecidos la fecha de fallecimiento:

```python
df = df.drop_duplicates(subset=["municipio","fallecidos" "fecha_fallecimiento"])
```



## Ejemplos

### Ejemplo MSPAS COVID

| Municipio | Fecha fallecimiento | Fallecidos | Acción |
|---|---|---:|---|
| Guatemala | 2021-05-10 | 2 | Se conserva. |
| Guatemala | 2021-05-10 | 2 | Se elimina por duplicado. |



# TR-011: Cálculo de tasa por 100,000 habitantes

**Aplica a:** MSPAS COVID.  
**Campos origen:** `fallecidos` y `poblacion`.  
**Campo destino:** `tasa_por_100k`.  
**Tipo:** cálculo derivado / indicador epidemiológico.

## Explicación 

Esta regla calcula cuántos fallecidos hay por cada 100,000 habitantes. Sirve para comparar lugares con poblaciones diferentes.

No es justo comparar solo el número total de fallecidos entre un municipio grande y uno pequeño. La tasa permite una comparación más equilibrada.

## Código Python relacionado

```python
def _calcular_tasa(fallecidos, poblacion) -> float:
    try:
        f = float(fallecidos)
        p = float(poblacion)
        if p > 0:
            return round((f / p) * 100_000, 4)
        return None
    except:
        return None
```

Aplicación:

```python
df["tasa_por_100k"] = df.apply(
    lambda row: _calcular_tasa(row["fallecidos"], row["poblacion"]), axis=1
)
```

## Fórmula

```text
tasa_por_100k = (fallecidos / poblacion) * 100,000
```

## Ejemplos

| Fallecidos | Población | Cálculo | Resultado |
|---:|---:|---|---:|
| 10 | 50,000 | `(10 / 50000) * 100000` | 20.0000 |
| 25 | 100,000 | `(25 / 100000) * 100000` | 25.0000 |
| 5 | 0 | No se puede dividir entre cero | `Valor vacío` |
| vacío | 100,000 | Falta dato de fallecidos | `Valor vacío` |



# TR-012: Estandarización de sexo

**Aplica a:** MSPAS MEC.  
**Campo origen:** `Sexo`.  
**Campo destino:** `sexo`.  
**Tipo:** traducción de código.

## Explicación sencilla

Esta regla convierte códigos cortos de sexo en textos completos y entendibles.

| Código original | Resultado |
|---|---|
| `F` | `Femenino` |
| `M` | `Masculino` |
| Vacío u otro valor | `No especificado` |

## Código Python relacionado

```python
MAPA_SEXO = {
    "F": "Femenino",
    "M": "Masculino",
}


def _normalizar_sexo(valor) -> str:
    if pd.isna(valor) or str(valor).strip() == "":
        return "No especificado"
    return MAPA_SEXO.get(str(valor).strip().upper(), "No especificado")
```

Aplicación:

```python
df["sexo_legible"] = df["Sexo"].apply(_normalizar_sexo)
```

## Ejemplos

| Valor original | Resultado | Explicación |
|---|---|---|
| `F` | `Femenino` | Código reconocido. |
| `M` | `Masculino` | Código reconocido. |
| ` f ` | `Femenino` | Se quitan espacios y se convierte a mayúscula. |
| `X` | `No especificado` | Código no reconocido. |
| vacío | `No especificado` | No hay dato. |



# TR-013: Filtro y mapeo de países seleccionados

**Aplica a:** COVID Mundial y Mortalidad Mundial.  
**Tipo:** filtrado geográfico y asignación de región.


## Explicación

Las fuentes mundiales pueden traer datos de muchos países. Esta regla conserva únicamente los países que interesan para el proyecto y descarta el resto.

Además, a cada país seleccionado se le asigna una región como:

- Centroamérica.
- América del Sur.
- América del Norte.
- Europa.
- Asia.
- Oceanía.

## Código Python

En `transform_covid_mundial.py`, los países vienen con código ISO2:

```python
PAISES_SELECCIONADOS = {
    # Centroamérica
    "GT": ("Guatemala", "Centroamérica"),
    "HN": ("Honduras", "Centroamérica"),
    "SV": ("El Salvador", "Centroamérica"),
    "NI": ("Nicaragua", "Centroamérica"),
    "CR": ("Costa Rica", "Centroamérica"),
    "PA": ("Panamá", "Centroamérica"),
    "BZ": ("Belice", "Centroamérica"),

    # América del Sur
    "PE": ("Perú", "América del Sur"),
    "BO": ("Bolivia", "América del Sur"),
    "EC": ("Ecuador", "América del Sur"),
    "BR": ("Brasil", "América del Sur"),
    "CO": ("Colombia", "América del Sur"),
    "AR": ("Argentina", "América del Sur"),
    "CL": ("Chile", "América del Sur"),

    # América del Norte
    "MX": ("México", "América del Norte"),
    "US": ("Estados Unidos", "América del Norte"),
    "CA": ("Canadá", "América del Norte"),

    # Europa
    "ES": ("España", "Europa"),
    "IT": ("Italia", "Europa"),
    "GB": ("Reino Unido", "Europa"),
    "DE": ("Alemania", "Europa"),
    "FR": ("Francia", "Europa"),
    "SE": ("Suecia", "Europa"),
    "PT": ("Portugal", "Europa"),
    "RU": ("Rusia", "Europa"),
    "UA": ("Ucrania", "Europa"),
    "PL": ("Polonia", "Europa"),

    # Asia
    "JP": ("Japón", "Asia"),
    "KR": ("Corea del Sur", "Asia"),
    "TR": ("Turquía", "Asia"),

    # Oceanía
    "AU": ("Australia", "Oceanía"),
    "NZ": ("Nueva Zelanda", "Oceanía"),
}
```

Filtro aplicado:

```python
df = df_raw[df_raw["Country_code"].isin(PAISES_SELECCIONADOS.keys())].copy()
```

Asignación de región:

```python
df_agg["region"] = df_agg["Country_code"].map(
    {k: v[1] for k, v in PAISES_SELECCIONADOS.items()}
)
```

## Ejemplos

| Fuente | Código país | País | Acción |
|---|---|---|---|
| COVID Mundial | `GT` | Guatemala | Se conserva. |
| COVID Mundial | `ES` | España | Se conserva. |
| COVID Mundial | `ZA` | Sudáfrica | Se descarta si no está en la lista. |
| Mortalidad Mundial | `GTM` | Guatemala | Se conserva. |
| Mortalidad Mundial | `ZAF` | Sudáfrica | Se descarta si no está en la lista. |

## Lista resumida por región

| Región | Países |
|---|---|
| Centroamérica | Guatemala, Honduras, El Salvador, Nicaragua, Costa Rica, Panamá, Belice |
| América del Sur | Perú, Bolivia, Ecuador, Brasil, Colombia, Argentina, Chile |
| América del Norte | México, Estados Unidos, Canadá |
| Europa | España, Italia, Reino Unido, Alemania, Francia, Suecia, Portugal, Rusia, Ucrania, Polonia |
| Asia | Japón, Corea del Sur, Turquía |
| Oceanía | Australia, Nueva Zelanda |

Total documentado y usado por el código: **32 países**.

---

# TR-014: Mapeo de región OMS a nombre legible

**Aplica a:** COVID Mundial.  
**Campo origen:** `WHO_region`.  
**Campo destino:** `who_region_desc`.  
**Tipo:** traducción de catálogo.

## Explicación

La OMS usa códigos cortos para sus regiones, como `AMRO` o `EURO`. Esta regla traduce esos códigos a nombres más entendibles.

## Código Python relacionado

```python
WHO_REGION_MAP = {
    "AMRO": "América",
    "EURO": "Europa",
    "SEARO": "Asia Sudoriental",
    "WPRO": "Pacífico Occidental",
    "EMRO": "Mediterráneo Oriental",
    "AFRO": "África",
    "OTHER": "Otro",
}
```

Aplicación:

```python
df_agg["who_region_desc"] = df_agg["WHO_region"].map(WHO_REGION_MAP).fillna("Otro")
```

## Ejemplos

| `WHO_region` | `who_region_desc` |
|---|---|
| `AMRO` | `América` |
| `EURO` | `Europa` |
| `SEARO` | `Asia Sudoriental` |
| `WPRO` | `Pacífico Occidental` |
| `XYZ` | `Otro` |
| vacío | `Otro` |



# TR-015: Agregación semanal a mensual en COVID Mundial

**Aplica a:** COVID Mundial.  
**Campos origen:** `New_cases`, `New_deaths`, `Cumulative_cases`, `Cumulative_deaths`, `Date_reported`.  
**Campos destino:** `new_cases_mes`, `new_deaths_mes`, `cum_cases_fin`, `cum_deaths_fin`, `semanas_reporte`.  
**Tipo:** agregación de datos.

## Explicación

La fuente de COVID Mundial trae datos reportados por semana. Pero para el análisis del proyecto se necesita trabajar por mes. Esta regla junta las semanas de un mismo mes para obtener un resumen mensual.

Por ejemplo, si Guatemala tiene cuatro reportes semanales en enero, esos cuatro reportes se combinan en una sola fila mensual de enero.

## Regla

| Campo mensual | Cómo se calcula |
|---|---|
| `new_cases_mes` | Suma los casos nuevos reportados en las semanas del mes. |
| `new_deaths_mes` | Suma las muertes nuevas reportadas en las semanas del mes. |
| `cum_cases_fin` | Toma el último acumulado de casos del mes. |
| `cum_deaths_fin` | Toma el último acumulado de muertes del mes. |
| `semanas_reporte` | Cuenta cuántos reportes semanales hubo en ese mes. |

## Ejemplo

Datos semanales originales:

| País | Fecha reporte | Casos nuevos | Muertes nuevas | Acumulado casos | Acumulado muertes |
|---|---|---:|---:|---:|---:|
| Guatemala | 2021-01-07 | 100 | 5 | 10,000 | 300 |
| Guatemala | 2021-01-14 | 150 | 7 | 10,150 | 307 |
| Guatemala | 2021-01-21 | 120 | 6 | 10,270 | 313 |
| Guatemala | 2021-01-28 | 130 | 4 | 10,400 | 317 |

Resultado mensual:

| País | Año | Mes | `new_cases_mes` | `new_deaths_mes` | `cum_cases_fin` | `cum_deaths_fin` | `semanas_reporte` |
|---|---:|---:|---:|---:|---:|---:|---:|
| Guatemala | 2021 | 1 | 500 | 22 | 10,400 | 317 | 4 |

## Importancia para el análisis

Permite que los datos mundiales tengan una granularidad mensual, más fácil de comparar con otras fuentes del proyecto.



# TR-016: Separación de tiempo: mes vs semana en Mortalidad Mundial

**Aplica a:** Mortalidad Mundial (`sandbox_world_mortality`) y Centroamérica (`sandbox_centroamerica`).  
**Campos origen:** `time`, `time_unit`, `anio`.  
**Campos destino:** `mes`, `semana`, `time_unit`.  
**Tipo:** conversión condicional de granularidad temporal.

## Explicación

La fuente mundial puede traer datos mensuales o semanales. Esta regla revisa el tipo de tiempo y coloca el valor en la columna correcta:

- Si el registro es mensual, el valor va en `mes`.
- Si el registro es semanal, el valor va en `semana`.
- Si el dato viene de la fuente anual de Centroamérica, no hay mes ni semana, solo año.

## Código Python relacionado

Para World Mortality:

```python
df["mes"] = df.apply(
    lambda row: int(row["time"]) if row["time_unit"] == "monthly" else None,
    axis=1
)

df["semana"] = df.apply(
    lambda row: int(row["time"]) if row["time_unit"] == "weekly" else None,
    axis=1
)
```

Para Centroamérica, los datos son anuales:

```python
df_norm = pd.DataFrame({
    "anio": df["anio"].astype("Int16"),
    "mes": None,
    "semana": None,
    "deaths": df["defunciones_general"],
    "time_unit": "annual",
})
```

## Ejemplos

| `time_unit` | `time` | Resultado `mes` | Resultado `semana` | Explicación |
|---|---:|---:|---:|---|
| `monthly` | 3 | 3 | `Valor vacío` | El dato corresponde al mes 3. |
| `weekly` | 12 | `Valor vacío` | 12 | El dato corresponde a la semana 12. |
| `annual` | `Valor vacío` | `Valor vacío` | `Valor vacío` | El dato solo tiene año. |


