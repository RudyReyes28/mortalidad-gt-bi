"""
Módulo de extracción de fallecidos COVID-19 del MSPAS desde Google Drive.

Este script se encarga de autenticarse con la API de Google Drive, navegar
al directorio `mortalidad-gt-fuentes/mspas/covid/` y descargar el CSV de
fallecidos por COVID-19 publicado en el tablero epidemiológico del MSPAS
(https://tableros.mspas.gob.gt/covid/).

El archivo original tiene formato ancho (wide): una columna por cada fecha
con fallecidos registrados. Este módulo lo transforma a formato largo (long/tidy)
mediante `pd.melt()` antes de cargarlo al Sandbox, normalizando el dato para
que sea consultable por fecha y municipio.
"""

import io
import logging
from datetime import datetime

import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.mspas_covid")

# Configuración
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

NOMBRE_CARPETA_RAIZ  = "mortalidad-gt-fuentes"
NOMBRE_CARPETA_MSPAS = "mspas"
NOMBRE_CARPETA_COVID = "covid"

# Columnas fijas de identificación (no son fechas)
COLUMNAS_ID = [
    "departamento", "codigo_departamento",
    "municipio", "codigo_municipio", "poblacion"
]

# Columnas canónicas del DataFrame resultante (formato largo)
COLUMNAS_ESTANDAR = COLUMNAS_ID + ["fecha_fallecimiento", "fallecidos"]


def _autenticar(ruta_credenciales: str):
    """
    Autentica con la API de Google Drive utilizando una Service Account.

    Args:
        ruta_credenciales (str): Ruta absoluta al archivo JSON que contiene
            las credenciales de la cuenta de servicio de Google Cloud.

    Returns:
        googleapiclient.discovery.Resource: Objeto de servicio listo para
            interactuar con la API de Google Drive (versión v3).
    """
    logger.info("Autenticando con Google Drive API...")
    creds = service_account.Credentials.from_service_account_file(
        ruta_credenciales, scopes=SCOPES
    )
    servicio = build("drive", "v3", credentials=creds)
    logger.info("Autenticación exitosa.")
    return servicio


def _buscar_carpeta(servicio, nombre: str, padre_id: str = None) -> str:
    """
    Busca una carpeta específica por su nombre dentro de Google Drive.

    Realiza una consulta a la API de Drive filtrando por tipo MIME (carpeta)
    y verificando que no esté en la papelera. Opcionalmente restringe la
    búsqueda a un directorio padre.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        nombre (str): Nombre exacto de la carpeta a buscar.
        padre_id (str, optional): ID de la carpeta padre donde se realizará
            la búsqueda. Por defecto es None (búsqueda global).

    Returns:
        str: El ID único de la carpeta encontrada en Google Drive.

    Raises:
        ValueError: Si la carpeta solicitada no es encontrada en Drive.
    """
    query = f"name='{nombre}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if padre_id:
        query += f" and '{padre_id}' in parents"

    resultado = servicio.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()

    carpetas = resultado.get("files", [])
    if not carpetas:
        raise ValueError(f"Carpeta '{nombre}' no encontrada en Drive.")

    carpeta_id = carpetas[0]["id"]
    logger.info(f"Carpeta '{nombre}' encontrada. ID: {carpeta_id}")
    return carpeta_id


def _buscar_csv_covid(servicio, carpeta_id: str) -> dict:
    """
    Localiza el archivo CSV de fallecidos COVID dentro de la carpeta `covid/`.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        carpeta_id (str): ID de la carpeta `mspas/covid/` en Drive.

    Returns:
        dict: Diccionario con claves `id` y `name` del primer CSV encontrado.

    Raises:
        FileNotFoundError: Si no existe ningún CSV en la carpeta indicada.
    """
    query = (
        f"'{carpeta_id}' in parents"
        " and trashed=false"
        " and (mimeType='text/csv' or name contains '.csv')"
    )
    resultado = servicio.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()

    archivos = resultado.get("files", [])
    if not archivos:
        raise FileNotFoundError("No se encontró CSV en mspas/covid/")

    logger.info(f"CSV encontrado: {archivos[0]['name']}")
    return archivos[0]


