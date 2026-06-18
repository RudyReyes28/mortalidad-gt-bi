"""

Extrae el diccionario de datos del INE desde Google Drive y carga
dos tablas al Sandbox:
    - sandbox.sandbox_ine_diccionario  : variables y sus códigos
    - sandbox.sandbox_ine_cie10        : códigos CIE-10 y descripciones

Hoja 1 "Defunciones":
    Columnas : Valor (celdas combinadas) | Código | Etiqueta
    Resultado: una fila por código con la variable propagada

Hoja 2 "CIE-10":
    Columnas : Código CIE-10 | Descripción
    Resultado: tabla directa sin transformación especial

"""

import io
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from sqlalchemy import create_engine, text
import os

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.diccionario_ine")

# Configuración 
SCOPES               = ["https://www.googleapis.com/auth/drive.readonly"]
NOMBRE_CARPETA_RAIZ  = "mortalidad-gt-fuentes"
NOMBRE_CARPETA_INE   = "ine"
NOMBRE_CARPETA_DICC  = "diccionario"
NOMBRE_ARCHIVO       = "diccionario-defunciones.xlsx"

TABLA_DICCIONARIO    = "sandbox_ine_diccionario"
TABLA_CIE10          = "sandbox_ine_cie10"
SCHEMA               = "sandbox"


# ── Autenticación Drive ───────────────────────────────────────────────────────
def _autenticar(ruta_credenciales: str):
    logger.info("Autenticando con Google Drive API...")
    creds = service_account.Credentials.from_service_account_file(
        ruta_credenciales, scopes=SCOPES
    )
    servicio = build("drive", "v3", credentials=creds)
    logger.info("Autenticación exitosa.")
    return servicio


# Buscar carpeta por nombre
def _buscar_carpeta(servicio, nombre: str, padre_id: str = None) -> str:
    query = (
        f"name='{nombre}'"
        " and mimeType='application/vnd.google-apps.folder'"
        " and trashed=false"
    )
    if padre_id:
        query += f" and '{padre_id}' in parents"

    resultado = servicio.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()

    carpetas = resultado.get("files", [])
    if not carpetas:
        raise ValueError(f"Carpeta '{nombre}' no encontrada en Drive.")

    logger.info(f"Carpeta '{nombre}' encontrada. ID: {carpetas[0]['id']}")
    return carpetas[0]["id"]


# Buscar archivo por nombre
def _buscar_archivo(servicio, nombre: str, carpeta_id: str) -> str:
    query = (
        f"name='{nombre}'"
        f" and '{carpeta_id}' in parents"
        " and trashed=false"
    )
    resultado = servicio.files().list(
        q=query, spaces="drive", fields="files(id, name)"
    ).execute()

    archivos = resultado.get("files", [])
    if not archivos:
        raise FileNotFoundError(
            f"Archivo '{nombre}' no encontrado en la carpeta diccionario/."
        )

    logger.info(f"Archivo '{nombre}' encontrado. ID: {archivos[0]['id']}")
    return archivos[0]["id"]


# Descargar archivo desde Drive 
def _descargar_archivo(servicio, file_id: str) -> io.BytesIO:
    logger.info("Descargando diccionario...")
    request = servicio.files().get_media(fileId=file_id)
    buffer  = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    buffer.seek(0)
    logger.info("Descarga completada.")
    return buffer


#  Procesar hoja Defunciones 
def _procesar_hoja_defunciones(buffer: io.BytesIO) -> pd.DataFrame:
    """
    Lee la hoja 'Defunciones' del diccionario y normaliza las celdas
    combinadas de la columna 'Valor' usando forward fill.

    Las celdas combinadas en pandas quedan como NaN en las filas
    siguientes a la primera — ffill propaga el valor hacia abajo.
    """
    logger.info("Procesando hoja 'Defunciones'...")

    buffer.seek(0)
    df = pd.read_excel(
        buffer,
        sheet_name="Defunciones",
        engine="openpyxl",
        header=1,           # primera fila es encabezado
    )

    # Renombrar columnas al formato estándar
    df.columns = ["variable", "codigo", "etiqueta"]

    # Eliminar filas completamente vacías
    df = df.dropna(how="all")

    # Forward fill en la columna variable — propaga el nombre de la variable
    # a todas las filas que pertenecen a ese grupo
    df["variable"] = df["variable"].ffill()

    # Eliminar filas donde código y etiqueta son NaN
    # (son las filas del encabezado de cada grupo de variable)
    df = df.dropna(subset=["codigo", "etiqueta"])

    # Limpiar tipos
    df["variable"] = df["variable"].astype(str).str.strip()
    df["codigo"]   = df["codigo"].astype(str).str.strip()
    df["etiqueta"] = df["etiqueta"].astype(str).str.strip()

    # Agregar trazabilidad
    df["fuente_origen"]  = "INE_DICCIONARIO"
    df["archivo_origen"] = NOMBRE_ARCHIVO
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"  → {len(df):,} códigos procesados en hoja Defunciones")
    logger.info(f"  → Variables encontradas: {df['variable'].unique().tolist()}")

    return df


