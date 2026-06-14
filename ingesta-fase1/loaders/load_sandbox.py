"""
Módulo de carga centralizada hacia el Sandbox en PostgreSQL.

Este script es el destino final (Load) del pipeline ETL en su primera fase. 
Recibe los DataFrames procesados por cualquiera de los extractores y los 
inserta en sus respectivas tablas dentro del esquema `sandbox`. 
Utiliza una estrategia de carga completa (Truncate + Reload) mediante 
el parámetro `if_exists="replace"`.
"""

import logging
from datetime import datetime

from sqlalchemy import create_engine, text
import pandas as pd

# Logging estructurado 
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("loader.sandbox")

# Tablas válidas por fuente 
TABLAS_PERMITIDAS = {
    "ine":              "sandbox_ine",
    "oms":              "sandbox_oms",
    "centroamerica":    "sandbox_centroamerica",
    "world_mortality":  "sandbox_world_mortality",
    "fuente_db":        "sandbox_fuente_db",
    # MSPAS — fuentes Eiler
    "mspas_mec":        "sandbox_mspas_mec",        # Enfermedades crónicas 2012-2024
    "mspas_covid":      "sandbox_mspas_covid",       # Fallecidos COVID-19 2020-2024
}


def _crear_engine(db_url: str):
    """
    Establece y valida la conexión a la base de datos PostgreSQL de destino.

    Args:
        db_url (str): Cadena de conexión SQLAlchemy (ej. `postgresql://user:pass@host/db`).

    Returns:
        sqlalchemy.engine.Engine: Motor de base de datos listo para transacciones.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: Si la conexión a la base de datos falla.
    """
    logger.info("Conectando a PostgreSQL...")
    engine = create_engine(db_url, pool_pre_ping=True)
    # Prueba la conexión antes de continuar
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    logger.info("Conexión exitosa.")
    return engine


def _asegurar_schema(engine):
    """
    Garantiza la existencia del esquema 'sandbox' en la base de datos.

    Si el esquema no existe, ejecuta la sentencia SQL para crearlo. 
    Esto es útil para despliegues iniciales en entornos limpios.

    Args:
        engine (sqlalchemy.engine.Engine): Motor de base de datos activo.
    """
    with engine.begin() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS sandbox"))
    logger.info("Schema 'sandbox' verificado.")


def load_sandbox(df: pd.DataFrame, fuente: str, db_url: str) -> dict:
    """
    Inserta el DataFrame consolidado en la tabla correspondiente del Sandbox.

    El proceso sigue una estrategia destructiva inicial (`if_exists="replace"`), 
    lo que significa que la tabla se borra y se vuelve a crear en cada ejecución 
    para asegurar que los datos crudos estén sincronizados con la fuente original 
    sin arrastrar duplicados históricos. La inserción se hace por lotes (chunks) 
    para no saturar la memoria del servidor de base de datos.

    Args:
        df (pd.DataFrame): Datos crudos consolidados por el extractor.
        fuente (str): Clave identificadora de la fuente. Debe existir dentro 
            del diccionario `TABLAS_PERMITIDAS` (ej. 'ine', 'oms').
        db_url (str): Cadena de conexión hacia la base de datos de destino.

    Returns:
        dict: Un diccionario con el reporte detallado de la ejecución, el cual 
            incluye claves como `fuente`, `tabla`, `filas_cargadas`, `status`, 
            `duracion_seg` y `error`. Ideal para el orquestador `main.py`.

    Raises:
        ValueError: Si la clave proporcionada en `fuente` no está permitida.
        Exception: Si ocurre un error a nivel de base de datos durante la 
            inserción de los lotes (`to_sql`).
    """
    # Validar fuente
    if fuente not in TABLAS_PERMITIDAS:
        raise ValueError(
            f"Fuente '{fuente}' no reconocida. "
            f"Valores válidos: {list(TABLAS_PERMITIDAS.keys())}"
        )

    tabla  = TABLAS_PERMITIDAS[fuente]
    tabla_full = f"sandbox.{tabla}"       # schema.tabla
    inicio  = datetime.now()

    logger.info("=" * 60)
    logger.info(f"INICIO — Carga Sandbox")
    logger.info(f"  Fuente  : {fuente}")
    logger.info(f"  Tabla   : {tabla_full}")
    logger.info(f"  Filas   : {len(df):,}")
    logger.info(f"  Columnas: {len(df.columns)}")
    logger.info("=" * 60)

    engine = _crear_engine(db_url)
    _asegurar_schema(engine)

    try:
        # REPLACE = truncate + reload
        # Si la tabla no existe la crea; si existe la reemplaza.
        df.to_sql(
            name=tabla,
            con=engine,
            schema="sandbox",
            if_exists="replace",    # anti-duplicados
            index=False,
            chunksize=5000,         # inserta de a 5000 filas para no saturar la BD
            method="multi",
        )

        fin = datetime.now()
        duracion=(fin - inicio).total_seconds()

        logger.info("-" * 60)
        logger.info(f"Carga completada exitosamente.")
        logger.info(f"  Tabla   : {tabla_full}")
        logger.info(f"  Filas   : {len(df):,}")
        logger.info(f"  Duración: {duracion:.1f}s")
        logger.info("=" * 60)

        reporte = {
            "fuente": fuente,
            "tabla": tabla_full,
            "filas_cargadas": len(df),
            "columnas": list(df.columns),
            "inicio": inicio.strftime("%Y-%m-%d %H:%M:%S"),
            "fin":  fin.strftime("%Y-%m-%d %H:%M:%S"),
            "duracion_seg": round(duracion, 1),
            "status": "SUCCESS",
            "error": None,
        }

    except Exception as e:
        logger.error(f"Error durante la carga a {tabla_full}: {e}")
        reporte = {
            "fuente":fuente,
            "tabla":  tabla_full,
            "filas_cargadas": 0,
            "columnas":  [],
            "inicio": inicio.strftime("%Y-%m-%d %H:%M:%S"),
            "fin": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "duracion_seg": 0,
            "status":"ERROR",
            "error":  str(e),
        }
        raise

    finally:
        engine.dispose()

    return reporte

# Ejecucion directa para prueba local 
if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path
    from dotenv import load_dotenv

    # Cargar .env desde la raíz del proyecto
    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)
    print(f"Cargando .env desde: {env_path}")

    DB_URL = os.getenv("SANDBOX_DB_URL")
    if not DB_URL:
        raise EnvironmentError(
            "Variable SANDBOX_DB_URL no encontrada en el .env.\n"
            "Ejemplo: SANDBOX_DB_URL=postgresql://user:pass@localhost:5432/mortalidad_sandbox"
        )

    # Para prueba rápida: carga un CSV local si no quieres correr el extractor completo
    TEST_CSV = Path(__file__).resolve().parents[1] / "test_data" / "muestra_ine.csv"

    if TEST_CSV.exists():
        print(f"\nCargando datos de prueba desde: {TEST_CSV}")
        df_test = pd.read_csv(TEST_CSV)
    else:
        # Si no hay CSV de prueba, corre el extractor real
        print("\nNo se encontró CSV de prueba. Corriendo extractor de Google Drive...")
        sys.path.append(str(Path(__file__).resolve().parents[0] / "extractors"))
        from extractors.extract_gdrive import extract_gdrive

        CREDENCIALES = os.getenv("GDRIVE_CREDENTIALS_PATH")
        df_test = extract_gdrive(CREDENCIALES)

    reporte = load_sandbox(df_test, fuente="ine", db_url=DB_URL)

    print(f"\nReporte de carga:")
    for k, v in reporte.items():
        print(f"  {k}: {v}")