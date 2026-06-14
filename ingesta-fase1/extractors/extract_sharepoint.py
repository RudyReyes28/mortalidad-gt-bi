"""
Módulo de extracción de datos de mortalidad de la OMS desde SharePoint Online.

Este script automatiza la descarga híbrida y segura de fragmentos binarios en 
formato Apache Parquet, gestionando el bypass de autenticación corporativa (MFA) 
con Playwright, procesando la data directamente en memoria RAM (sin almacenamiento 
temporal en disco) y estandarizando el layout al esquema del Sandbox.
"""

import io
import logging
from datetime import datetime
import pandas as pd
import requests

# Importamos nuestro módulo de automatización web encargado del bypass MFA
from utils.auth_sp import obtener_cookies_sharepoint

# Configuración del logging uniforme para el pipeline
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.sharepoint")

# Columnas estándar requeridas por el cargador final en el Sandbox de destino
COLUMNAS_ESTANDAR = [
    "iso3c",
    "country_name",
    "year",
    "time",
    "time_unit",
    "deaths",
]

# Lista estática de fragmentos optimizados y particionados por volumen en SharePoint
FRAGMENTOS_OMS = [
    "Morticd10_part1.parquet",
    "Morticd10_part2.parquet",
    "Morticd10_part3.parquet",
    "Morticd10_part4.parquet",
    "Morticd10_part5.parquet",
    "Morticd10_part6.parquet"
]

# Mapeo oficial desde el esquema crudo ICD-10 de la OMS hacia columnas del Sandbox
MAPEO_COLUMNAS_OMS = {
    "Country": "iso3c",
    "Year": "year",
    "Sex": "time",
    "List": "time_unit",
    "Deaths1": "deaths"
}