# Procesar hoja CIE-10 
def _procesar_hoja_cie10(buffer: io.BytesIO) -> pd.DataFrame:
    """
    Lee la hoja 'CIE-10' del diccionario.
    Estructura simple: Código CIE-10 | Descripción
    """
    logger.info("Procesando hoja 'CIE-10'...")

    buffer.seek(0)
    df = pd.read_excel(
        buffer,
        sheet_name="CIE-10",
        engine="openpyxl",
        header=1,
    )

    # Renombrar columnas
    df.columns = ["codigo_cie10", "descripcion"]

    # Limpiar
    df = df.dropna(how="all")
    df = df.dropna(subset=["codigo_cie10"])
    df["codigo_cie10"] = df["codigo_cie10"].astype(str).str.strip().str.upper()
    df["descripcion"]  = df["descripcion"].astype(str).str.strip()

    # Trazabilidad
    df["fuente_origen"]  = "INE_DICCIONARIO_CIE10"
    df["archivo_origen"] = NOMBRE_ARCHIVO
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    logger.info(f"  → {len(df):,} códigos CIE-10 procesados")

    return df


# Cargar al Sandbox 
def _cargar_sandbox(df: pd.DataFrame, tabla: str, db_url: str):
    """Carga el DataFrame al Sandbox usando replace para evitar duplicados."""
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS sandbox"))
        conn.commit()

    df.to_sql(
        name=tabla,
        con=engine,
        schema=SCHEMA,
        if_exists="replace",
        index=False,
        chunksize=1000,
        method="multi",
    )

    logger.info(f"  → {len(df):,} filas cargadas en {SCHEMA}.{tabla}")
    engine.dispose()


# Función principal
def extract_diccionario_ine(ruta_credenciales: str, db_url: str):
    """
    Extrae el diccionario del INE desde Google Drive y carga
    dos tablas al Sandbox: sandbox_ine_diccionario y sandbox_ine_cie10.

    Args:
        ruta_credenciales: Ruta al JSON de la Service Account de Google.
        db_url: Cadena de conexión al Sandbox PostgreSQL.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor Diccionario INE")
    logger.info("=" * 60)

    # Descargar archivo desde Drive 
    servicio  = _autenticar(ruta_credenciales)
    id_raiz   = _buscar_carpeta(servicio, NOMBRE_CARPETA_RAIZ)
    id_ine    = _buscar_carpeta(servicio, NOMBRE_CARPETA_INE,  padre_id=id_raiz)
    id_dicc   = _buscar_carpeta(servicio, NOMBRE_CARPETA_DICC, padre_id=id_ine)
    id_archivo = _buscar_archivo(servicio, NOMBRE_ARCHIVO, id_dicc)
    buffer    = _descargar_archivo(servicio, id_archivo)

    # Procesar hoja Defunciones 
    df_diccionario = _procesar_hoja_defunciones(buffer)
    logger.info(f"\nEjemplo de datos procesados:")
    logger.info(f"\n{df_diccionario.head(8).to_string()}")

    # Procesar hoja CIE-10 
    df_cie10 = _procesar_hoja_cie10(buffer)

    # Cargar ambas tablas al Sandbox
    logger.info("\nCargando al Sandbox...")
    _cargar_sandbox(df_diccionario, TABLA_DICCIONARIO, db_url)
    _cargar_sandbox(df_cie10,       TABLA_CIE10,       db_url)

    logger.info("-" * 60)
    logger.info("Diccionario INE cargado exitosamente.")
    logger.info(f"  sandbox.{TABLA_DICCIONARIO} : {len(df_diccionario):,} filas")
    logger.info(f"  sandbox.{TABLA_CIE10}       : {len(df_cie10):,} filas")
    logger.info("=" * 60)

    return df_diccionario, df_cie10


# Ejecución directa 
if __name__ == "__main__":
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)

    CREDENCIALES = os.getenv("GDRIVE_CREDENTIALS_PATH")
    DB_URL       = os.getenv("SANDBOX_DB_URL")

    if not CREDENCIALES or not DB_URL:
        raise EnvironmentError(
            "Faltan variables en .env: GDRIVE_CREDENTIALS_PATH o SANDBOX_DB_URL"
        )

    df_dicc, df_cie10 = extract_diccionario_ine(CREDENCIALES, DB_URL)

    print(f"\n── Diccionario variables ──")
    print(f"Shape    : {df_dicc.shape}")
    print(f"Variables: {df_dicc['variable'].nunique()}")
    print(df_dicc.head(10).to_string())

    print(f"\n── CIE-10 ──")
    print(f"Shape    : {df_cie10.shape}")
    print(df_cie10.head(5).to_string())