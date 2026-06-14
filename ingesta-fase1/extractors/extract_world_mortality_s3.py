"""
Módulo de extracción de datos del World Mortality Dataset desde AWS S3.

Se encarga de establecer conexión con Amazon S3 mediante Boto3, listar los 
archivos crudos (JSON) alojados bajo un prefijo específico, descargarlos 
directamente en memoria, estandarizar su estructura de columnas e inyectar la 
trazabilidad necesaria antes de enviarlos al Sandbox.
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

# Columnas estandar del World Mortality Dataset
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


def _crear_cliente_s3(aws_key: str, aws_secret: str, region: str):
    """
    Crea y retorna un cliente de Amazon S3 autenticado.

    Args:
        aws_key (str): ID de la llave de acceso de AWS (Access Key ID).
        aws_secret (str): Llave secreta de acceso de AWS (Secret Access Key).
        region (str): Región de AWS donde se aloja el bucket (ej. 'us-east-1').

    Returns:
        botocore.client.S3: Cliente Boto3 inicializado y listo para interactuar con S3.
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


def _listar_archivos(cliente, bucket: str, prefix: str) -> list[dict]:
    """
    Lista todos los archivos JSON y CSV dentro del prefijo dado en S3.

    Explora el bucket ignorando explícitamente los objetos que representan 
    carpetas (cuyas llaves terminan en `/`).

    Args:
        cliente (botocore.client.S3): Cliente autenticado de Boto3.
        bucket (str): Nombre del bucket de destino.
        prefix (str): Ruta o prefijo donde se encuentran los archivos.

    Returns:
        list[dict]: Lista de diccionarios, donde cada elemento contiene el 
            identificador del archivo (`key`) y su tamaño en KB (`size_kb`).

    Raises:
        ConnectionError: Si ocurre un fallo de red o permisos al contactar la API de AWS.
        FileNotFoundError: Si no se encuentran archivos válidos (.json o .csv) en la ruta.
    """
    logger.info(f"Listando archivos en s3://{bucket}/{prefix}...")
    try:
        respuesta = cliente.list_objects_v2(Bucket=bucket, Prefix=prefix)
    except ClientError as e:
        raise ConnectionError(f"Error al conectar con S3: {e}")

    objetos = respuesta.get("Contents", [])

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


def _descargar_archivo(cliente, bucket: str, archivo: dict) -> pd.DataFrame:
    """
    Descarga un archivo desde S3 hacia la memoria y lo convierte en DataFrame.

    Detecta la extensión del archivo a partir de su llave para utilizar 
    el motor de lectura de Pandas adecuado (`read_json` o `read_csv`).

    Args:
        cliente (botocore.client.S3): Cliente autenticado de Boto3.
        bucket (str): Nombre del bucket de origen.
        archivo (dict): Diccionario con la metadata del archivo (debe contener 'key').

    Returns:
        pd.DataFrame: DataFrame con la información contenida en el archivo.

    Raises:
        IOError: Si la descarga del flujo binario falla.
        ValueError: Si el archivo no tiene una extensión soportada (.csv o .json).
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


def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Verifica y adapta el DataFrame al esquema estándar del World Mortality Dataset.

    Si faltan columnas, las imputa con valores NULL generando un WARNING. 
    Las columnas extra que traiga el archivo original no se eliminan en esta fase, 
    se conservan para el Sandbox.

    Args:
        df (pd.DataFrame): DataFrame original descargado.
        nombre_archivo (str): Nombre del archivo procesado para trazas en el log.

    Returns:
        pd.DataFrame: DataFrame con las columnas ordenadas según `COLUMNAS_ESTANDAR`.
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


def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Agrega columnas de control y auditoría para el almacenamiento en Sandbox.

    Args:
        df (pd.DataFrame): DataFrame con la información estandarizada.
        nombre_archivo (str): Nombre físico del objeto en S3.

    Returns:
        pd.DataFrame: El mismo DataFrame incluyendo `fuente_origen`, 
            `archivo_origen`, y `fecha_carga`.
    """
    df["fuente_origen"]  = "WORLD_MORTALITY"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def extract_world_mortality_s3(
    bucket: str,
    prefix: str,
    aws_key: str,
    aws_secret: str,
    region: str = "us-east-1",
) -> pd.DataFrame:
    """
    Orquestador principal del extractor del World Mortality Dataset en AWS S3.

    Se encarga de coordinar la autenticación, listar los archivos disponibles, 
    descargar cada uno a memoria RAM de forma iterativa, estandarizarlos y 
    consolidarlos en un único DataFrame para la ingesta.

    Args:
        bucket (str): Nombre del bucket de S3.
        prefix (str): Ruta interna dentro del bucket donde residen los datos.
        aws_key (str): Access Key ID de IAM.
        aws_secret (str): Secret Access Key de IAM.
        region (str, optional): Región de AWS. Por defecto es "us-east-1".

    Returns:
        pd.DataFrame: Conjunto de datos consolidado con los registros de 
            todos los archivos procesados.

    Raises:
        RuntimeError: Si ocurre un fallo global y no se procesa ningún archivo.
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