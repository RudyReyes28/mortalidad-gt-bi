"""
Módulo de extracción de datos de enfermedades crónicas del MSPAS desde Google Drive.

Este script se encarga de autenticarse con la API de Google Drive, navegar por
la estructura jerárquica de carpetas del MSPAS y descargar de forma secuencial
todos los archivos `.csv` correspondientes a enfermedades crónicas (MEC) del
período 2012–2024. Además, aplica las reglas de limpieza documentadas para
normalizar las inconsistencias entre años y añade metadatos de trazabilidad.
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
logger = logging.getLogger("extractor.mspas_mec")

# Configuración
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

NOMBRE_CARPETA_RAIZ  = "mortalidad-gt-fuentes"
NOMBRE_CARPETA_MSPAS = "mspas"
NOMBRE_CARPETA_MEC   = "mec"

# Columnas canónicas objetivo en Sandbox
COLUMNAS_ESTANDAR = [
    "Año", "Departamento", "Municipio", "CIE-10",
    "Diagnóstico", "Grupo Etario", "Sexo", "Casos"
]

# Variantes de nombres de columna encontradas en los CSVs del MSPAS
RENAME_MAP = {
    "CIE 10":      "CIE-10",        # 2019: sin guión
    "GrupoEtario": "Grupo Etario",  # 2020: sin espacio
}


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


def _listar_archivos_csv(servicio, carpeta_id: str) -> list[dict]:
    """
    Lista todos los archivos CSV contenidos en una carpeta específica de Drive.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        carpeta_id (str): ID de la carpeta padre en Drive.

    Returns:
        list[dict]: Lista de diccionarios con claves `id` y `name` de cada
            archivo encontrado, ordenados alfabéticamente.

    Raises:
        FileNotFoundError: Si no se encuentran archivos CSV en la carpeta indicada.
    """
    query = (
        f"'{carpeta_id}' in parents"
        " and trashed=false"
        " and (mimeType='text/csv' or name contains '.csv')"
    )
    resultado = servicio.files().list(
        q=query, spaces="drive",
        fields="files(id, name)",
        orderBy="name",
    ).execute()

    archivos = resultado.get("files", [])
    if not archivos:
        raise FileNotFoundError("No se encontraron CSVs en mspas/mec/")

    logger.info(f"{len(archivos)} CSV(s) encontrado(s) en mspas/mec/")
    return archivos


def _descargar_csv(servicio, archivo: dict) -> pd.DataFrame:
    """
    Descarga un archivo CSV directamente desde Drive hacia la memoria RAM.

    Utiliza `MediaIoBaseDownload` para descargar el flujo binario por fragmentos
    en un búfer temporal (`io.BytesIO`) y lo carga en un DataFrame de pandas.
    Preserva los valores de texto como `"no especificada"` sin convertirlos a NaN.

    Args:
        servicio (googleapiclient.discovery.Resource): Servicio autenticado de Drive.
        archivo (dict): Diccionario con claves `id` y `name` del archivo.

    Returns:
        pd.DataFrame: DataFrame con los datos crudos extraídos del CSV.
    """
    logger.info(f"Descargando: {archivo['name']}...")
    request = servicio.files().get_media(fileId=archivo["id"])
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    df = pd.read_csv(
        buffer,
        sep=";",
        encoding="utf-8-sig",
        keep_default_na=False,  # preservar "no especificada" como string
        na_values=[],
    )
    logger.info(f"  → {len(df):,} filas leídas desde {archivo['name']}")
    return df


def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Normaliza el esquema del DataFrame aplicando las reglas de limpieza documentadas.

    Las inconsistencias del MSPAS detectadas y corregidas son:

    - **Todos los años**: headers con `\\n` embebido → se limpian con `strip()`.
    - **2013**: columna extra `Cantidad` entre `Diagnóstico` y `Grupo Etario` → se elimina.
    - **2019**: columna `CIE 10` sin guión → se renombra a `CIE-10`.
    - **2020**: columna `GrupoEtario` sin espacio → se renombra a `Grupo Etario`.

    Args:
        df (pd.DataFrame): DataFrame original extraído del CSV.
        nombre_archivo (str): Nombre del archivo procesado (para logging).

    Returns:
        pd.DataFrame: DataFrame estandarizado y ordenado según `COLUMNAS_ESTANDAR`.
    """
    # 1. Limpiar headers
    df.columns = [c.replace("\n", "").strip() for c in df.columns]

    # 2. Eliminar columna extra (2013)
    if "Cantidad" in df.columns:
        logger.info(f"[{nombre_archivo}] Columna 'Cantidad' extra eliminada (anomalía 2013)")
        df = df.drop(columns=["Cantidad"])

    # 3. Renombrar variantes
    renombradas = {k: v for k, v in RENAME_MAP.items() if k in df.columns}
    if renombradas:
        logger.info(f"[{nombre_archivo}] Columnas renombradas: {renombradas}")
        df = df.rename(columns=renombradas)

    # 4. Verificar faltantes
    faltantes = [c for c in COLUMNAS_ESTANDAR if c not in df.columns]
    if faltantes:
        logger.warning(f"[{nombre_archivo}] Columnas faltantes — se imputan NULL: {faltantes}")
        for col in faltantes:
            df[col] = None

    return df[COLUMNAS_ESTANDAR]


