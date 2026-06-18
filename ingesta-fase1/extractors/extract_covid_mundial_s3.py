"""
extract_covid_mundial_s3.py
---------------------------
Extrae el dataset COVID mundial de la OMS desde AWS S3 y carga
al Sandbox en sandbox.sandbox_covid_mundial.

Fuente original : OMS / HDX
URL espejo      : https://srhdpeuwpubsa.blob.core.windows.net/whdh/COVID/WHO-COVID-19-global-data.csv
Servicio ingesta: AWS S3 -> mortalidad-gt-fuentes/raw/covid-mundial/
Tabla destino   : sandbox.sandbox_covid_mundial

Estructura del CSV:
    Date_reported     : fecha semanal del reporte
    Country_code      : código ISO2 del país
    Country           : nombre del país
    WHO_region        : región OMS (AMRO, EURO, SEARO, etc.)
    New_cases         : casos nuevos en la semana
    Cumulative_cases  : casos acumulados
    New_deaths        : muertes nuevas en la semana
    Cumulative_deaths : muertes acumuladas

"""

import io
import logging
import os
from datetime import datetime
from pathlib import Path

import boto3
import pandas as pd
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.covid_mundial")

# ── Configuración ─────────────────────────────────────────────────────────────
S3_PREFIX         = "raw/covid-mundial/"
NOMBRE_ARCHIVO    = "WHO-COVID-19-global-data.csv"
TABLA_SANDBOX     = "sandbox_covid_mundial"
SCHEMA            = "sandbox"

# ── Columnas estándar del dataset ─────────────────────────────────────────────
COLUMNAS_ESTANDAR = [
    "Date_reported",
    "Country_code",
    "Country",
    "WHO_region",
    "New_cases",
    "Cumulative_cases",
    "New_deaths",
    "Cumulative_deaths",
]


# ── Cliente S3 ────────────────────────────────────────────────────────────────
def _crear_cliente_s3(aws_key: str, aws_secret: str, region: str):
    logger.info("Autenticando con AWS S3...")
    cliente = boto3.client(
        "s3",
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
        region_name=region,
    )
    logger.info("Autenticación exitosa.")
    return cliente


# ── Descargar CSV desde S3 ────────────────────────────────────────────────────
def _descargar_csv(cliente, bucket: str, key: str) -> pd.DataFrame:
    """
    Descarga el CSV desde S3 en memoria y lo lee con pandas.
    Maneja valores vacíos en columnas numéricas.
    """
    logger.info(f"Descargando s3://{bucket}/{key}...")
    try:
        respuesta = cliente.get_object(Bucket=bucket, Key=key)
        contenido = respuesta["Body"].read()
    except ClientError as e:
        raise IOError(f"Error al descargar desde S3: {e}")

    df = pd.read_csv(
        io.BytesIO(contenido),
        encoding="utf-8",
        dtype={
            "Country_code":       str,
            "Country":            str,
            "WHO_region":         str,
            "New_cases":          "Int64",   # Int64 soporta NaN en enteros
            "Cumulative_cases":   "Int64",
            "New_deaths":         "Int64",
            "Cumulative_deaths":  "Int64",
        },
        parse_dates=["Date_reported"],
    )

    logger.info(f"  → {len(df):,} filas leídas")
    logger.info(f"  → Columnas: {list(df.columns)}")
    return df


