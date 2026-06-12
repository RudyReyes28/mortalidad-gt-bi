"""
Orquestador principal del pipeline de ingesta Fase 1.
Ejecuta todos los extractores en secuencia y carga cada resultado
al Sandbox de PostgreSQL

Flujo:
    extract_gdrive()-> sandbox.sandbox_ine            ACTIVO
    extract_s3()->  sandbox.sandbox_centroamerica  PENDIENTE
    extract_sharepoint() ->sandbox.sandbox_oms            PENDIENTE
    extract_rds()  -> sandbox.sandbox_fuente_db      PENDIENTE

Uso:
    python main.py  # corre todas las fuentes activas
    python main.py --fuente ine # corre solo una fuente

Para activar una fuente nueva:
    1. implementa extractors/extract_<nombre>.py
    2. Descomenta el import correspondiente abajo
    3. Descomenta la entrada en _construir_fuentes()
    4. Agrega las variables necesarias al .env

"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

#  Cargar .env desde la raíz del proyecto 
# main.py vive en ingesta-fase1/ -> parents[1] = raíz del proyecto
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

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

#  Importar modulos del pipeline 
from extractors.extract_gdrive import extract_gdrive
from extractors.extract_world_mortality_s3 import extract_world_mortality_s3
from extractors.extract_mspas_mec import extract_mspas_mec
from extractors.extract_mspas_covid import extract_mspas_covid
# PENDIENTE — descomenta cuando se implemente el extractor
# from extractors.extract_s3         import extract_s3
# from extractors.extract_sharepoint import extract_sharepoint
# from extractors.extract_rds        import extract_rds

from loaders.load_sandbox import load_sandbox


# Variables de entorno requeridas
def _cargar_config() -> dict:
    """
    Lee y valida las variables de entorno necesarias para las fuentes ACTIVAS.
    """
    config = {
        # Google Drive — INE (ACTIVO)
        "gdrive_credentials": os.getenv("GDRIVE_CREDENTIALS_PATH"),

        # Sandbox destino (siempre obligatorio)
        "sandbox_url": os.getenv("SANDBOX_DB_URL"),

        # Descomentar cuando se active cada fuente
        # AWS S3
        "aws_access_key": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_region": os.getenv("AWS_REGION", "us-east-1"),
        "s3_bucket": os.getenv("S3_BUCKET_NAME"),
        "s3_prefix": os.getenv("S3_PREFIX", "raw/centroamerica/"),

        # SharePoint — OMS/MSPAS
        # "sp_url":  os.getenv("SHAREPOINT_URL"),
        # "sp_user": os.getenv("SHAREPOINT_USER"),
        # "sp_password": os.getenv("SHAREPOINT_PASSWORD"),
        # "sp_folder": os.getenv("SHAREPOINT_FOLDER"),

        # RDS fuente adicional
        # "rds_url": os.getenv("RDS_SOURCE_URL"),
    }

    # Validar solo las obligatorias de fuentes activas
    obligatorias = {
        "gdrive_credentials": "GDRIVE_CREDENTIALS_PATH",
        "sandbox_url": "SANDBOX_DB_URL",
    }
    faltantes = [var for key, var in obligatorias.items() if not config[key]]
    if faltantes:
        raise EnvironmentError(
            f"Variables de entorno faltantes en .env: {faltantes}\n"
            f"Revisa el archivo .env.example para ver qué se necesita."
        )

    return config


# Definicion de fuentes activas
def _construir_fuentes(config: dict) -> dict:
    """
    Registra cada fuente ACTIVA con su extractor y argumentos.

     integrar tu extractor:
        1. Implementa extractors/extract_<nombre>.py
           La función principal debe retornar un pd.DataFrame
        2. Descomenta el import arriba
        3. Descomenta tu bloque aqui
        4. Agrega tus variables al .env y al _cargar_config()
    """
    fuentes = {}

    # ACTIVO — INE desde Google Drive
    fuentes["ine"] = {
        "descripcion": "INE — Estadísticas vitales de defunciones (Google Drive)",
        "extractor": extract_gdrive,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    # ACTIVO - WORLD MORTALITY DESDE S3
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

    # PENDIENTE — Centroamérica desde S3
    # fuentes["centroamerica"] = {
    #     "descripcion": "Fuente centroamericana (AWS S3)",
    #     "extractor":   extract_s3,
    #     "kwargs": {
    #         "bucket": config["s3_bucket"],
    #         "prefix": config["s3_prefix"],
    #         "aws_key": config["aws_access_key"],
    #         "aws_secret": config["aws_secret_key"],
    #         "region": config["aws_region"],
    #     },
    # }

    # ACTIVO — MSPAS Enfermedades Crónicas (MEC) desde Google Drive (CSV)
    fuentes["mspas_mec"] = {
        "descripcion": "MSPAS — Enfermedades Crónicas MEC 2012-2024 (Google Drive / CSV)",
        "extractor": extract_mspas_mec,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    # ACTIVO — MSPAS Fallecidos COVID-19 desde Google Drive (CSV)
    fuentes["mspas_covid"] = {
        "descripcion": "MSPAS — Fallecidos COVID-19 por municipio 2020-2024 (Google Drive / CSV)",
        "extractor": extract_mspas_covid,
        "kwargs": {"ruta_credenciales": config["gdrive_credentials"]},
    }

    #PENDIENTE  — OMS/MSPAS desde SharePoint
    # fuentes["oms"] = {
    #     "descripcion": "OMS / MSPAS (SharePoint)",
    #     "extractor": extract_sharepoint,
    #     "kwargs": {
    #         "sp_url": config["sp_url"],
    #         "usuario":config["sp_user"],
    #         "password":config["sp_password"],
    #         "carpeta":config["sp_folder"],
    #     },
    # }

    #PENDIENTE  — Fuente adicional desde RDS
    # fuentes["fuente_db"] = {
    #     "descripcion": "Fuente adicional (RDS relacional)",
    #     "extractor": extract_rds,
    #     "kwargs": {"db_url": config["rds_url"]},
    # }

    return fuentes


# Guardar reporte de ejecucion
def _guardar_reporte(reporte_global: dict):
    """Guarda el reporte JSON de la ejecución en ingesta-fase1/reportes/."""
    REPORTES.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ruta = REPORTES / f"ejecucion_{timestamp}.json"

    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(reporte_global, f, indent=2, ensure_ascii=False)

    logger.info(f"Reporte guardado en: {ruta}")
    return ruta


#  Pipeline principal 
def run_pipeline(fuentes_a_correr: list = None):
    """
    Ejecuta el pipeline completo o un subconjunto de fuentes activas.

    Parametro:
        fuentes_a_correr : lista de claves a ejecutar.
                           None = todas las fuentes activas.
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

    # Filtrar si se especifico una fuente particular
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

    #  Ejecutar cada fuente 
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
            logger.error(f"  ✗ Error en fuente '{clave}': {e}")
            reporte_global["fuentes"][clave] = {
                "fuente": clave,
                "status": "ERROR",
                "error":  str(e),
            }
            reporte_global["resumen"]["con_error"] += 1
           

    # Resumen final
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


#  Entry point 
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pipeline de ingesta Fase 1 — Plataforma Analítica de Mortalidad GT"
    )
    parser.add_argument(
        "--fuente",
        type=str,
        nargs="+",
        choices=["ine", "world_mortality", "mspas_mec", "mspas_covid"],   #  agrega aquí cada fuente cuando se active
        help="Fuente(s) específica(s) a correr. Sin argumento corre todas las activas.",
        default=None,
    )
    args = parser.parse_args()
    run_pipeline(fuentes_a_correr=args.fuente)