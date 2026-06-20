# mortalidad-gt-bi

Plataforma Analítica de Mortalidad End-to-End — Proyecto Seminario de Sistemas 2, USAC.

---

## Requisitos previos

- Python 3.12
- PostgreSQL local con las bases de datos `mortalidad_sandbox` y `mortalidad_dw` creadas
- Archivo `.env` configurado (ver `.env.example`)

Crear las bases de datos en PostgreSQL:
```sql
CREATE DATABASE mortalidad_sandbox;
CREATE DATABASE mortalidad_dw;
```

---

## Configuración del entorno

Activar el entorno virtual desde la raíz del proyecto:

```bash
# Linux / Mac
source venv/bin/activate

# Windows
venv\Scripts\activate
```

Instalar dependencias (solo la primera vez):

```bash
pip install -r requirements.txt
```

---

## Fase 1 — Ingesta al Sandbox

Ir a la carpeta `ingesta-fase1/`:

```bash
cd ingesta-fase1
```

Correr cada fuente por separado:

```bash
python main.py --fuente ine              # INE — defunciones Guatemala (Google Drive)
python main.py --fuente world_mortality  # World Mortality Dataset (AWS S3)
python main.py --fuente centroamerica    # Panamá + Costa Rica (RDS)
python main.py --fuente mspas_mec        # MSPAS enfermedades crónicas 2012-2024 (Google Drive)
python main.py --fuente mspas_covid      # MSPAS fallecidos COVID-19 2020-2024 (Google Drive)
python main.py --fuente covid_mundial    # OMS COVID mundial — casos y muertes globales (AWS S3)
python main.py --fuente oms              # OMS mortalidad mundial (SharePoint) — tarda ~20 min
```

O correr todas las fuentes activas de una vez (excepto OMS):

```bash
python main.py --fuente ine world_mortality centroamerica mspas_mec mspas_covid covid_mundial
```

El diccionario del INE debe cargarse por separado (requerido para la Fase 2):

```bash
python extractors/extract_diccionario_ine.py
```

---

## Fase 2 — Transformación a Stage

Ir a la carpeta `transformacion-fase2/transformation/`:

```bash
cd transformacion-fase2/transformation
```

Correr cada transformación en el siguiente orden:

```bash
python transform_ine.py                  # sandbox_ine -> stage.stage_defunciones_gt
python transform_mspas_mec.py            # sandbox_mspas_mec -> stage.stage_mspas_mec
python transform_mspas_covid.py          # sandbox_mspas_covid -> stage.stage_mspas_covid
python transform_mort_mundial.py         # sandbox_world_mortality + sandbox_centroamerica -> stage.stage_mortalidad_mundial
python transform_covid_mundial.py        # sandbox_covid_mundial -> stage.stage_covid_mundial
```

> **Nota:** La tabla `sandbox_oms` no se transforma a Stage. Sus 5 millones de registros
> se conservan en Sandbox como evidencia de ingesta. El análisis internacional se cubre
> con `stage_mortalidad_mundial` y `stage_covid_mundial`.

---

## Fase 2 — Carga al Data Warehouse (local y nube)

El DW sigue un **Galaxy Schema** con 5 tablas de hechos y 7 dimensiones conformadas.
Se carga en dos destinos simultáneamente: DW local (`DW_DB_URL`) y DW en la nube (`DW_CLOUD_URL`).

Ir a la carpeta `transformacion-fase2/dw/`:

```bash
cd transformacion-fase2/dw
```

**Paso 1 — Crear las 7 dimensiones** (siempre primero, obligatorio):

```bash
python create_dimensions.py
```

Dimensiones que crea:
- `dw.dim_tiempo` — años, meses, trimestres y períodos
- `dw.dim_geografia_gt` — departamentos y municipios de Guatemala (SCD Tipo 2)
- `dw.dim_geografia_mundial` — países y regiones internacionales
- `dw.dim_causa_cie10` — códigos CIE-10 con capítulo y categoría
- `dw.dim_sexo` — catálogo de sexo
- `dw.dim_grupo_etario` — rangos de edad homologados
- `dw.dim_fuente` — sistemas de origen de los datos

**Paso 2 — Cargar las 5 tablas de hechos** (en cualquier orden):

```bash
python load_fact_defunciones_gt.py        # stage_defunciones_gt -> dw.fact_defunciones_gt
python load_fact_morbimortalidad_mec.py   # stage_mspas_mec -> dw.fact_morbimortalidad_mec
python load_fact_mortalidad_covid_gt.py   # stage_mspas_covid -> dw.fact_mortalidad_covid_gt
python load_fact_mortalidad_mundial.py    # stage_mortalidad_mundial -> dw.fact_mortalidad_mundial
python load_fact_covid_mundial.py         # stage_covid_mundial -> dw.fact_covid_mundial
```

> Si necesitas recargar el DW desde cero, trunca todas las tablas de hechos primero:
> ```sql
> TRUNCATE TABLE dw.fact_defunciones_gt RESTART IDENTITY;
> TRUNCATE TABLE dw.fact_morbimortalidad_mec RESTART IDENTITY;
> TRUNCATE TABLE dw.fact_mortalidad_covid_gt RESTART IDENTITY;
> TRUNCATE TABLE dw.fact_mortalidad_mundial RESTART IDENTITY;
> TRUNCATE TABLE dw.fact_covid_mundial RESTART IDENTITY;
> ```

---

## Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `GDRIVE_CREDENTIALS_PATH` | Ruta al JSON de la Service Account de Google Cloud |
| `SANDBOX_DB_URL` | Conexión a PostgreSQL Sandbox. Ej: `postgresql://postgres:pass@localhost:5432/mortalidad_sandbox` |
| `DW_DB_URL` | Conexión al DW local. Ej: `postgresql://postgres:pass@localhost:5432/mortalidad_dw` |
| `DW_CLOUD_URL` | Conexión al DW en la nube (RDS AWS). Ej: `postgresql://user:pass@host.rds.amazonaws.com:5432/mortalidad_dw` |
| `AWS_ACCESS_KEY_ID` | Clave de acceso AWS (extractores S3) |
| `AWS_SECRET_ACCESS_KEY` | Clave secreta AWS (extractores S3) |
| `AWS_REGION` | Región AWS. Ej: `us-east-2` |
| `S3_BUCKET_NAME` | Nombre del bucket S3 |
| `S3_PREFIX` | Prefijo del path en S3. Ej: `raw/world-mortality/` |
| `SHAREPOINT_URL` | URL del sitio SharePoint (extractor OMS) |
| `SHAREPOINT_USER` | Usuario SharePoint |
| `SHAREPOINT_PASSWORD` | Contraseña SharePoint |

---

## Flujo completo end-to-end

```
Fuentes heterogéneas
  (Google Drive, AWS S3, RDS, SharePoint)
          │
          ▼
    Sandbox (schema sandbox)       — mortalidad_sandbox
    6 tablas crudas (zona de aterrizaje fiel al origen)
          │
          ▼
    Stage (schema stage)           — mortalidad_sandbox
    5 tablas transformadas y limpias
          │
          ▼
    Data Warehouse                 — mortalidad_dw
    Galaxy Schema: 5 fact tables + 7 dimensiones conformadas
          │
          ├── DW local   (DW_DB_URL)
          └── DW nube    (DW_CLOUD_URL — RDS AWS)
```