# ── Validar y limpiar ─────────────────────────────────────────────────────────
def _limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Limpieza mínima para el Sandbox — no destructiva.
    Solo normaliza tipos y elimina filas completamente vacías.
    """
    logger.info("Aplicando limpieza mínima (Sandbox — sin transformaciones destructivas)...")

    # Eliminar filas completamente vacías
    antes = len(df)
    df = df.dropna(how="all")
    logger.info(f"  Filas vacías eliminadas: {antes - len(df):,}")

    # Limpiar espacios en columnas de texto
    for col in ["Country_code", "Country", "WHO_region"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    # Reemplazar NaN en numéricos con None (NULL en PostgreSQL)
    for col in ["New_cases", "Cumulative_cases", "New_deaths", "Cumulative_deaths"]:
        if col in df.columns:
            df[col] = df[col].where(df[col].notna(), None)

    # Verificar cobertura
    logger.info(f"  Países únicos      : {df['Country_code'].nunique()}")
    logger.info(f"  Regiones OMS       : {df['WHO_region'].unique().tolist()}")
    logger.info(f"  Rango fechas       : {df['Date_reported'].min()} → {df['Date_reported'].max()}")
    logger.info(f"  NULLs New_cases    : {df['New_cases'].isna().sum():,}")
    logger.info(f"  NULLs New_deaths   : {df['New_deaths'].isna().sum():,}")

    return df


# ── Agregar trazabilidad ──────────────────────────────────────────────────────
def _agregar_trazabilidad(df: pd.DataFrame) -> pd.DataFrame:
    df["fuente_origen"]  = "OMS_COVID_MUNDIAL"
    df["archivo_origen"] = NOMBRE_ARCHIVO
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


# ── Cargar al Sandbox ─────────────────────────────────────────────────────────
def _cargar_sandbox(df: pd.DataFrame, db_url: str):
    """Carga el DataFrame al Sandbox con estrategia replace."""
    logger.info(f"Cargando en {SCHEMA}.{TABLA_SANDBOX}...")
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    # Convertir Date_reported a string para compatibilidad PostgreSQL
    df["Date_reported"] = df["Date_reported"].astype(str)

    df.to_sql(
        name=TABLA_SANDBOX,
        con=engine,
        schema=SCHEMA,
        if_exists="replace",
        index=False,
        chunksize=5000,
        method="multi",
    )

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM {SCHEMA}.{TABLA_SANDBOX}")
        ).scalar()

    logger.info(f"  → {total:,} filas cargadas en {SCHEMA}.{TABLA_SANDBOX}")
    engine.dispose()


# ── Función principal ─────────────────────────────────────────────────────────
def extract_covid_mundial_s3(
    bucket: str,
    aws_key: str,
    aws_secret: str,
    db_url: str,
    region: str = "us-east-1",
) -> pd.DataFrame:
    """
    Extrae el dataset COVID mundial de la OMS desde S3 y carga al Sandbox.

    Args:
        bucket    : nombre del bucket S3.
        aws_key   : AWS Access Key ID.
        aws_secret: AWS Secret Access Key.
        db_url    : cadena de conexión al Sandbox PostgreSQL.
        region    : región AWS del bucket.

    Returns:
        DataFrame cargado en sandbox.sandbox_covid_mundial.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor COVID Mundial OMS (S3)")
    logger.info("=" * 60)

    cliente = _crear_cliente_s3(aws_key, aws_secret, region)

    key = f"{S3_PREFIX}{NOMBRE_ARCHIVO}"
    df  = _descargar_csv(cliente, bucket, key)
    df  = _limpiar(df)
    df  = _agregar_trazabilidad(df)

    _cargar_sandbox(df, db_url)

    logger.info("-" * 60)
    logger.info("Extracción COVID Mundial completada.")
    logger.info(f"  Filas cargadas : {len(df):,}")
    logger.info(f"  Tabla          : {SCHEMA}.{TABLA_SANDBOX}")
    logger.info("=" * 60)

    return df


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    AWS_KEY    = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    BUCKET     = os.getenv("S3_BUCKET_NAME")
    DB_URL     = os.getenv("SANDBOX_DB_URL")

    faltantes = [k for k, v in {
        "AWS_ACCESS_KEY_ID":     AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
        "S3_BUCKET_NAME":        BUCKET,
        "SANDBOX_DB_URL":        DB_URL,
    }.items() if not v]

    if faltantes:
        raise EnvironmentError(f"Variables faltantes en .env: {faltantes}")

    df = extract_covid_mundial_s3(BUCKET, AWS_KEY, AWS_SECRET, DB_URL, AWS_REGION)

    print(f"\nResumen:")
    print(f"  Shape          : {df.shape}")
    print(f"  Países únicos  : {df['Country_code'].nunique()}")
    print(f"  Rango fechas   : {df['Date_reported'].min()} → {df['Date_reported'].max()}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nNULLs por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")