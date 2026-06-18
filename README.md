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
python main.py --fuente oms              # OMS mortalidad mundial (SharePoint) — tarda ~20 min
```

O correr todas las fuentes activas de una vez (excepto OMS):

```bash
python main.py --fuente ine world_mortality centroamerica mspas_mec mspas_covid
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
python transform_mortalidad_mundial.py   # sandbox_world_mortality + sandbox_centroamerica -> stage.stage_mortalidad_mundial
```

> **Nota:** La tabla `sandbox_oms` no se transforma a Stage. Sus 5 millones de registros
> se conservan en Sandbox como evidencia de ingesta. El análisis internacional se cubre
> con `stage_mortalidad_mundial`.

---

## Fase 2 — Carga al Data Warehouse local

Ir a la carpeta `transformacion-fase2/dw/`:

```bash
cd transformacion-fase2/dw
```

**Paso 1 — Crear las dimensiones** (siempre primero):

```bash
python create_dimensions.py
```

**Paso 2 — Cargar la tabla de hechos** (en cualquier orden):

```bash
python load_fact_ine.py          # stage_defunciones_gt -> dw.fact_defunciones
python load_fact_mspas_mec.py    # stage_mspas_mec -> dw.fact_defunciones
python load_fact_mspas_covid.py  # stage_mspas_covid -> dw.fact_defunciones
python load_fact_mundial.py      # stage_mortalidad_mundial -> dw.fact_defunciones
```

> Si necesitas recargar el DW desde cero, trunca la tabla de hechos primero:
> ```sql
> TRUNCATE TABLE dw.fact_defunciones RESTART IDENTITY;
> ```

---

## Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `GDRIVE_CREDENTIALS_PATH` | Ruta al JSON de la Service Account de Google Cloud |
| `SANDBOX_DB_URL` | Conexión a PostgreSQL Sandbox. Ej: `postgresql://postgres:pass@localhost:5432/mortalidad_sandbox` |
| `DW_DB_URL` | Conexión al DW local. Ej: `postgresql://postgres:pass@localhost:5432/mortalidad_dw` |
| `AWS_ACCESS_KEY_ID` | Clave de acceso AWS (extractor S3) |
| `AWS_SECRET_ACCESS_KEY` | Clave secreta AWS (extractor S3) |
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
    Sandbox (schema sandbox)
    mortalidad_sandbox
          │
          ▼
    Stage (schema stage)
    mortalidad_sandbox
          │
          ▼
    Data Warehouse local (schema dw)
    mortalidad_dw
```