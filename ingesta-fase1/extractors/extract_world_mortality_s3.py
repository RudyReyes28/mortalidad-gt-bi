"""

Fuente: S3 — s3://mortalidad-gt-fuentes/raw/world-mortality/
Destino: retorna pd.DataFrame (lo recibe load_sandbox.py)
"""

import io
import logging
from datetime import datetime

import boto3
import pandas as pd
from botocore.exceptions import ClientError

# Logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.s3")

#Columnas estandar del World Mortality Dataset
COLUMNAS_ESTANDAR = [
    "iso3c",
    "country_name",
    "year",
    "time",
    "time_unit",
    "deaths",
]


# Se mantienen todos los países por defecto en el Sandbox (datos crudos).
# El filtro regional se aplica en Stage (Fase 2).
PAISES_CENTROAMERICA = ["GTM", "HND", "SLV", "NIC", "CRI", "PAN", "BLZ"]


# Autenticacion 
def _crear_cliente_s3(aws_key: str, aws_secret: str, region: str):
    """
    Crea y retorna un cliente S3 autenticado con las credenciales del .env.
    """
    logger.info("Autenticando con AWS S3...")
    cliente = boto3.client(
        "s3",
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
        region_name=region,
    )
    logger.info("Autenticacion exitosa")
    return cliente


# Listar archivos en un prefijo 
def _listar_archivos(cliente, bucket: str, prefix: str) -> list[dict]:
    """
    Lista todos los archivos JSON y CSV dentro del prefijo dado en S3.
    Retorna lista de dicts con {key, size}.
    Ignora carpetas (keys que terminan en /).
    """
    logger.info(f"Listando archivos en s3://{bucket}/{prefix}...")
    try:
        respuesta = cliente.list_objects_v2(Bucket=bucket, Prefix=prefix)
    except ClientError as e:
        raise ConnectionError(f"Error al conectar con S3: {e}")

    objetos = respuesta.get("Contents", [])

    # Filtrar solo JSON y CSV, ignorar carpetas
    archivos = [
        {"key": obj["Key"], "size_kb": round(obj["Size"] / 1024, 1)}
        for obj in objetos
        if not obj["Key"].endswith("/")
        and (obj["Key"].endswith(".json") or obj["Key"].endswith(".csv"))
    ]

    if not archivos:
        raise FileNotFoundError(
            f"No se encontraron archivos JSON/CSV en s3://{bucket}/{prefix}"
        )

    logger.info(f"{len(archivos)} archivo(s) encontrado(s):")
    for a in archivos:
        logger.info(f" -> {a['key']} ({a['size_kb']} KB)")

    return archivos


# Descargar y leer un archivo desde S3 
def _descargar_archivo(cliente, bucket: str, archivo: dict) -> pd.DataFrame:
    """
    Descarga un archivo desde S3 en memoria y lo lee con pandas
    """
    key = archivo["key"]
    logger.info(f"Descargando: {key}...")

    try:
        respuesta = cliente.get_object(Bucket=bucket, Key=key)
        contenido = respuesta["Body"].read()
    except ClientError as e:
        raise IOError(f"Error al descargar {key}: {e}")

    buffer = io.BytesIO(contenido)

    if key.endswith(".json"):
        df = pd.read_json(buffer, encoding="utf-8")
    elif key.endswith(".csv"):
        df = pd.read_csv(buffer, encoding="utf-8")
    else:
        raise ValueError(f"Formato no soportado: {key}")

    logger.info(f" {len(df):,} filas leídas desde {key.split('/')[-1]}")
    return df


# Estandarizar columnas
def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Verifica que el DataFrame tenga las columnas estándar del World Mortality Dataset.
    Columnas faltantes se imputan como NULL con WARNING.
    """
    columnas_actuales  = set(df.columns)
    columnas_esperadas = set(COLUMNAS_ESTANDAR)

    faltantes = columnas_esperadas - columnas_actuales
    extras    = columnas_actuales - columnas_esperadas

    if faltantes:
        logger.warning(
            f"[{nombre_archivo}] Columnas faltantes- se imputaran NULL: {sorted(faltantes)}"
        )
        for col in faltantes:
            df[col] = None

    if extras:
        logger.info(
            f"[{nombre_archivo}] Columnas extra (se conservan en Sandbox): {sorted(extras)}"
        )

    return df[COLUMNAS_ESTANDAR]


# Agregar columnas de trazabilidad
def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Agrega columnas de control para el Sandbox:
        fuente_origen: identificador de la fuente
        archivo_origen: nombre del archivo S3 descargado
        fecha_carga: timestamp de la ejecución del pipeline
    """
    df["fuente_origen"]  = "WORLD_MORTALITY"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


#  Funcion principal exportada 
def extract_world_mortality_s3(
    bucket: str,
    prefix: str,
    aws_key: str,
    aws_secret: str,
    region: str = "us-east-1",
) -> pd.DataFrame:
    """
    Punto de entrada del extractor S3.

    Retorna:
        pd.DataFrame con todos los registros listos para el Sandbox.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor S3 (World Mortality Dataset)")
    logger.info("=" * 60)

    cliente  = _crear_cliente_s3(aws_key, aws_secret, region)
    archivos = _listar_archivos(cliente, bucket, prefix)

    dataframes = []
    errores    = []

    for archivo in archivos:
        nombre = archivo["key"].split("/")[-1]
        try:
            df = _descargar_archivo(cliente, bucket, archivo)
            df = _estandarizar_columnas(df, nombre)
            df = _agregar_trazabilidad(df, nombre)
            dataframes.append(df)
        except Exception as e:
            logger.error(f"Error procesando {nombre}: {e}")
            errores.append(nombre)

    if not dataframes:
        raise RuntimeError("Ningún archivo pudo ser procesado. Revisa los errores anteriores.")

    if errores:
        logger.warning(f"Archivos con error (no incluidos): {errores}")

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    logger.info("-" * 60)
    logger.info("Extracción completada.")
    logger.info(f"  Archivos procesados : {len(dataframes)}")
    logger.info(f"  Archivos con error : {len(errores)}")
    logger.info(f"  Total filas : {len(df_consolidado):,}")
    logger.info(f"  Países únicos  : {df_consolidado['country_name'].nunique()}")
    logger.info(f"  Rango de años : {df_consolidado['year'].min()} — {df_consolidado['year'].max()}")
    logger.info("=" * 60)

    return df_consolidado


# Ejecucion directa para pruebas locales
if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)
    print(f"Cargando .env desde: {env_path}")

    AWS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    BUCKET = os.getenv("S3_BUCKET_NAME")
    PREFIX= os.getenv("S3_PREFIX", "raw/world-mortality/")

    faltantes = [k for k, v in {
        "AWS_ACCESS_KEY_ID": AWS_KEY,
        "AWS_SECRET_ACCESS_KEY": AWS_SECRET,
        "S3_BUCKET_NAME":  BUCKET,
    }.items() if not v]

    if faltantes:
        raise EnvironmentError(f"Variables faltantes en .env: {faltantes}")

    df = extract_world_mortality_s3(BUCKET, PREFIX, AWS_KEY, AWS_SECRET, AWS_REGION)

    print(f"\nResumen del DataFrame consolidado:")
    print(f" Shape  : {df.shape}")
    print(f" Columnas  : {list(df.columns)}")
    print(f" Países únicos : {df['country_name'].nunique()}")
    print(f" Rango años : {df['year'].min()} — {df['year'].max()}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nValores NULL por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")