"""
Extractor MSPAS — Enfermedades Crónicas (MEC) 2012–2024
Fuente  : Google Drive → mortalidad-gt-fuentes/mspas/mec/  se muestran los 13 csv puros con datos de mortalidad por enfermedades crónicas del MSPAS.
Formato  : CSV con separador ';' y codificación UTF-8 (con BOM)
Columnas : Año, Departamento, Municipio, CIE-10, Diagnóstico, Grupo Etario, Sexo, Casos

Reglas de limpieza aplicadas (inconsistencias documentadas del MSPAS):
  - Todos los años : headers con \\n embebido → se limpian
  - 2013           : columna extra "Cantidad" entre Diagnóstico y Grupo Etario → se elimina
  - 2019           : "CIE 10" sin guión → se renombra a "CIE-10"
  - 2020           : "GrupoEtario" sin espacio → se renombra a "Grupo Etario"
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


# Autenticacion
def _autenticar(ruta_credenciales: str):
    """Autentica con Google Drive API. Retorna el servicio listo para usar."""
    logger.info("Autenticando con Google Drive API...")
    creds = service_account.Credentials.from_service_account_file(
        ruta_credenciales, scopes=SCOPES
    )
    servicio = build("drive", "v3", credentials=creds)
    logger.info("Autenticación exitosa.")
    return servicio


# Buscar carpeta por nombre
def _buscar_carpeta(servicio, nombre: str, padre_id: str = None) -> str:
    """Busca una carpeta por nombre en Drive y retorna su ID."""
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


# Listar CSVs en una carpeta
def _listar_archivos_csv(servicio, carpeta_id: str) -> list[dict]:
    """Lista todos los archivos .csv dentro de la carpeta indicada."""
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


# Descargar CSV desde Drive en memoria
def _descargar_csv(servicio, archivo: dict) -> pd.DataFrame:
    """Descarga un CSV de Drive en memoria y lo lee con pandas."""
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


# Limpiar y estandarizar columnas
def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Aplica las correcciones documentadas de inconsistencias del MSPAS:
      1. Limpia \\n y espacios en nombres de columna (2013, 2024)
      2. Elimina columna extra 'Cantidad' (2013)
      3. Renombra variantes al nombre canónico (2019, 2020)
      4. Imputa NULL en columnas faltantes con WARNING
    Retorna siempre en el orden de COLUMNAS_ESTANDAR.
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


# Convertir tipos
def _convertir_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas al tipo correcto."""
    df["Año"]   = pd.to_numeric(df["Año"],   errors="coerce").astype("Int64")
    df["Casos"] = pd.to_numeric(df["Casos"], errors="coerce").astype("Int64")
    for col in ["Departamento", "Municipio", "CIE-10", "Diagnóstico", "Grupo Etario", "Sexo"]:
        df[col] = df[col].replace("", None)
    return df


# Agregar columnas de trazabilidad
def _agregar_trazabilidad(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """Agrega columnas de control para el Sandbox."""
    df["fuente_origen"]  = "MSPAS_MEC"
    df["archivo_origen"] = nombre_archivo
    df["fecha_carga"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


# Función principal exportada
def extract_mspas_mec(ruta_credenciales: str) -> pd.DataFrame:
    """
    Punto de entrada del extractor MSPAS MEC.
    Navega: mortalidad-gt-fuentes → mspas → mec → descarga todos los CSVs.

    Retorna:
        pd.DataFrame consolidado con todos los años, listo para el Sandbox.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor MSPAS MEC (Google Drive / CSV)")
    logger.info("=" * 60)

    servicio = _autenticar(ruta_credenciales)

    # Navegar mortalidad-gt-fuentes/mspas/mec/
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