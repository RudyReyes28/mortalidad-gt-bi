"""
Extrae datos de mortalidad de Centroamerica (Panamá y Costa Rica)
desde el RDS PostgreSQL y retorna un DataFrame consolidado

Fuente  : RDS PostgreSQL — sandbox.sandbox_centroamerica_panama
                         — sandbox.sandbox_centroamerica_costa_rica
"""

import logging
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

# Logging estructurado
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("extractor.rds")

# Tablas fuente en RDS
TABLAS_FUENTE = {
    "panama":      "sandbox.sandbox_centroamerica_panama",
    "costa_rica":  "sandbox.sandbox_centroamerica_costa_rica",
}

# Columnas estandar de salida
# Se normalizan las columnas de ambas tablas a un schema comun
# para que el Sandbox tenga una tabla unificada de Centroamerica.
COLUMNAS_SALIDA = [
    "pais",
    "anio",
    "defunciones_general",
    "defunciones_infantil_menores_de_un_anio",
    "defunciones_menores_de_5_anios",
    "defunciones_materna",
    "defunciones_de_mujeres_en_edad_fertil",
    "poblacion_total",
    "tasa_bruta_mortalidad_por_mil",
    "fuente_origen",
    "archivo_origen",
    "fecha_carga",
]


#Conexion al RDS
def _crear_engine(db_url: str):
    """
    Crea y verifica la conexión al RDS PostgreSQL.
    """
    logger.info("Conectando al RDS PostgreSQL...")
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexion al RDS exitosa.")
        return engine
    except SQLAlchemyError as e:
        raise ConnectionError(f"No se pudo conectar al RDS: {e}")


# Extraer y normalizar Panama
def _extraer_panama(engine) -> pd.DataFrame:
    logger.info("Extrayendo datos de Panamá...")
    query = "SELECT * FROM sandbox.sandbox_centroamerica_panama ORDER BY anio"
    df = pd.read_sql(query, engine)
    logger.info(f"  -> {len(df):,} filas leídas desde Panama")

    df_normalizado = pd.DataFrame({
        "pais": "Panama",
        "anio": df["anio"],
        "defunciones_general": df["defunciones_general"],
        "defunciones_infantil_menores_de_un_anio": df["defunciones_infantil_menores_de_un_anio"],
        "defunciones_menores_de_5_anios": df["defunciones_menores_de_5_anios"],
        "defunciones_materna":  df["defunciones_materna"],
        "defunciones_de_mujeres_en_edad_fertil":   df["defunciones_de_mujeres_en_edad_fertil"],
        "poblacion_total":  None,
        "tasa_bruta_mortalidad_por_mil": None,
        "fuente_origen": df["fuente_origen"],
        "archivo_origen": df["archivo_origen"],
        "fecha_carga":  datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return df_normalizado


def _extraer_costa_rica(engine) -> pd.DataFrame:
    logger.info("Extrayendo datos de Costa Rica...")
    query = "SELECT * FROM sandbox.sandbox_centroamerica_costa_rica ORDER BY anio"
    df = pd.read_sql(query, engine)
    logger.info(f" -> {len(df):,} filas leídas desde Costa Rica")

    df_normalizado = pd.DataFrame({
        "pais": "Costa Rica",
        "anio": df["anio"],
        "defunciones_general": df["defunciones"],
        "defunciones_infantil_menores_de_un_anio": None,
        "defunciones_menores_de_5_anios": None,
        "defunciones_materna": None,
        "defunciones_de_mujeres_en_edad_fertil": None,
        "poblacion_total": df["poblacion_total_al_30_de_junio"],
        "tasa_bruta_mortalidad_por_mil": df["tasa_bruta_de_mortalidad_por_mil_habitantes"],
        "fuente_origen": df["fuente_origen"],
        "archivo_origen": df["archivo_origen"],
        "fecha_carga": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return df_normalizado


# Funcion principal exportada
def extract_rds(db_url: str) -> pd.DataFrame:
    """
    Punto de entrada del extractor RDS.

    Retorna:
        pd.DataFrame con todos los registros de Centroamérica
        listos para el Sandbox (sandbox.sandbox_fuente_db).
    """
    logger.info("=" * 60)
    logger.info("INICIO — Extractor RDS (Centroamerica: Panama + Costa Rica)")
    logger.info("=" * 60)

    engine = _crear_engine(db_url)
    dataframes = []
    errores = []

    # Extraer cada país
    extractores_pais = {
        "Panama":  _extraer_panama,
        "Costa Rica": _extraer_costa_rica,
    }

    for pais, extractor_fn in extractores_pais.items():
        try:
            df = extractor_fn(engine)
            dataframes.append(df)
        except Exception as e:
            logger.error(f"Error extrayendo {pais}: {e}")
            errores.append(pais)

    engine.dispose()

    if not dataframes:
        raise RuntimeError("No se pudo extraer ningún país. Revisa la conexión al RDS.")

    if errores:
        logger.warning(f"Países con error (no incluidos): {errores}")

    df_consolidado = pd.concat(dataframes, ignore_index=True)

    # Verificar que el orden de columnas sea el estándar
    df_consolidado = df_consolidado[COLUMNAS_SALIDA]

    logger.info("-" * 60)
    logger.info("Extracción completada.")
    logger.info(f"  Países procesados : {len(dataframes)}")
    logger.info(f"  Países con error  : {len(errores)}")
    logger.info(f"  Total filas       : {len(df_consolidado):,}")
    logger.info(f"  Países en data    : {df_consolidado['pais'].unique().tolist()}")
    logger.info(f"  Rango de años     : {df_consolidado['anio'].min()} — {df_consolidado['anio'].max()}")
    logger.info("=" * 60)

    return df_consolidado


# Ejecucion directa para pruebas locales
if __name__ == "__main__":
    import os
    from pathlib import Path
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parents[2] / ".env"
    load_dotenv(env_path)
    print(f"Cargando .env desde: {env_path}")

    RDS_URL = os.getenv("RDS_SOURCE_URL")
    if not RDS_URL:
        raise EnvironmentError(
            "Variable RDS_SOURCE_URL no encontrada en .env.\n"
            "Formato: postgresql://postgres:password@<host>.rds.amazonaws.com:5432/mortalidad_sandbox"
        )

    df = extract_rds(RDS_URL)

    print(f"\nResumen del DataFrame consolidado:")
    print(f"  Shape      : {df.shape}")
    print(f"  Columnas   : {list(df.columns)}")
    print(f"  Países     : {df['pais'].unique().tolist()}")
    print(f"  Rango años : {df['anio'].min()} — {df['anio'].max()}")
    print(f"\nPrimeras 3 filas:")
    print(df.head(3).to_string())
    print(f"\nValores NULL por columna:")
    nulls = df.isnull().sum()
    print(nulls[nulls > 0] if nulls.any() else "  Sin valores NULL.")