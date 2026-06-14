"""
Módulo de extracción de datos de mortalidad desde Google Drive.

Este script se encarga de autenticarse con la API de Google Drive, navegar por 
la estructura jerárquica de carpetas del INE y descargar de forma secuencial 
todos los archivos `.xlsx` correspondientes a las defunciones. Además, estandariza 
las columnas y añade metadatos de trazabilidad.
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
logger = logging.getLogger("extractor.gdrive")

# Columnas estandar (schema de referencia 2018-2023) 
COLUMNAS_ESTANDAR = [
    "Depreg", "Mupreg", "Mesreg", "Añoreg",
    "Depocu", "Mupocu", "Sexo",
    "Diaocu", "Mesocu", "Añoocu",
    "Edadif", "Perdif", "Puedif", "Ecidif",
    "Escodif", "Ciuodif",                   # ausentes en 2024 
    "Pnadif", "Dnadif", "Mnadif", "Nacdif",
    "Predif", "Dredif", "Mredif",
    "Caudef", "Asist", "Ocur", "Cerdef",
]

# Configuracion 
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
NOMBRE_CARPETA_RAIZ= "mortalidad-gt-fuentes"
NOMBRE_CARPETA_INE = "ine"
NOMBRE_CARPETA_DATOS= "datos"          


def _autenticar(ruta_credenciales: str):
    """
    Autentica con la API de Google Drive utilizando una Service Account.

    Args:
        ruta_credenciales (str): Ruta absoluta o relativa al archivo JSON que 
            contiene las credenciales de la cuenta de servicio de Google Cloud.

    Returns:
        googleapiclient.discovery.Resource: Objeto de servicio construido listo 
            para interactuar con la API de Google Drive (versión v3).
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
    y verificando que no esté en la papelera. Opcionalmente, restringe la 
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
        q=query,
        spaces="drive",
        fields="files(id, name)",
    ).execute()

    carpetas = resultado.get("files", [])
    if not carpetas:
        raise ValueError(f"Carpeta '{nombre}' no encontrada en Drive.")

    carpeta_id = carpetas[0]["id"]
    logger.info(f"Carpeta '{nombre}' encontrada. ID: {carpeta_id}")
    return carpeta_id


def _listar_archivos_xlsx(servicio, carpeta_id: str) -> list[dict]:
    """
    Lista todos los archivos de Excel (.xlsx) contenidos en una carpeta específica.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        carpeta_id (str): ID de la carpeta padre en Drive.

    Returns:
        list[dict]: Lista de diccionarios, donde cada diccionario contiene las claves 
            `id` (str) y `name` (str) de los archivos encontrados, ordenados 
            alfabéticamente/cronológicamente.
    """
    query = (
        f"'{carpeta_id}' in parents"
        " and trashed=false"
        " and ("
        "   mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'"
        "   or name contains '.xlsx'"
        ")"
    )
    resultado = servicio.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        orderBy="name",          
    ).execute()

    archivos = resultado.get("files", [])
    logger.info(f"{len(archivos)} archivo(s) xlsx encontrado(s) en la carpeta INE.")
    return archivos