def _convertir_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte las columnas del DataFrame al tipo de dato correcto.

    Args:
        df (pd.DataFrame): DataFrame estandarizado con columnas canónicas.

    Returns:
        pd.DataFrame: DataFrame con tipos de dato corregidos. `Año` y `Casos`
            como enteros nullable (`Int64`); columnas de texto con vacíos
            convertidos a `None`.
    """
    df["Año"]   = pd.to_numeric(df["Año"],   errors="coerce").astype("Int64")
    df["Casos"] = pd.to_numeric(df["Casos"], errors="coerce").astype("Int64")
    for col in ["Departamento", "Municipio", "CIE-10", "Diagnóstico", "Grupo Etario", "Sexo"]:
        df[col] = df[col].replace("", None)
    return df


def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Inyecta metadatos de auditoría al conjunto de datos para el Sandbox.

    Args:
        df (pd.DataFrame): DataFrame con la información estandarizada.
        nombre_archivo (str): Nombre físico del archivo CSV de origen.

    Returns:
        pd.DataFrame: El mismo DataFrame incluyendo tres nuevas columnas:
            `fuente_origen`, `archivo_origen` y `fecha_carga`.
    """
    df["fuente_origen"]  = "MSPAS_MEC"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def extract_mspas_mec(ruta_credenciales: str) -> pd.DataFrame:
    """
    Función orquestadora para la extracción de enfermedades crónicas del MSPAS desde Google Drive.

    Ejecuta el ciclo de vida completo: autenticación, navegación al directorio
    `mortalidad-gt-fuentes/mspas/mec/`, descarga iterativa de todos los archivos
    `.csv`, aplicación de reglas de limpieza, conversión de tipos, inyección de
    trazabilidad y concatenación en un único conjunto de datos final.

    Args:
        ruta_credenciales (str): Ruta al archivo JSON con las credenciales IAM
            de la Service Account de Google Cloud.

    Returns:
        pd.DataFrame: Un único DataFrame consolidado con todos los registros
            de los 13 años procesados (2012–2024), listo para el Sandbox.

    Raises:
        FileNotFoundError: Si la carpeta `mspas/mec/` en Drive no contiene archivos CSV.
        RuntimeError: Si ocurre un fallo global que impide procesar cualquier archivo.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor MSPAS MEC (Google Drive / CSV)")
    logger.info("=" * 60)

    servicio = _autenticar(ruta_credenciales)

    id_raiz  = _buscar_carpeta(servicio, NOMBRE_CARPETA_RAIZ)
    id_mspas = _buscar_carpeta(servicio, NOMBRE_CARPETA_MSPAS, padre_id=id_raiz)
    id_mec   = _buscar_carpeta(servicio, NOMBRE_CARPETA_MEC,   padre_id=id_mspas)

    archivos = _listar_archivos_csv(servicio, id_mec)

    dataframes = []
    errores    = []

    for archivo in archivos:
        try:
            df = _descargar_csv(servicio, archivo)
            df = _estandarizar_columnas(df, archivo["name"])
            df = _convertir_tipos(df)
            df = _agregar_trazabilidad(df, archivo["name"])
            dataframes.append(df)
        except Exception as e:
            logger.error(f"Error procesando {archivo['name']}: {e}")
            errores.append(archivo["name"])

    if not dataframes:
        raise RuntimeError("Ningún CSV pudo ser procesado. Revisa los errores anteriores.")

    if errores:
        logger.warning(f"Archivos con error (no incluidos): {errores}")

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    logger.info("-" * 60)
    logger.info("Extracción completada.")
    logger.info(f"  Archivos procesados : {len(dataframes)}")
    logger.info(f"  Archivos con error  : {len(errores)}")
    logger.info(f"  Total filas         : {len(df_consolidado):,}")
    logger.info(f"  Rango de años       : {df_consolidado['Año'].min()} — {df_consolidado['Año'].max()}")
    logger.info("=" * 60)

    return df_consolidado


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

    df = extract_mspas_mec(CREDENCIALES)

    print(f"\nResumen del DataFrame consolidado:")
    print(f"  Shape    : {df.shape}")
    print(f"  Columnas : {list(df.columns)}")
    print(f"  Años     : {sorted(df['Año'].dropna().unique().tolist())}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nValores NULL por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")