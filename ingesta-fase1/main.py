"""
Orquestador principal del pipeline de ingesta Fase 1.

Ejecuta todos los extractores en secuencia y carga cada resultado al Sandbox 
de PostgreSQL. Funciona como el punto de entrada (Entry Point) de la aplicación, 
gestionando dependencias de entorno, orquestación de funciones, captura de errores 
y generación de trazas de auditoría (Data Lineage).
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto o subcarpeta actual
ENV_RAIZ = Path(__file__).resolve().parents[1] / ".env"
ENV_LOCAL = Path(__file__).resolve().parent / ".env"

if ENV_LOCAL.exists():
    load_dotenv(ENV_LOCAL)
elif ENV_RAIZ.exists():
    load_dotenv(ENV_RAIZ)
else:
    load_dotenv() # Carga por defecto del sistema
    
# Logging estructurado 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pipeline.main")

# Paths
RAIZ  = Path(__file__).resolve().parent
EXTRACTORS= RAIZ / "extractors"
LOADERS = RAIZ / "loaders"
REPORTES = RAIZ / "reportes"

sys.path.insert(0, str(EXTRACTORS))
sys.path.insert(0, str(LOADERS))

# Importar modulos del pipeline 
from extractors.extract_gdrive import extract_gdrive
from extractors.extract_world_mortality_s3 import extract_world_mortality_s3
from extractors.extract_sharepoint import extract_sharepoint 
from extractors.extract_mspas_mec import extract_mspas_mec
from extractors.extract_mspas_covid import extract_mspas_covid
from extractors.extract_centroamerica_rds import extract_rds

from loaders.load_sandbox import load_sandbox


def _cargar_config() -> dict:
    """
    Lee y valida las variables de entorno necesarias para las fuentes activas.

    Returns:
        dict: Diccionario que contiene las credenciales y rutas obtenidas 
            del sistema o del archivo `.env`.

    Raises:
        EnvironmentError: Si falta alguna variable de entorno declarada como 
            obligatoria para la ejecución del pipeline.
    """
    config = {
        "gdrive_credentials": os.getenv("GDRIVE_CREDENTIALS_PATH"),
        "sandbox_url": os.getenv("SANDBOX_DB_URL"),
        "aws_access_key": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "s3_bucket": os.getenv("S3_BUCKET_NAME"),
        "s3_prefix": os.getenv("S3_PREFIX", "raw/centroamerica/"),
         "sp_url":  os.getenv("SHAREPOINT_URL"),
         "sp_user": os.getenv("SHAREPOINT_USER"),
         "sp_password": os.getenv("SHAREPOINT_PASSWORD"),
         "sp_folder": os.getenv("SHAREPOINT_FOLDER"),
        "rds_url": os.getenv("RDS_SOURCE_URL"),
    }

    obligatorias = {
        "sandbox_url": "SANDBOX_DB_URL",
        "sp_url": "SHAREPOINT_URL",
        "sp_user": "SHAREPOINT_USER",
        "sp_password": "SHAREPOINT_PASSWORD",
        "sp_folder": "SHAREPOINT_FOLDER",
        "gdrive_credentials": "GDRIVE_CREDENTIALS_PATH",
    }
    
    faltantes = [var for key, var in obligatorias.items() if not config[key]]
    if faltantes:
        raise EnvironmentError(
            f"Variables de entorno faltantes en .env: {faltantes}\n"
            f"Revisa el archivo .env.example para ver qué se necesita."
        )

    return config


def _construir_fuentes(config: dict) -> dict:
    """
    Registra cada fuente del proyecto junto a su módulo extractor y parámetros.

    Args:
        config (dict): Diccionario con las variables de configuración ya validadas.

    Returns:
        dict: Un diccionario anidado donde la clave es el identificador de la 
            fuente (ej. 'ine', 'world_mortality') y el valor contiene la descripción, 
            el puntero a la función extractora y sus argumentos (kwargs).
    """
    fuentes = {}

    fuentes["ine"] = {
        "descripcion": "INE — Estadísticas vitales de defunciones (Google Drive)",
        "extractor": extract_gdrive,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    fuentes["world_mortality"] = {
        "descripcion": "World Mortality Dataset (AWS S3)",
        "extractor": extract_world_mortality_s3,
        "kwargs": {
            "bucket": config["s3_bucket"],
            "prefix": config["s3_prefix"],
            "aws_key": config["aws_access_key"],
            "aws_secret": config["aws_secret_key"],
            "region": config["aws_region"],
        },
    }

    fuentes["oms"] = {
        "descripcion": "OMS / MSPAS (SharePoint)",
        "extractor": extract_sharepoint,
        "kwargs": {
            "site_url": config["sp_url"],
            "username": config["sp_user"],
            "password": config["sp_password"],
            "folder_server_relative_url": config["sp_folder"],
        },
    }

    fuentes["mspas_mec"] = {
        "descripcion": "MSPAS — Enfermedades Crónicas MEC 2012-2024 (Google Drive / CSV)",
        "extractor": extract_mspas_mec,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    fuentes["mspas_covid"] = {
        "descripcion": "MSPAS — Fallecidos COVID-19 por municipio 2020-2024 (Google Drive / CSV)",
        "extractor": extract_mspas_covid,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    fuentes["centroamerica"] = {
         "descripcion": "Fuente adicional (RDS relacional)",
         "extractor": extract_rds,
         "kwargs": {"db_url": config["rds_url"]},
     }

    return fuentes


def _guardar_reporte(reporte_global: dict) -> Path:
    """
    Vuelca el reporte de ejecución estructurado en un archivo JSON local.

    Genera un registro histórico que actúa como evidencia de Data Lineage, 
    detallando qué fuentes se corrieron, el volumen de datos extraídos, 
    y cualquier error encontrado.

    Args:
        reporte_global (dict): Diccionario maestro que agrupa los resultados 
            individuales de cada tabla cargada.

    Returns:
        Path: Ruta absoluta del archivo JSON generado.
    """
    REPORTES.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = REPORTES / f"ejecucion_{timestamp}.json"

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(reporte_global, f, indent=2, ensure_ascii=False)

    logger.info(f"Reporte guardado en: {ruta}")
    return ruta


def run_pipeline(fuentes_a_correr: list = None):
    """
    Ejecuta el ciclo de vida completo del pipeline de extracción y carga.

    Itera sobre las fuentes configuradas, dispara sus respectivos extractores, 
    pasa el DataFrame resultante a `load_sandbox` y compila un reporte global.

    Args:
        fuentes_a_correr (list, optional): Lista de identificadores de las 
            fuentes específicas a ejecutar. Si se envía `None`, procesa todas 
            las fuentes registradas.
    """
    inicio_pipeline = datetime.now()

    logger.info("#" + "═" * 58 + "#")
    logger.info("#  PIPELINE INGESTA — FASE 1 — PLATAFORMA MORTALIDAD GT   #")
    logger.info("#" + "═" * 58 + "#")
    logger.info(f"Inicio: {inicio_pipeline.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        config = _cargar_config()
    except EnvironmentError as e:
        logger.error(f"Error de configuración: {e}")
        sys.exit(1)

    fuentes = _construir_fuentes(config)

    if fuentes_a_correr:
        invalidas = [f for f in fuentes_a_correr if f not in fuentes]
        if invalidas:
            logger.error(
                f"Fuentes no reconocidas o no activas aun: {invalidas}. "
                f"Activas: {list(fuentes.keys())}"
            )
            sys.exit(1)
        fuentes = {k: v for k, v in fuentes.items() if k in fuentes_a_correr}

    logger.info(f"Fuentes activas a procesar: {list(fuentes.keys())}")
    logger.info("─" * 60)

    reporte_global = {
        "execution_id": inicio_pipeline.strftime("%Y-%m-%d %H:%M:%S"),
        "fuentes": {},
        "resumen": {
            "total_fuentes": len(fuentes),
            "exitosas": 0,
            "con_error":  0,
            "total_filas": 0,
            "duracion_seg":0,
        },
    }

    for clave, meta in fuentes.items():
        logger.info(f"\n Procesando: {clave.upper()}")
        logger.info(f"  {meta['descripcion']}")

        try:
            logger.info("  [1/2] Extrayendo datos...")
            df = meta["extractor"](**meta["kwargs"])
            logger.info(f"  [1/2] OK — {len(df):,} filas extraídas")

            logger.info("  [2/2] Cargando al Sandbox...")
            reporte = load_sandbox(df, fuente=clave, db_url=config["sandbox_url"])
            logger.info(f"  [2/2] OK — {reporte['filas_cargadas']:,} filas en {reporte['tabla']}")

            reporte_global["fuentes"][clave] = reporte
            reporte_global["resumen"]["exitosas"] += 1
            reporte_global["resumen"]["total_filas"]+= reporte["filas_cargadas"]

        except Exception as e:
            logger.error(f"  Error en fuente '{clave}': {e}")
            reporte_global["fuentes"][clave] = {
                "fuente": clave,
                "status": "ERROR",
                "error":  str(e),
            }
            reporte_global["resumen"]["con_error"] += 1
           
    fin      = datetime.now()
    duracion = (fin - inicio_pipeline).total_seconds()
    reporte_global["resumen"]["duracion_seg"] = round(duracion, 1)

    logger.info("\n" + "═" * 60)
    logger.info("RESUMEN DE EJECUCIÓN")
    logger.info("═" * 60)
    logger.info(f"  Fuentes procesadas : {len(fuentes)}")
    logger.info(f"  Exitosas           : {reporte_global['resumen']['exitosas']}")
    logger.info(f"  Con error          : {reporte_global['resumen']['con_error']}")
    logger.info(f"  Total filas        : {reporte_global['resumen']['total_filas']:,}")
    logger.info(f"  Duración total     : {duracion:.1f}s")
    logger.info("═" * 60)

    _guardar_reporte(reporte_global)

    if reporte_global["resumen"]["con_error"] > 0:
        logger.warning("Pipeline completado con errores. Revisa los logs.")
        sys.exit(1)
    else:
        logger.info("Pipeline completado exitosamente")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipeline de ingesta Fase 1 — Plataforma Analítica de Mortalidad GT"
    )
    parser.add_argument(
        "--fuente",
        type=str,
        nargs="+",
        choices=["ine", "world_mortality", "mspas_mec", "mspas_covid", "centroamerica", "oms"],   
        help="Fuente(s) específica(s) a correr. Sin argumento corre todas las activas.",
        default=None,
    )
    args = parser.parse_args()
    run_pipeline(fuentes_a_correr=args.fuente)