def _descargar_xlsx(servicio, archivo: dict) -> pd.DataFrame:
    """
    Descarga un archivo Excel directamente desde Drive hacia la memoria RAM.

    Utiliza `MediaIoBaseDownload` para descargar el flujo binario por fragmentos 
    (chunks) en un búfer temporal (`io.BytesIO`) y luego lo carga en un DataFrame 
    de pandas utilizando el motor `openpyxl`.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        archivo (dict): Diccionario representativo del archivo con claves `id` y `name`.

    Returns:
        pd.DataFrame: DataFrame con los datos crudos extraídos del archivo Excel.
    """
    logger.info(f"Descargando: {archivo['name']}...")
    request = servicio.files().get_media(fileId=archivo["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    df = pd.read_excel(buffer, engine="openpyxl")
    logger.info(f"  → {len(df):,} filas leídas desde {archivo['name']}")
    return df


def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Normaliza el esquema del DataFrame alineándolo al estándar del proyecto.

    Verifica la existencia de todas las columnas esperadas. Si faltan columnas 
    (como ocurre en los registros de 2024), las crea e imputa con valores NULL. 
    Posteriormente, reordena el DataFrame al esquema oficial.

    Args:
        df (pd.DataFrame): DataFrame original extraído del archivo.
        nombre_archivo (str): Nombre del archivo procesado (para fines de logging).

    Returns:
        pd.DataFrame: DataFrame estandarizado y ordenado según `COLUMNAS_ESTANDAR`.
    """
    columnas_actuales = set(df.columns)
    columnas_esperadas = set(COLUMNAS_ESTANDAR)

    faltantes = columnas_esperadas - columnas_actuales
    extras    = columnas_actuales - columnas_esperadas

    if faltantes:
        logger.warning(
            f"[{nombre_archivo}] Columnas faltantes - se imputaran NULL: {sorted(faltantes)}"
        )
        for col in faltantes:
            df[col] = None

    if extras:
        logger.info(
            f"[{nombre_archivo}] Columnas extra (no en schema estandar): {sorted(extras)}"
        )

    return df[COLUMNAS_ESTANDAR]


def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Inyecta metadatos de auditoría al conjunto de datos para el Sandbox.

    Args:
        df (pd.DataFrame): DataFrame con la información estandarizada.
        nombre_archivo (str): Nombre físico del archivo de origen.

    Returns:
        pd.DataFrame: El mismo DataFrame incluyendo tres nuevas columnas: 
            `fuente_origen`, `archivo_origen`, y `fecha_carga`.
    """
    df["fuente_origen"]  = "INE"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def extract_gdrive(ruta_credenciales: str) -> pd.DataFrame:
    """
    Función orquestadora para la extracción de defunciones del INE desde Google Drive.

    Ejecuta el ciclo de vida completo: autenticación, navegación al directorio 
    `mortalidad-gt-fuentes/ine/datos/`, descarga iterativa de todos los archivos 
    `.xlsx`, estandarización de sus columnas, inyección de trazabilidad y 
    concatenación en un único conjunto de datos final.

    Args:
        ruta_credenciales (str): Ruta al archivo JSON con las credenciales IAM.

    Returns:
        pd.DataFrame: Un único DataFrame consolidado con todas las filas de 
            los archivos analizados.

    Raises:
        FileNotFoundError: Si la carpeta objetivo en Drive no contiene archivos.
        RuntimeError: Si ocurre un fallo global que impide procesar cualquier archivo.
    """
    logger.info("=" * 60)
    logger.info("INICIO - Extractor Google Drive (INE)")
    logger.info("=" * 60)

    servicio = _autenticar(ruta_credenciales)

    id_raiz= _buscar_carpeta(servicio, NOMBRE_CARPETA_RAIZ)
    id_ine = _buscar_carpeta(servicio, NOMBRE_CARPETA_INE,   padre_id=id_raiz)
    id_datos = _buscar_carpeta(servicio, NOMBRE_CARPETA_DATOS, padre_id=id_ine)

    archivos = _listar_archivos_xlsx(servicio, id_datos)

    if not archivos:
        logger.error("No se encontraron archivos xlsx en la carpeta datos/. Abortando.")
        raise FileNotFoundError("Carpeta ine/datos/ vacia en Google Drive.")

    dataframes = []
    errores    = []

    for archivo in archivos:
        try:
            df = _descargar_xlsx(servicio, archivo)
            df = _estandarizar_columnas(df, archivo["name"])
            df = _agregar_trazabilidad(df, archivo["name"])
            dataframes.append(df)
        except Exception as e:
            logger.error(f"Error procesando {archivo['name']}: {e}")
            errores.append(archivo["name"])

    if not dataframes:
        raise RuntimeError("Ningún archivo pudo ser procesado. Revisa los errores anteriores.")

    if errores:
        logger.warning(f"Archivos con error (no incluidos): {errores}")

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    logger.info("-" * 60)
    logger.info(f"Extraccion completada.")
    logger.info(f" Archivos procesados: {len(dataframes)}")
    logger.info(f" Archivos con error : {len(errores)}")
    logger.info(f" Total filas  : {len(df_consolidado):,}")
    logger.info(f" Columnas : {list(df_consolidado.columns)}")
    logger.info("=" * 60)

    return df_consolidado

# Ejecucion para pruebas
if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)
    print(f"Cargando .env desde: {env_path}")

    CREDENCIALES = os.getenv("GDRIVE_CREDENTIALS_PATH")
    if not CREDENCIALES:
        raise EnvironmentError(
            "Variable GDRIVE_CREDENTIALS_PATH no encontrada en el .env. "
            f"Verifica que el archivo .env esté en: {env_path}"
        )

    print(f"Usando credenciales: {CREDENCIALES}")

    df = extract_gdrive(CREDENCIALES)
    print(f"\nResumen del DataFrame consolidado:")
    print(f"  Shape   : {df.shape}")
    print(f"  Columnas: {list(df.columns)}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nValores NULL por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")