"""
Fuente: SharePoint Online — Extracción Híbrida Real por Archivos Individuales (Formato Parquet)
Destino: retorna pd.DataFrame consolidado de las partes para load_sandbox.py
"""

import io
import logging
from datetime import datetime
import pandas as pd
import requests

# Importamos nuestro módulo de automatización web
from utils.auth_sp import obtener_cookies_sharepoint

logger = logging.getLogger("extractor.sharepoint")

COLUMNAS_ESTANDAR = [
    "iso3c",
    "country_name",
    "year",
    "time",
    "time_unit",
    "deaths",
]

# Definición explícita de los fragmentos actualizados a formato .parquet
FRAGMENTOS_OMS = [
    "Morticd10_part1.parquet",
    "Morticd10_part2.parquet",
    "Morticd10_part3.parquet",
    "Morticd10_part4.parquet",
    "Morticd10_part5.parquet",
    "Morticd10_part6.parquet"
]

MAPEO_COLUMNAS_OMS = {
    "Country": "iso3c",
    "Year": "year",
    "Sex": "time",
    "List": "time_unit",
    "Deaths1": "deaths"
}

def _estandarizar_columnas(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    """
    Mapea el esquema crudo de la OMS al estándar del Sandbox de destino,
    asegurando que las columnas clave contengan la data real extraída.
    """
    # 1. Aplicar el renombrado basado en las columnas reales del log
    df_mapeado = df.rename(columns=MAPEO_COLUMNAS_OMS).copy()
    
    # 2. Replicar el código numérico en la columna de nombre de país si no viene explicitamente
    if "country_name" not in df_mapeado.columns:
        df_mapeado["country_name"] = df_mapeado["iso3c"].astype(str)
        
    # 3. Forzar a que las columnas destino tengan el tipo de dato correcto antes de Postgres
    df_mapeado["iso3c"] = df_mapeado["iso3c"].astype(str)
    df_mapeado["year"] = pd.to_numeric(df_mapeado["year"], errors="coerce").fillna(0).astype(int)
    df_mapeado["deaths"] = pd.to_numeric(df_mapeado["deaths"], errors="coerce").fillna(0).astype(int)
    df_mapeado["time"] = df_mapeado["time"].astype(str)
    df_mapeado["time_unit"] = df_mapeado["time_unit"].astype(str)

    # 4. Asegurar el orden estricto de las columnas esperadas por el cargador
    return df_mapeado[COLUMNAS_ESTANDAR]

def _agregar_trazabilidad(df: pd.DataFrame, nombre_fuente: str) -> pd.DataFrame:
    df["fuente_origen"] = "SHAREPOINT_SCRAPING_HYBRID"
    df["archivo_origen"] = nombre_fuente
    df["fecha_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return df

def extract_sharepoint(site_url: str, username: str, password: str, folder_server_relative_url: str) -> pd.DataFrame:
    """
    Orquestador del extractor: Obtiene el token/cookie mediante Playwright 
    y descarga secuencialmente cada archivo de forma directa y limpia.
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor SharePoint (Descarga Binaria de Parquet)")
    logger.info("=" * 60)

    # 1. Obtener la cookie válida usando Playwright
    try:
        cookie_fresca = obtener_cookies_sharepoint(site_url)
    except Exception as e:
        raise ConnectionError(f"Fallo en la automatización del navegador al capturar tokens: {e}")

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Cookie": cookie_fresca
    }

    dataframes = []
    base_sharepoint_url = site_url.split("/sites/")[0]

    # 2. Iterar sobre cada fragmento binario .parquet esperado
    for archivo in FRAGMENTOS_OMS:
        download_url = f"{base_sharepoint_url}{folder_server_relative_url}/{archivo}?download=1"
        logger.info(f"Solicitando fragmento a la nube: {archivo}")

        try:
            respuesta = requests.get(download_url, headers=headers, allow_redirects=True, timeout=30)
            contenido = respuesta.content
            
            # Validar que Microsoft no nos esté rechazando con un HTML de error
            if contenido.startswith(b'<!DOCTYPE') or b'<html' in contenido[:200].lower():
                logger.warning(f"  ⚠ No se pudo descargar '{archivo}' directamente (El servidor retornó un HTML). Saltando...")
                continue
                
            if respuesta.status_code == 200 and len(contenido) > 0:
                # Carga limpia desde flujo binario usando el motor pyarrow bajo capó
                df_parte = pd.read_parquet(io.BytesIO(contenido))
                logger.info(f"  → ¡Éxito! {len(df_parte):,} filas leídas desde Parquet.")

                df_parte = _estandarizar_columnas(df_parte, archivo)
                df_parte = _agregar_trazabilidad(df_parte, archivo)
                dataframes.append(df_parte)
            else:
                logger.warning(f"  ⚠ El servidor respondió con código {respuesta.status_code} para el archivo {archivo}")

        except Exception as e:
            logger.error(f"  ✗ Error procesando el flujo binario del archivo {archivo}: {e}")

    # Plan de contingencia si la lista estática no recolecta nada
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

    logger.info("Consolidando todos los fragmentos Parquet recolectados...")
    df_consolidado = pd.concat(dataframes, ignore_index=True)
    
    logger.info("-" * 60)
    logger.info(f"EXTRACCIÓN HÍBRIDA COMPLETADA. Total filas unificadas: {len(df_consolidado):,}")
    logger.info("=" * 60)
    
    return df_consolidado