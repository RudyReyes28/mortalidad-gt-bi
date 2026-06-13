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

#  Columnas estandar (schema de referencia 2018-2023) 
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


# Autenticacion 
def _autenticar(ruta_credenciales: str):
    """
    Autentica con Google Drive usando una Service Account
    Retorna el servicio de Drive listo para usar


    """
    logger.info("Autenticando con Google Drive API...")
    creds = service_account.Credentials.from_service_account_file(
        ruta_credenciales, scopes=SCOPES
    )
    servicio = build("drive", "v3", credentials=creds)
    logger.info("Autenticación exitosa.")
    return servicio


#  Buscar carpeta por nombre
def _buscar_carpeta(servicio, nombre: str, padre_id: str = None) -> str:
    """
    Busca una carpeta por nombre en Drive y retorna su ID.
    Si padre_id se especifica, busca solo dentro de esa carpeta.
    Lanza ValueError si no la encuentra.
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


# Listar archivos xlsx en una carpeta 
def _listar_archivos_xlsx(servicio, carpeta_id: str) -> list[dict]:
    """
    Lista todos los archivos .xlsx dentro de la carpeta indicada.
    Retorna lista de dicts con {id, name}.
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
        orderBy="name",          # procesa en orden cronológico (2018, 2019…)
    ).execute()

    archivos = resultado.get("files", [])
    logger.info(f"{len(archivos)} archivo(s) xlsx encontrado(s) en la carpeta INE.")
    return archivos


# Descargar y leer un xlsx desde Drive ¿
def _descargar_xlsx(servicio, archivo: dict) -> pd.DataFrame:
    """
    Descarga un archivo xlsx de Drive en memoria y lo lee con pandas
    Retorna un DataFrame crudo con las columnas del archivo original
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


# Estandarizar columnas 
def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Verifica que el DataFrame tenga las columnas estandar.
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

    # Retorna siempre en el orden estandar
    return df[COLUMNAS_ESTANDAR]


# Agregar columnas de trazabilidad 
def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Agrega columnas de control para el Sandbox
        fuente_origen: identificador de la fuente
        archivo_origen: nombre del archivo xlsx descargado
        fecha_carga: timestamp de la ejecución del pipeline
    """
    df["fuente_origen"]  = "INE"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


# Funcion principal exportada
def extract_gdrive(ruta_credenciales: str) -> pd.DataFrame:
    
    logger.info("=" * 60)
    logger.info("INICIO - Extractor Google Drive (INE)")
    logger.info("=" * 60)

    servicio = _autenticar(ruta_credenciales)

    # Navegar mortalidad-gt-fuentes/ine/datos/
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