def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Mapea el esquema crudo de la OMS al estándar del Sandbox de destino.

    Aplica el renombrado de columnas, inicializa la columna de control geográfico 
    replicando el identificador base, sanitiza valores nulos mediante coerción 
    numérica y fuerza los tipos de datos compatibles con la persistencia en PostgreSQL.

    Args:
        df (pd.DataFrame): DataFrame original extraído de la partición binaria.
        nombre_archivo (str): Nombre físico de la partición en proceso (para logs).

    Returns:
        pd.DataFrame: DataFrame normalizado, tipado y ordenado según `COLUMNAS_ESTANDAR`.
    """
    # 1. Aplicar el renombrado basado en las columnas reales del layout OMS
    df_mapeado = df.rename(columns=MAPEO_COLUMNAS_OMS).copy()
    
    # 2. Replicar el código numérico en la columna de nombre de país para homologación en Fase 2
    if "country_name" not in df_mapeado.columns:
        df_mapeado["country_name"] = df_mapeado["iso3c"].astype(str)
        
    # 3. Forzar tipado estricto y sanitización de nulos antes de Postgres
    df_mapeado["iso3c"] = df_mapeado["iso3c"].astype(str)
    df_mapeado["year"] = pd.to_numeric(df_mapeado["year"], errors="coerce").fillna(0).astype(int)
    df_mapeado["deaths"] = pd.to_numeric(df_mapeado["deaths"], errors="coerce").fillna(0).astype(int)
    df_mapeado["time"] = df_mapeado["time"].astype(str)
    df_mapeado["time_unit"] = df_mapeado["time_unit"].astype(str)

    # 4. Asegurar el orden y estructura exacta de las columnas destino
    return df_mapeado[COLUMNAS_ESTANDAR]


def _agregar_trazabilidad(df: pd.DataFrame, nombre_fuente: str) -> pd.DataFrame:
    """
    Inyecta metadatos de auditoría y linaje de datos al conjunto extraído.

    Args:
        df (pd.DataFrame): DataFrame con la información estandarizada.
        nombre_fuente (str): Nombre físico de la partición de origen en SharePoint.

    Returns:
        pd.DataFrame: El mismo DataFrame incluyendo columnas de trazabilidad:
            `fuente_origen`, `archivo_origen`, y `fecha_carga`.
    """
    df["fuente_origen"] = "SHAREPOINT_SCRAPING_HYBRID"
    df["archivo_origen"] = nombre_fuente
    df["fecha_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df


def extract_sharepoint(
    site_url: str, 
    username: str, 
    password: str, 
    folder_server_relative_url: str
) -> pd.DataFrame:
    """
    Orquestador principal para la extracción híbrida del dataset de la OMS en SharePoint.

    Coordina el ciclo de vida de extracción: solicita el bypass de autenticación web 
    con Playwright para capturar las cookies de sesión activa, calcula las URLs relativas 
    de descarga de Microsoft 365, descarga iterativamente cada fragmento Parquet en caliente 
    hacia la memoria RAM, invoca los submódulos de estandarización y consolida un DataFrame unificado.

    Args:
        site_url (str): URL base del sitio institucional de SharePoint (ej. https://.../sites/OMS_RAW).
        username (str): Correo institucional / Cuenta de servicio para la autenticación.
        password (str): Contraseña asociada a las credenciales de acceso.
        folder_server_relative_url (str): Ruta interna relativa de la carpeta contenedora.

    Returns:
        pd.DataFrame: Conjunto de datos consolidado con las filas unificadas de todas las partes.

    Raises:
        ConnectionError: Si el navegador automatizado falla al interceptar las credenciales/cookies.
        ValueError: Si Microsoft deniega el flujo binario y retorna páginas HTML de error en su lugar.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor SharePoint (Descarga Binaria de Parquet)")
    logger.info("=" * 60)

    # 1. Obtener la cookie válida del portal web usando Playwright (Evade MFA persistente)
    try:
        cookie_fresca = obtener_cookies_sharepoint(site_url)
    except Exception as e:
        raise ConnectionError(f"Fallo en la automatización del navegador al capturar tokens: {e}")

    # Cabeceras de simulación para asegurar la aceptación del flujo binario
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_fresca
    }

    dataframes = []
    base_sharepoint_url = site_url.split("/sites/")[0]

    # 2. Iterar de forma secuencial sobre cada fragmento binario .parquet esperado
    for archivo in FRAGMENTOS_OMS:
        download_url = f"{base_sharepoint_url}{folder_server_relative_url}/{archivo}?download=1"
        logger.info(f"Solicitando fragmento a la nube: {archivo}")

        try:
            # Petición HTTP directa por flujo de bytes para evitar bloqueos
            respuesta = requests.get(download_url, headers=headers, allow_redirects=True, timeout=30)
            contenido = respuesta.content
            
            # Validación de Seguridad: Evitar falsos positivos si Microsoft retorna un formulario HTML de login
            if contenido.startswith(b'<!DOCTYPE') or b'<html' in contenido[:200].lower():
                logger.warning(f"  ⚠ No se pudo descargar '{archivo}' directamente (El servidor retornó un HTML). Saltando...")
                continue
                
            if respuesta.status_code == 200 and len(contenido) > 0:
                # Lectura eficiente en RAM usando io.BytesIO con procesamiento columnar pyarrow bajo el capó
                df_parte = pd.read_parquet(io.BytesIO(contenido))
                logger.info(f"  → ¡Éxito! {len(df_parte):,} filas leídas desde Parquet.")

                # Transformación e inyección en caliente
                df_parte = _estandarizar_columnas(df_parte, archivo)
                df_parte = _agregar_trazabilidad(df_parte, archivo)
                dataframes.append(df_parte)
            else:
                logger.warning(f"  ⚠ El servidor respondió con código {respuesta.status_code} para el archivo {archivo}")

        except Exception as e:
            logger.error(f"  ✗ Error procesando el flujo binario del archivo {archivo}: {e}")

    # 3. Plan de contingencia si la lista estática es rechazada o bloqueada por completo
    if not dataframes:
        logger.warning("No se encontraron archivos con la lista estática Parquet. Verificando endpoint...")
        download_url_carpeta = f"{base_sharepoint_url}{folder_server_relative_url}?download=1"
        respuesta = requests.get(download_url_carpeta, headers=headers, allow_redirects=True, timeout=45)
        
        if respuesta.content.startswith(b'<!DOCTYPE') or b'<html' in respuesta.content[:200].lower():
            texto_error = respuesta.content[:300].decode('utf-8', errors='ignore')
            raise ValueError(
                f"Microsoft denegó la descarga del flujo. El servidor respondió con una página web.\n"
                f"Muestra de la respuesta: {texto_error}"
            )

    # 4. Consolidar e integrar todas las piezas del dataset leídas en RAM
    logger.info("Consolidando todos los fragmentos Parquet recolectados...")
    df_consolidado = pd.concat(dataframes, ignore_index=True)
    
    logger.info("-" * 60)
    logger.info(f"EXTRACCIÓN HÍBRIDA COMPLETADA. Total filas unificadas: {len(df_consolidado):,}")
    logger.info("=" * 60)
    
    return df_consolidado