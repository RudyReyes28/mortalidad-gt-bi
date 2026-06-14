# Extractor — MSPAS Enfermedades Crónicas (Google Drive / CSV)

**Fuente:** Google Drive — `mortalidad-gt-fuentes/mspas/mec/` (13 archivos CSV)  
**Destino:** `sandbox.sandbox_mspas_mec`  
**Autor:** Eiler Ajú  

Extrae los registros de enfermedades crónicas no transmisibles publicados por el MSPAS
a través de su portal de datos abiertos. Los datos cubren el período 2012–2024 en 13
archivos CSV separados (uno por año), desagregados por municipio, diagnóstico CIE-10,
grupo etario y sexo.

Una característica importante de esta fuente es que los CSVs del MSPAS presentan
**cuatro inconsistencias de esquema** entre años distintos, todas detectadas y corregidas
en el proceso de extracción.

**Flujo interno:**

1. Autentica con Google Drive API usando la misma Service Account del proyecto.
2. Navega la jerarquía `mortalidad-gt-fuentes/mspas/mec/` por nombre de carpeta.
3. Lista todos los archivos `.csv` encontrados ordenados alfabéticamente.
4. Por cada CSV: descarga en memoria → limpia headers → elimina columnas extra → renombra variantes → convierte tipos.
5. Inyecta columnas de trazabilidad (`fuente_origen`, `archivo_origen`, `fecha_carga`).
6. Concatena los 13 DataFrames en uno solo y lo retorna al pipeline.

**Reglas de limpieza aplicadas:**

| Año | Anomalía | Corrección |
|---|---|---|
| Todos | Headers con `\n` embebido | `col.replace("\n", "").strip()` |
| 2013 | Columna extra `Cantidad` entre `Diagnóstico` y `Grupo Etario` | `df.drop(columns=["Cantidad"])` |
| 2019 | Columna `CIE 10` sin guión | `rename({"CIE 10": "CIE-10"})` |
| 2020 | Columna `GrupoEtario` sin espacio | `rename({"GrupoEtario": "Grupo Etario"})` |

## Variables de entorno requeridas

```bash
GDRIVE_CREDENTIALS_PATH=/ruta/absoluta/al/service-account.json
```

## Dependencias

```bash
pandas
google-api-python-client
google-auth
```

## Referencia del código
::: extractors.extract_mspas_mec
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []