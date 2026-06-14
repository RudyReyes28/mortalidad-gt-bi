# Extractor — MSPAS Fallecidos COVID-19 (Google Drive / CSV)

**Fuente:** Google Drive — `mortalidad-gt-fuentes/mspas/covid/` (1 archivo CSV)  
**Destino:** `sandbox.sandbox_mspas_covid`  
**Autor:** Eiler Gómez  

Extrae el registro de fallecidos confirmados por COVID-19 publicado por el MSPAS
en su tablero epidemiológico (`tableros.mspas.gob.gt/covid`). El dataset cubre desde
el primer fallecido registrado en Guatemala (marzo 2020) hasta noviembre 2024.

La característica más importante de esta fuente es que el CSV original tiene
**formato ancho (wide)**: una columna por cada fecha con fallecidos, lo que resulta
en 1,063 columnas. Este extractor lo transforma a **formato largo (long/tidy)**
mediante `pd.melt()` antes de cargarlo al Sandbox, produciendo un registro por
municipio × fecha con fallecidos > 0.

**Flujo interno:**

1. Autentica con Google Drive API usando la misma Service Account del proyecto.
2. Navega la jerarquía `mortalidad-gt-fuentes/mspas/covid/` por nombre de carpeta.
3. Localiza y descarga el único CSV presente en la carpeta.
4. Detecta automáticamente las columnas de fechas (patrón `20XX-MM-DD`).
5. Aplica `pd.melt()` para pivotear de formato ancho a largo.
6. Convierte tipos: `fecha_fallecimiento` a `datetime`, numéricos a `Int64`.
7. Filtra filas con `fallecidos == 0` (no aportan al análisis).
8. Inyecta columnas de trazabilidad y retorna el DataFrame al pipeline.

**Transformación wide → long:**

```
Antes  (wide):  340 filas × 1,063 columnas
Después (long): ~17,000 filas × 9 columnas  (solo fallecidos > 0)
```

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
::: extractors.extract_mspas_covid
    options:
        show_root_heading: false
        show_if_no_docstring: false
        filters: []