def _descargar_csv(servicio, archivo: dict) -> pd.DataFrame:
    """
    Descarga el CSV de fallecidos COVID directamente desde Drive hacia memoria RAM.

    Utiliza `MediaIoBaseDownload` para descargar el flujo binario por fragmentos
    en un búfer temporal (`io.BytesIO`) y lo carga en un DataFrame de pandas.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        archivo (dict): Diccionario con claves `id` y `name` del archivo.

    Returns:
        pd.DataFrame: DataFrame crudo en formato ancho (wide), con una columna
            por cada fecha de fallecimiento registrada (1,058 columnas de fechas).
    """
    logger.info(f"Descargando: {archivo['name']}...")
    request = servicio.files().get_media(fileId=archivo["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    df = pd.read_csv(buffer, encoding="utf-8-sig")
    logger.info(f"  → {df.shape[0]:,} filas × {df.shape[1]:,} columnas leídas")
    return df


def _wide_to_long(df: pd.DataFrame) -> pd.DataFrame:
    """
    Transforma el DataFrame de formato ancho (wide) a formato largo (long/tidy).

    El CSV original del MSPAS contiene 1,063 columnas: 5 de identificación del
    municipio y 1,058 columnas de fechas (una por cada día con fallecidos). Esta
    función aplica `pd.melt()` para convertirlo a un registro por municipio-fecha,
    omitiendo las filas con cero fallecidos.

    **Antes (wide):**

    | municipio | 2020-03-15 | 2020-03-21 |
    |---|---|---|
    | GUATEMALA | 2 | 1 |

    **Después (long):**

    | municipio | fecha_fallecimiento | fallecidos |
    |---|---|---|
    | GUATEMALA | 2020-03-15 | 2 |
    | GUATEMALA | 2020-03-21 | 1 |

    Args:
        df (pd.DataFrame): DataFrame crudo en formato ancho descargado de Drive.

    Returns:
        pd.DataFrame: DataFrame en formato largo con columnas definidas en
            `COLUMNAS_ESTANDAR`. Solo incluye filas con `fallecidos > 0`.
    """
    cols_fechas = [c for c in df.columns if c[:2] in ("20", "19") and "-" in c]
    logger.info(
        f"Columnas de fechas detectadas: {len(cols_fechas)} "
        f"({cols_fechas[0]} → {cols_fechas[-1]})"
    )

    cols_id_presentes = [c for c in COLUMNAS_ID if c in df.columns]
    cols_id_faltantes = [c for c in COLUMNAS_ID if c not in df.columns]
    if cols_id_faltantes:
        logger.warning(f"Columnas ID faltantes — se imputan NULL: {cols_id_faltantes}")
        for col in cols_id_faltantes:
            df[col] = None

    df_long = df.melt(
        id_vars=cols_id_presentes,
        value_vars=cols_fechas,
        var_name="fecha_fallecimiento",
        value_name="fallecidos",
    )

    df_long["fecha_fallecimiento"]  = pd.to_datetime(df_long["fecha_fallecimiento"], errors="coerce")
    df_long["fallecidos"]           = pd.to_numeric(df_long["fallecidos"], errors="coerce").fillna(0).astype(int)
    df_long["codigo_departamento"]  = pd.to_numeric(df_long["codigo_departamento"], errors="coerce").astype("Int64")
    df_long["codigo_municipio"]     = pd.to_numeric(df_long["codigo_municipio"],    errors="coerce").astype("Int64")
    df_long["poblacion"]            = pd.to_numeric(df_long["poblacion"],           errors="coerce").astype("Int64")

    total_antes   = len(df_long)
    df_long       = df_long[df_long["fallecidos"] > 0].copy()
    total_despues = len(df_long)
    logger.info(
        f"Melt: {total_antes:,} filas brutas → {total_despues:,} con fallecidos > 0 "
        f"({total_antes - total_despues:,} con 0 omitidas)"
    )

    return df_long[COLUMNAS_ESTANDAR]


def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Inyecta metadatos de auditoría al conjunto de datos para el Sandbox.

    Args:
        df (pd.DataFrame): DataFrame con la información en formato largo.
        nombre_archivo (str): Nombre físico del archivo CSV de origen.

    Returns:
        pd.DataFrame: El mismo DataFrame incluyendo tres nuevas columnas:
            `fuente_origen`, `archivo_origen` y `fecha_carga`.
    """
    df["fuente_origen"]  = "MSPAS_COVID"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def extract_mspas_covid(ruta_credenciales: str) -> pd.DataFrame:
    """
    Función orquestadora para la extracción de fallecidos COVID-19 del MSPAS desde Google Drive.

    Ejecuta el ciclo de vida completo: autenticación, navegación al directorio
    `mortalidad-gt-fuentes/mspas/covid/`, descarga del CSV, transformación de
    formato ancho a largo (`pd.melt()`), conversión de tipos, inyección de
    trazabilidad y retorno del DataFrame final listo para el Sandbox.

    Args:
        ruta_credenciales (str): Ruta al archivo JSON con las credenciales IAM
            de la Service Account de Google Cloud.

    Returns:
        pd.DataFrame: DataFrame en formato largo (municipio × fecha) con los
            fallecidos confirmados por COVID-19, listo para el Sandbox.

    Raises:
        FileNotFoundError: Si la carpeta `mspas/covid/` en Drive no contiene el CSV.
        ValueError: Si alguna carpeta intermedia no es encontrada en Drive.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor MSPAS COVID (Google Drive / CSV)")
    logger.info("=" * 60)

    servicio = _autenticar(ruta_credenciales)

    id_raiz  = _buscar_carpeta(servicio, NOMBRE_CARPETA_RAIZ)
    id_mspas = _buscar_carpeta(servicio, NOMBRE_CARPETA_MSPAS, padre_id=id_raiz)
    id_covid = _buscar_carpeta(servicio, NOMBRE_CARPETA_COVID,  padre_id=id_mspas)

    archivo  = _buscar_csv_covid(servicio, id_covid)
    df_raw   = _descargar_csv(servicio, archivo)
    df_long  = _wide_to_long(df_raw)
    df_long  = _agregar_trazabilidad(df_long, archivo["name"])

    logger.info("-" * 60)
    logger.info("Extracción completada.")
    logger.info(f"  Total filas (municipio × fecha) : {len(df_long):,}")
    logger.info(f"  Municipios únicos               : {df_long['municipio'].nunique()}")
    logger.info(f"  Rango de fechas                 : "
                f"{df_long['fecha_fallecimiento'].min().date()} — "
                f"{df_long['fecha_fallecimiento'].max().date()}")
    logger.info(f"  Total fallecidos                : {df_long['fallecidos'].sum():,}")
    logger.info("=" * 60)

    return df_long


# Ejecución directa para pruebas
if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)
    print(f"Cargando .env desde: {env_path}")

    CREDENCIALES = os.getenv("GDRIVE_CREDENTIALS_PATH")
    if not CREDENCIALES:
        raise EnvironmentError("Variable GDRIVE_CREDENTIALS_PATH no encontrada en el .env.")

    df = extract_mspas_covid(CREDENCIALES)

    print(f"\nResumen del DataFrame:")
    print(f"  Shape       : {df.shape}")
    print(f"  Columnas    : {list(df.columns)}")
    print(f"  Municipios  : {df['municipio'].nunique()}")
    print(f"  Rango fechas: {df['fecha_fallecimiento'].min().date()} — {df['fecha_fallecimiento'].max().date()}")
    print(f"  Fallecidos  : {df['fallecidos'].sum():,}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nValores NULL por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")